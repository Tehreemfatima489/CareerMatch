"""
Demo data seeder for CareerMatch — standalone version.

WHERE TO PUT THIS FILE:
    Same folder as manage.py (project root).

HOW TO RUN:
    python seed_demo_data.py

WHAT THIS DOES:
    Same as the management-command version: creates 3 companies, 3 jobs
    (entry / mid / senior) covering both the "related fields accepted"
    and "strict multi-field" education cases, and 15 applicants (A-O)
    covering skill aliasing, acronym matching, typo matching, education
    phrasing variation, experience-title phrasing variation, a
    distinct-skill-variant trap, a related-but-different education
    trap, a same-title-different-skills trap, a level-penalty isolation
    case, and a multi-role/multi-degree candidate built for the Skill
    Compass demo.

    Every user gets the SAME password (set below) and is created with
    is_verified=True, bypassing the OTP flow entirely (this script
    writes straight to the DB — it doesn't go through the register
    views, so no OTP email is ever sent).

    Safe to re-run: uses get_or_create keyed on email/title, so running
    it twice won't create duplicates.

AFTER RUNNING:
    Job/profile vectors are NOT cached yet (this script doesn't touch
    Celery). See the commented-out block at the very bottom for how to
    trigger that automatically once your worker is running.
"""

import os
import django

# ---------------------------------------------------------------------
# Bootstrap Django so this file can run standalone with `python seed_demo_data.py`
# instead of needing to be a registered app's management command.
# CHANGE "config.settings" below if your settings module has a different path.
# ---------------------------------------------------------------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from datetime import date, timedelta

from django.contrib.auth import get_user_model

from users.models import ApplicantProfile, CompanyProfile, Skill, Education, Experience
from users.utils import get_or_create_skill
from jobs.models import Job, JobSkill

User = get_user_model()

DEMO_PASSWORD = "Demo@1234"

# Confirmed against constants.py — these match DEGREE_LEVEL_MODEL_CHOICES exactly.
DEGREE_BACHELORS = "bachelors"
DEGREE_MASTERS = "masters"


def _make_verified_user(email, full_name=None, company_name=None):
    """Creates (or fetches) a user + profile, bypassing OTP by setting
    is_verified=True directly."""
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"is_verified": True},
    )
    if created:
        user.set_password(DEMO_PASSWORD)
        user.is_verified = True
        user.save()

    if company_name is not None:
        profile, _ = CompanyProfile.objects.get_or_create(
            user=user, defaults={"company_name": company_name}
        )
    else:
        profile, _ = ApplicantProfile.objects.get_or_create(
            user=user, defaults={"full_name": full_name}
        )
    return user, profile


def _add_education(applicant, degree, degree_level, institution, years_ago_start, years_ago_end=None):
    start = date.today() - timedelta(days=365 * years_ago_start)
    end = None
    if years_ago_end is not None:
        end = date.today() - timedelta(days=365 * years_ago_end)
    Education.objects.get_or_create(
        applicant=applicant,
        degree=degree,
        defaults={
            "degree_level": degree_level,
            "institution": institution,
            "start_date": start,
            "end_date": end,
        },
    )


def _add_experience(applicant, role, company, skill_names, years_ago_start, years_ago_end=None, is_current=False):
    start = date.today() - timedelta(days=365 * years_ago_start)
    end = None
    if years_ago_end is not None:
        end = date.today() - timedelta(days=365 * years_ago_end)
    exp, created = Experience.objects.get_or_create(
        applicant=applicant,
        role=role,
        company=company,
        defaults={
            "start_date": start,
            "end_date": end,
            "is_current": is_current,
        },
    )
    if created:
        skills = [get_or_create_skill(name) for name in skill_names]
        exp.skills_used.set(skills)
        applicant.skills.add(*skills)
    return exp


def _add_job_skills(job, required=None, optional=None):
    for name in (required or []):
        skill = get_or_create_skill(name)
        JobSkill.objects.get_or_create(job=job, skill=skill, defaults={"is_optional": False})
    for name in (optional or []):
        skill = get_or_create_skill(name)
        JobSkill.objects.get_or_create(job=job, skill=skill, defaults={"is_optional": True})


