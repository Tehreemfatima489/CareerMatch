from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from users.utils import get_or_create_skill
from .tasks import on_job_posted 
from .models import Job, Compatibility, InterviewInvite, JobSkill
from users.models import ApplicantProfile, Skill
from itertools import groupby
from operator import attrgetter
from constants import DEGREE_LEVEL_MODEL_CHOICES
from jobs.models import (
    SkillMatchFeedback, SkillAliasOverride, SkillDistinctOverride,
    TitleMatchFeedback, TitleMatchOverride, MatchFlag,
)
from .services import _approve_skill_feedback, _approve_title_feedback
from django.core.paginator import Paginator


def _parse_float(value, default=0.0):
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default



# POST JOB

@login_required
def post_job(request):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile

    if request.method == "POST":
        raw_required = request.POST.get("required_skills", "")
        required_names = [n.strip() for n in raw_required.split(",") if n.strip()]

        if not required_names:
            return render(request, "company/post_job.html", {
                "degree_level_choices": DEGREE_LEVEL_MODEL_CHOICES,
                "form_data": request.POST,
            })

        job = Job.objects.create(
            company=company,
            title=request.POST["title"],
            description=request.POST["description"],
            level=request.POST["level"],
            location=request.POST.get("location", ""),
            education_required=request.POST.get("education_required", ""),
            required_degree_level=request.POST.get("required_degree_level") or None,
            experience_required=_parse_float(request.POST.get("experience_required"), 0.0),
            salary=request.POST.get("salary") or None,
            accept_related_education_fields=request.POST.get("accept_related_education_fields") == "on",
        )

        # Required skills
        for name in required_names:
            skill = get_or_create_skill(name)
            JobSkill.objects.get_or_create(job=job, skill=skill, defaults={"is_optional": False})

        # Optional skills
        raw_optional = request.POST.get("optional_skills", "")
        for name in raw_optional.split(","):
            name = name.strip()
            if name:
                skill = get_or_create_skill(name)
                JobSkill.objects.get_or_create(job=job, skill=skill, defaults={"is_optional": True})
        
        on_job_posted.delay(job.pk) 
        return redirect("manage_jobs")

    return render(request, "company/post_job.html", {
        "degree_level_choices": DEGREE_LEVEL_MODEL_CHOICES,
    })

# MANAGE JOBS 

@login_required
def manage_jobs(request):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile
    jobs = Job.objects.filter(company=company)

    for job in jobs:
        job.total_candidates = Compatibility.objects.filter(job=job).count()
        job.qualified_candidates = Compatibility.objects.filter(job=job, score__gte=30).count()
        job.invited_candidates = InterviewInvite.objects.filter(job=job).count()

    return render(request, "company/manage_jobs.html", {
        "jobs": jobs
    })


# EDIT JOB

@login_required
def edit_job(request, job_id):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile
    job = get_object_or_404(Job, id=job_id, company=company)

    if request.method == "POST":
        raw_required = request.POST.get("required_skills", "")
        required_names = [n.strip() for n in raw_required.split(",") if n.strip()]

        if not required_names:
            return render(request, "company/edit_job.html", {
                "job": job,
                "required_str": raw_required,
                "optional_str": request.POST.get("optional_skills", ""),
                "degree_level_choices": DEGREE_LEVEL_MODEL_CHOICES,
            })

        job.title = request.POST.get("title", job.title)
        job.description = request.POST.get("description", job.description)
        job.level = request.POST.get("level", job.level)
        job.location = request.POST.get("location", job.location)
        job.education_required = request.POST.get("education_required", job.education_required)
        job.required_degree_level = request.POST.get("required_degree_level") or None
        job.experience_required = _parse_float(request.POST.get("experience_required"), job.experience_required)
        job.salary = request.POST.get("salary") or None
        job.accept_related_education_fields = request.POST.get("accept_related_education_fields") == "on"
        job.save()

        JobSkill.objects.filter(job=job).delete()

        for name in required_names:
            skill = get_or_create_skill(name)
            JobSkill.objects.get_or_create(job=job, skill=skill, defaults={"is_optional": False})

        raw_optional = request.POST.get("optional_skills", "")
        for name in raw_optional.split(","):
            name = name.strip()
            if name:
                skill = get_or_create_skill(name)
                JobSkill.objects.get_or_create(job=job, skill=skill, defaults={"is_optional": True})
        on_job_posted.delay(job.pk) 
        return redirect("manage_jobs")

    required_str = ", ".join(job.required_skill_names)
    optional_str = ", ".join(job.optional_skill_names)

    return render(request, "company/edit_job.html", {
        "job": job,
        "required_str": required_str,
        "optional_str": optional_str,
        "degree_level_choices": DEGREE_LEVEL_MODEL_CHOICES,
    })



