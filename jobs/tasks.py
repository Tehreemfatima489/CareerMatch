import numpy as np
import logging
from celery import shared_task, chain, group
from django.db import transaction
from constants import DEGREE_LEVEL_TIER_MAP

from users.models import ApplicantProfile
from jobs.models import Compatibility, Job
from jobs.services import (
    build_cached_profile_payload,
    calculate_education_score,
    calculate_experience_score,
    calculate_skill_score,
    load_profile_vectors_from_cache,
    model,
    load_job_edu_fields_from_cache,
    precompute_job_education_fields,
    build_cached_job_edu_payload,
    precompute_profile_vectors,
)

logger = logging.getLogger(__name__)
LEVEL_WEIGHTS = {
    "entry":  {"skills": 0.60, "education": 0.30, "experience": 0.10},
    "mid":    {"skills": 0.50, "education": 0.20, "experience": 0.30},
    "senior": {"skills": 0.40, "education": 0.10, "experience": 0.50},
}

QUALITY_THRESHOLD = 30.0
TOP_K_LIMIT       = 30

LEVEL_PENALTY = {
    ("entry",  "entry"):  1.00,
    ("entry",  "mid"):    0.70,
    ("entry",  "senior"): 0.40,
    ("mid",    "entry"):  0.90,
    ("mid",    "mid"):    1.00,
    ("mid",    "senior"): 0.70,
    ("senior", "entry"):  0.80,
    ("senior", "mid"):    0.95,
    ("senior", "senior"): 1.00,
}


def _is_profile_empty(profile_data: dict) -> bool:
    return (
        profile_data["user_skills_vecs"] is None and
        not profile_data.get("edu_records")
    )
def _score_profile_against_job(profile_data: dict, job: Job, student_level: str = "entry") -> dict | None:

    required_skills = job.required_skill_names
    optional_skills = job.optional_skill_names

    skill_score, missing, matched_skill_names = calculate_skill_score(
        profile_data["user_skills"],
        profile_data["user_skills_vecs"],
        required_skills,
        optional_skills,
    )

    job_edu_fields = load_job_edu_fields_from_cache(job.cached_edu_fields)
    edu_score, matched_education_id = calculate_education_score(
        profile_data.get("edu_records", []),
        job.education_required,
        job_degree_tier=DEGREE_LEVEL_TIER_MAP.get(job.required_degree_level),
        job_edu_fields=job_edu_fields,
        accept_related_education_fields=job.accept_related_education_fields,
    )

    job_title_vec = np.array(job.cached_title_vec) if job.cached_title_vec else None

    exp_score, exceeds_experience, relevant_experience_ids = calculate_experience_score(
        exp_records=profile_data.get("exp_records", []),
        required_skills=required_skills,
        experience_required=float(job.experience_required or 0.0),
        job_title=job.title,
        job_title_vec=job_title_vec,
        overall_skill_score=skill_score,
        relevance_threshold=30.0,
    )

    w = LEVEL_WEIGHTS.get(job.level, LEVEL_WEIGHTS["entry"])
    raw_score = (
        (skill_score * w["skills"]) +
        (edu_score   * w["education"]) +
        (exp_score   * w["experience"])
    )

    penalty     = LEVEL_PENALTY.get((student_level, job.level), 0.80)
    final_score = round(raw_score * penalty, 2)

    if final_score < QUALITY_THRESHOLD:
        return None

    return {
        "score":                    final_score,
        "skill_score":              skill_score,
        "education_score":          edu_score,
        "experience_score":         exp_score,
        "missing_skills":           missing,
        "matched_skill_names":      matched_skill_names, 
        "exceeds_experience":       exceeds_experience,
        "matched_education_id":     matched_education_id,
        "relevant_experience_ids":  relevant_experience_ids,
    }





@shared_task
def precompute_job_vector(job_id):
    try:
        job = Job.objects.prefetch_related("required_skills").get(pk=job_id)
    except Job.DoesNotExist:
        return "JOB_NOT_FOUND"

    title_vec = model.encode(job.title.strip())
    serialized_edu_fields = build_cached_job_edu_payload(job.education_required)

    Job.objects.filter(pk=job_id).update(
        cached_title_vec=title_vec.tolist(),
        cached_edu_fields=serialized_edu_fields,
    )
    return f"JOB_VECTOR_CACHED_{job_id}"