def seed_jobs():
    _, techcorp = _make_verified_user("hr@techcorp-demo.com", company_name="TechCorp")
    _, dataworks = _make_verified_user("hr@dataworks-demo.com", company_name="DataWorks")
    _, cloudnine = _make_verified_user("hr@cloudnine-demo.com", company_name="CloudNine")

    # Job 1: entry level, RELATED education fields accepted
    job1, _ = Job.objects.get_or_create(
        company=techcorp,
        title="Software Engineer",
        defaults={
            "description": "Entry-level role building and maintaining web features.",
            "level": "entry",
            "location": "Lahore, Pakistan",
            "education_required": "Computer Science",
            "accept_related_education_fields": True,
            "required_degree_level": DEGREE_BACHELORS,
            "experience_required": 0,
        },
    )
    _add_job_skills(job1, required=["Python", "Django", "Git"], optional=["Docker"])

    # Job 2: mid level, multiple strict fields + related credit
    job2, _ = Job.objects.get_or_create(
        company=dataworks,
        title="Data Analyst",
        defaults={
            "description": "Mid-level analyst role turning raw data into reporting.",
            "level": "mid",
            "location": "Lahore, Pakistan",
            "education_required": "Statistics, Mathematics",
            "accept_related_education_fields": True,
            "required_degree_level": DEGREE_BACHELORS,
            "experience_required": 3,
        },
    )
    _add_job_skills(job2, required=["SQL", "Excel", "Power BI"], optional=["Python"])

    # Job 3: senior level, STRICT multi-field, no related credit
    job3, _ = Job.objects.get_or_create(
        company=cloudnine,
        title="Senior Backend Engineer",
        defaults={
            "description": "Senior role owning backend architecture and infra.",
            "level": "senior",
            "location": "Remote",
            "education_required": "Computer Science, Software Engineering",
            "accept_related_education_fields": False,
            "required_degree_level": DEGREE_BACHELORS,
            "experience_required": 5,
        },
    )
    _add_job_skills(job3, required=["Python", "Django", "AWS", "PostgreSQL"], optional=["Redis"])

    return job1, job2, job3