# DELETE JOB

@login_required
def delete_job(request, job_id):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile
    job = get_object_or_404(Job, id=job_id, company=company)

    if request.method == "POST":
        job.delete()
        return redirect("manage_jobs")

    return render(request, "company/confirm_delete_job.html", {"job": job})


# CANDIDATE SCORE BREAKDOWN (company-facing)

@login_required
def candidate_breakdown(request, job_id, applicant_id):
    is_admin = request.user.is_superuser

    if not hasattr(request.user, "companyprofile") and not is_admin:
        return redirect("dashboard")

    job = get_object_or_404(Job, id=job_id)

    if not is_admin:
        company = request.user.companyprofile
        if job.company_id != company.id:
            return redirect("dashboard")
    match = get_object_or_404(Compatibility, job=job, user_id=applicant_id)
    applicant = match.user

    weights = {
        "entry":  {"skills": 0.60, "education": 0.30, "experience": 0.10},
        "mid":    {"skills": 0.50, "education": 0.20, "experience": 0.30},
        "senior": {"skills": 0.40, "education": 0.10, "experience": 0.50},
    }
    w = weights.get(job.level, weights["entry"])

    # Skills
    user_skills     = list(applicant.skills.values_list("name", flat=True))
    required_skills = job.required_skill_names
    optional_skills = job.optional_skill_names
    all_job_skills  = required_skills + optional_skills
    missing_set     = set(match.missing_skills or [])
    job_skill_set   = set(required_skills + optional_skills)

    # Only the records the score was actually based on
    matched_educations = (
        applicant.educations.filter(id=match.matched_education_id)
        if match.matched_education_id else applicant.educations.none()
    )
    relevant_exp_ids = set(match.relevant_experience_ids or [])
    relevant_experiences = (
        applicant.experiences.filter(id__in=relevant_exp_ids)
        if relevant_exp_ids else applicant.experiences.none()
    )

    total_exp = sum(exp.years for exp in relevant_experiences)
    total_exp = round(total_exp, 1)

    breakdown = {
        "skill": {
            "score":            round(match.skill_score, 1),
            "weight":           int(w["skills"] * 100),
            "missing":          match.missing_skills or [],
            "matched_required": [s for s in required_skills if s not in missing_set],
            "missing_required": list(match.missing_skills or []),
            "matched_optional": [s for s in optional_skills if s in user_skills],
            "missing_optional": [s for s in optional_skills if s not in user_skills],
            "bonus_skills": [s for s in user_skills if s not in set(match.matched_skill_names or [])],
        },
        "education": {
            "score":  round(match.education_score, 1),
            "weight": int(w["education"] * 100),
        },
        "experience": {
            "score":       round(match.experience_score, 1),
            "weight":      int(w["experience"] * 100),
            "total_years": total_exp,
            "exceeds":     match.exceeds_experience,
            "gap":         round(max(job.experience_required - total_exp, 0), 1),
        },
    }

    return render(request, "company/candidate_breakdown.html", {
        "job":                  job,
        "applicant":            applicant,
        "match":                match,
        "breakdown":            breakdown,
        "all_job_skills":       all_job_skills,
        "user_skills":          user_skills,
        "matched_educations":   matched_educations,
        "relevant_experiences": relevant_experiences,
    })
# DOWNLOAD RESUME

@login_required
def download_resume(request, applicant_id):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    applicant = get_object_or_404(ApplicantProfile, id=applicant_id)

    if not applicant.resume:
        return redirect("manage_jobs")

    return redirect(applicant.resume.url)



# SENT INVITATIONS TRACKER

@login_required
def sent_invitations(request):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile

    invites = (
        InterviewInvite.objects
        .filter(job__company=company)
        .select_related("job", "applicant")
        .order_by("job_id", "-sent_at")   
    )

    grouped = []
    for job, group in groupby(invites, key=attrgetter("job")):
        group_list = list(group)
        grouped.append({
            "job": job,
            "invites": group_list,
            "count": len(group_list),
            "latest": group_list[0].sent_at,
        })

    grouped.sort(key=lambda g: g["latest"], reverse=True)

    return render(request, "company/sent_invitations.html", {
        "grouped": grouped
    })