@shared_task
def cache_profile_vectors(user_id):
    try:
        profile = ApplicantProfile.objects.prefetch_related(
            "skills", "experiences", "educations"
        ).get(id=user_id)
    except ApplicantProfile.DoesNotExist:
        return "PROFILE_NOT_FOUND"

    payload = build_cached_profile_payload(profile)
    ApplicantProfile.objects.filter(id=user_id).update(
        cached_profile_data=payload
    )
    return f"PROFILE_VECTORS_CACHED_{user_id}"


@shared_task
def generate_matches_for_student(user_id):
    try:
        profile = ApplicantProfile.objects.prefetch_related(
            "skills", "experiences", "educations"
        ).get(id=user_id)
    except ApplicantProfile.DoesNotExist:
        return "PROFILE_NOT_FOUND"

    profile_data  = precompute_profile_vectors(profile)
    student_level = profile.current_level

   
    if _is_profile_empty(profile_data):
        with transaction.atomic():
            Compatibility.objects.filter(user=profile).delete()
        return "PROFILE_EMPTY_SKIPPED"

    all_matches = []

    jobs_qs = (
        Job.objects
        .prefetch_related("job_skills__skill")
        .filter(is_active=True)
        .exclude(cached_title_vec=None)      
        .iterator(chunk_size=100)
    )

    for job in jobs_qs:
        try:
            result = _score_profile_against_job(profile_data, job, student_level)
        except Exception:
            logger.exception(f"Scoring failed for job_id={job.id}, user_id={user_id}")
            continue
        if result:
            all_matches.append({"job": job, **result})

    all_matches = sorted(
        all_matches, key=lambda x: x["score"], reverse=True
    )[:TOP_K_LIMIT]

    bulk = [
        Compatibility(
            user=profile,
            job=item["job"],
            score=item["score"],
            skill_score=item["skill_score"],
            education_score=item["education_score"],
            experience_score=item["experience_score"],
            missing_skills=item["missing_skills"],
            exceeds_experience=item["exceeds_experience"],
            matched_skill_names=item["matched_skill_names"],
            matched_education_id=item["matched_education_id"],
            relevant_experience_ids=item["relevant_experience_ids"],
        )
        for item in all_matches
    ]

    with transaction.atomic():
        Compatibility.objects.filter(user=profile).delete()
        Compatibility.objects.bulk_create(bulk, ignore_conflicts=True)

    return f"STUDENT_MATCHES_GENERATED_{len(bulk)}_FOR_USER_{user_id}"


@shared_task
def generate_matches_for_job(job_id):
    try:
        job = Job.objects.prefetch_related("job_skills__skill").get(pk=job_id)
    except Job.DoesNotExist:
        return "JOB_NOT_FOUND"

    if not job.cached_title_vec:            
        return "JOB_VECTOR_NOT_READY"

    profiles_qs = (
    ApplicantProfile.objects
    .exclude(cached_profile_data=None)
    .filter(is_open_to_opportunities=True)
    .iterator(chunk_size=100)
    )

    bulk         = []
    scored_count = 0

    for profile in profiles_qs:
        profile_data  = load_profile_vectors_from_cache(profile.cached_profile_data)
        student_level = profile.current_level

      
        if _is_profile_empty(profile_data):
            continue

        scored_count += 1
        try:
            result = _score_profile_against_job(profile_data, job, student_level)
        except Exception:
            logger.exception(f"Scoring failed for profile_id={profile.id}, job_id={job_id}")
            continue

        if result:
            bulk.append(
                Compatibility(
                    user=profile,
                    job=job,
                    score=result["score"],
                    skill_score=result["skill_score"],
                    education_score=result["education_score"],
                    experience_score=result["experience_score"],
                    missing_skills=result["missing_skills"],
                    exceeds_experience=result["exceeds_experience"],
                    matched_education_id=result["matched_education_id"],
                    matched_skill_names=result["matched_skill_names"],
                    relevant_experience_ids=result["relevant_experience_ids"],
                )
            )

    with transaction.atomic():
        Compatibility.objects.filter(job=job).delete()
        Compatibility.objects.bulk_create(bulk, ignore_conflicts=True)

    return (
        f"JOB_MATCHES_GENERATED_FOR_JOB_{job_id} | "
        f"SCORED={scored_count} | STORED={len(bulk)}"
    )

@shared_task
def on_job_posted(job_id):
    student_ids = list(
        ApplicantProfile.objects.filter(is_open_to_opportunities=True)
        .values_list("id", flat=True)
    )

    steps = [precompute_job_vector.si(job_id), generate_matches_for_job.si(job_id)]
    if student_ids:
        steps.append(group(generate_matches_for_student.si(pid) for pid in student_ids))

    chain(*steps).delay()
    return f"JOB_POSTED_CHAIN_QUEUED_{job_id}"