def seed_applicants():
    # A — Skill alias: "JS" / "ReactJS" instead of "JavaScript" / "React"
    _, a = _make_verified_user("applicant.a@demo-mail.com", full_name="Ayesha Khan")
    a.current_level = "entry"
    a.save()
    _add_education(a, "Bachelor of Science in Computer Science", DEGREE_BACHELORS, "UET Lahore", 4, 0)
    _add_experience(a, "Frontend Intern", "StartupHub", ["JS", "ReactJS", "CSS"], 1, 0)

    # B — Acronym: has "AWS" for a job that (in this taxonomy) spells it out
    _, b = _make_verified_user("applicant.b@demo-mail.com", full_name="Bilal Ahmed")
    b.current_level = "senior"
    b.save()
    _add_education(b, "BS Computer Science", DEGREE_BACHELORS, "FAST NUCES", 8, 4)
    _add_experience(b, "Backend Engineer", "CloudBase", ["Python", "Django", "AWS", "PostgreSQL"], 6, 0)

    # C — Typo: "Pyhton" / "Djnago" (1-char edit distance)
    _, c = _make_verified_user("applicant.c@demo-mail.com", full_name="Sara Malik")
    c.current_level = "entry"
    c.save()
    _add_education(c, "Computer Science", DEGREE_BACHELORS, "LUMS", 3, 0)
    _add_experience(c, "Junior Developer", "CodeHouse", ["Pyhton", "Djnago", "Git"], 1, 0)

    # D — Education phrasing: full degree name vs job's short form
    _, d = _make_verified_user("applicant.d@demo-mail.com", full_name="Hamza Tariq")
    d.current_level = "entry"
    d.save()
    _add_education(d, "Bachelor of Science in Computer Science", DEGREE_BACHELORS, "GIKI", 4, 0)
    _add_experience(d, "Software Intern", "DevWorks", ["Python", "Django", "Git"], 1, 0)

    # E — Experience title phrasing: "Software Developer" vs job's "Software Engineer"
    _, e = _make_verified_user("applicant.e@demo-mail.com", full_name="Zara Sheikh")
    e.current_level = "entry"
    e.save()
    _add_education(e, "Computer Science", DEGREE_BACHELORS, "NUST", 4, 0)
    _add_experience(e, "Software Developer", "PixelWorks", ["Python", "Django", "Git", "Docker"], 1, 0)

    # F — Distinct variant trap: "React Native" (mobile) vs job wanting "React" (web)
    _, f = _make_verified_user("applicant.f@demo-mail.com", full_name="Omar Farooq")
    f.current_level = "entry"
    f.save()
    _add_education(f, "Computer Science", DEGREE_BACHELORS, "COMSATS", 4, 0)
    _add_experience(f, "Mobile App Developer", "AppNest", ["React Native", "JavaScript"], 1, 0)

    # G — Related-but-different education: Computer Engineering vs job's Computer Science
    _, g = _make_verified_user("applicant.g@demo-mail.com", full_name="Fatima Noor")
    g.current_level = "entry"
    g.save()
    _add_education(g, "Computer Engineering", DEGREE_BACHELORS, "UET Taxila", 4, 0)
    _add_experience(g, "Software Engineer", "ByteForge", ["Python", "Django", "Git"], 1, 0)

    # H — Same title, unrelated skills: "Software Engineer" role but design-tool skills
    _, h = _make_verified_user("applicant.h@demo-mail.com", full_name="Usman Raza")
    h.current_level = "entry"
    h.save()
    _add_education(h, "Computer Science", DEGREE_BACHELORS, "PUCIT", 4, 0)
    _add_experience(h, "Software Engineer", "DesignLoft", ["Photoshop", "Illustrator"], 1, 0)

    # --- Data Analyst (job2) candidates -------------------------------

    # I — Clean, full match. Baseline for Data Analyst.
    _, i_ = _make_verified_user("applicant.i@demo-mail.com", full_name="Ali Raza")
    i_.current_level = "mid"
    i_.save()
    _add_education(i_, "BS Statistics", DEGREE_BACHELORS, "Punjab University", 6, 2)
    _add_experience(i_, "Data Analyst", "InsightWorks", ["SQL", "Excel", "Power BI", "Python"], 3, 0)

    # J — Alias/typo variants: "MS Excel" -> Excel, squished "PowerBI" -> Power BI
    _, j = _make_verified_user("applicant.j@demo-mail.com", full_name="Mahnoor Iqbal")
    j.current_level = "mid"
    j.save()
    _add_education(j, "Bachelors in Mathematics", DEGREE_BACHELORS, "Kinnaird College", 6, 2)
    _add_experience(j, "Data Analyst", "MetricLabs", ["MS Excel", "PowerBI", "SQL"], 3, 0)

    # K — Related-education trap: Economics vs job's required Statistics/Mathematics
    _, k = _make_verified_user("applicant.k@demo-mail.com", full_name="Rabia Saeed")
    k.current_level = "mid"
    k.save()
    _add_education(k, "Economics", DEGREE_BACHELORS, "LSE Lahore", 6, 2)
    _add_experience(k, "Data Analyst", "NumberCrunch", ["SQL", "Excel", "Power BI"], 3, 0)

    # --- Senior Backend Engineer (job3) candidates ---------------------

    # L — Clean, full match. Second strong senior candidate alongside B.
    _, l = _make_verified_user("applicant.l@demo-mail.com", full_name="Hassan Iqbal")
    l.current_level = "senior"
    l.save()
    _add_education(l, "Computer Science", DEGREE_BACHELORS, "LUMS", 9, 5)
    _add_experience(l, "Senior Backend Engineer", "ScaleSoft",
                     ["Python", "Django", "AWS", "PostgreSQL", "Redis"], 6, 0)

    # M — Alias ("Postgres" -> PostgreSQL) + acronym-expansion ("Amazon Web Services" -> AWS)
    _, m = _make_verified_user("applicant.m@demo-mail.com", full_name="Nida Aslam")
    m.current_level = "senior"
    m.save()
    _add_education(m, "BS Computer Science", DEGREE_BACHELORS, "FAST NUCES", 9, 5)
    _add_experience(m, "Backend Engineer", "CorePath",
                     ["Python", "Django", "Postgres", "Amazon Web Services"], 6, 0)

    # N — Level-penalty isolation: all the right skills, but mid-level applying to a senior job
    _, n = _make_verified_user("applicant.n@demo-mail.com", full_name="Kamran Sheikh")
    n.current_level = "mid"
    n.save()
    _add_education(n, "Computer Science", DEGREE_BACHELORS, "UET Lahore", 6, 2)
    _add_experience(n, "Backend Developer", "ServerSide", ["Python", "Django", "AWS", "PostgreSQL"], 3, 0)

    # O — Skill Compass demo: two degrees, three roles, deliberately missing
    # Django (required by both Software Engineer and Senior Backend Engineer)
    # and Power BI (required only by Data Analyst).
    _, o = _make_verified_user("applicant.o@demo-mail.com", full_name="Areeba Chaudhry")
    o.current_level = "senior"
    o.save()
    _add_education(o, "Computer Science", DEGREE_BACHELORS, "NUST", 9, 5)
    _add_education(o, "Statistics", DEGREE_BACHELORS, "Punjab University", 9, 5)
    _add_experience(o, "Software Engineer", "ByteForge", ["Python", "Git", "Docker"], 5, 3)
    _add_experience(o, "Data Analyst", "InsightWorks", ["SQL", "Excel"], 3, 1)
    _add_experience(o, "Backend Engineer", "CloudBase", ["Python", "AWS", "PostgreSQL", "Redis"], 1, 0)


def main():
    print("Seeding companies + jobs...")
    seed_jobs()

    print("Seeding applicants...")
    seed_applicants()

    print(f"Done. All demo users share the password: {DEMO_PASSWORD}")
    print("Reminder: job/profile vectors are not cached yet — see the "
          "docstring at the top of this file for how to trigger that.")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------
# OPTIONAL: uncomment to auto-trigger vector caching right after seeding
# (requires a Celery worker running and reachable, e.g.
#  celery -A config worker -l info --concurrency=4)
# ---------------------------------------------------------------------
#
from jobs.tasks import precompute_job_vector, cache_profile_vectors
#
def trigger_caching():
    for job in Job.objects.all():
        precompute_job_vector.delay(job.id)
    for ap in ApplicantProfile.objects.all():
        cache_profile_vectors.delay(ap.id)

if __name__ == "__main__":
    main()
    trigger_caching()