# TALENT SEARCH (RANKED LEADERBOARD)


@login_required
def view_applicants(request, job_id):
    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile
    job = get_object_or_404(Job, id=job_id, company=company)

    candidates_qs = (
        Compatibility.objects
        .filter(job=job, score__gte=30, user__is_open_to_opportunities=True)
        .select_related("user", "user__user")
        .order_by("-score")
    )

    paginator = Paginator(candidates_qs, 20)  # 20 candidates per page
    page_number = request.GET.get("page")
    candidates = paginator.get_page(page_number)

    invite_map = {
        inv.applicant_id: inv
        for inv in InterviewInvite.objects.filter(job=job)
                                          .select_related("applicant")
    }

    invited = set(invite_map.keys())

    return render(request, "company/view_applicants.html", {
        "job":            job,
        "candidates":     candidates,       
        "total_count":    paginator.count,  
        "invited":        invited,
        "invite_map":     invite_map,
    })


# SEND INVITE

@login_required
def send_invite(request, job_id, applicant_id):
    if request.method != "POST":
        return redirect("manage_jobs")

    if not hasattr(request.user, "companyprofile"):
        return redirect("dashboard")

    company = request.user.companyprofile
    job = get_object_or_404(Job, id=job_id, company=company)
    applicant = get_object_or_404(ApplicantProfile, id=applicant_id)

    if InterviewInvite.objects.filter(job=job, applicant=applicant).exists():
        return redirect("view_applicants", job_id=job.id)

    match = Compatibility.objects.filter(user=applicant, job=job).first()
    score = match.score if match else 0

    InterviewInvite.objects.create(
        job=job,
        applicant=applicant,
        compatibility_score=score,
        message=request.POST.get(
            "message",
            "We reviewed your profile and would like to talk with you regarding this opportunity."
        ),
        status="pending"
    )

    return redirect("view_applicants", job_id=job.id)



#############################feeddback views

@login_required
def submit_skill_feedback(request, job_id, applicant_id):
    if request.method != "POST":
        return redirect("candidate_breakdown", job_id=job_id, applicant_id=applicant_id)

    is_admin = request.user.is_superuser
    if not hasattr(request.user, "companyprofile") and not is_admin:
        return redirect("dashboard")

    job = get_object_or_404(Job, id=job_id)
    if not is_admin and job.company_id != request.user.companyprofile.id:
        return redirect("dashboard")

    submitted_by = None if is_admin else request.user.companyprofile

    fb = SkillMatchFeedback.objects.create(
        job=job,
        applicant_id=applicant_id,
        submitted_by=submitted_by,
        job_skill_text=request.POST.get("job_skill", "").strip(),
        user_skill_text=request.POST.get("user_skill", "").strip(),
        judged_same=request.POST.get("judgment") == "same",
    )

    if is_admin:
        _approve_skill_feedback(fb, reviewed_by=request.user)

    return redirect("candidate_breakdown", job_id=job_id, applicant_id=applicant_id)

@login_required
def submit_title_feedback(request, job_id, applicant_id):
    if request.method != "POST":
        return redirect("candidate_breakdown", job_id=job_id, applicant_id=applicant_id)

    is_admin = request.user.is_superuser
    if not hasattr(request.user, "companyprofile") and not is_admin:
        return redirect("dashboard")

    job = get_object_or_404(Job, id=job_id)
    if not is_admin and job.company_id != request.user.companyprofile.id:
        return redirect("dashboard")

    kind = request.POST.get("kind")
    if kind not in ("experience_role", "education_field"):
        return redirect("candidate_breakdown", job_id=job_id, applicant_id=applicant_id)

    submitted_by = None if is_admin else request.user.companyprofile

    fb = TitleMatchFeedback.objects.create(
        kind=kind,
        job=job,
        applicant_id=applicant_id,
        submitted_by=submitted_by,
        job_text=request.POST.get("job_text", "").strip(),
        user_text=request.POST.get("user_text", "").strip(),
        judged_same=request.POST.get("judgment") == "same",
    )

    if is_admin:
        _approve_title_feedback(fb, reviewed_by=request.user)

    return redirect("candidate_breakdown", job_id=job_id, applicant_id=applicant_id)