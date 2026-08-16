import os
import sys
import django
import logging
from datetime import date, timedelta

# -----------------------------------------------------------------
# 1. SETUP DJANGO ENVIRONMENT
# -----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import transaction
from django.contrib.auth import get_user_model
from users.models import ApplicantProfile, Skill, Education, Experience, CompanyProfile
from jobs.models import Job, JobSkill

User = get_user_model()
logger = logging.getLogger(__name__)


def run_seed():
    print("Starting LedgerPeak seeding...")

    with transaction.atomic():
        # -----------------------------------------------------------------
        # 2. CREATE COMPANY USER & PROFILE
        # -----------------------------------------------------------------
        company_user, _ = User.objects.get_or_create(
            email="company@ledgerpeak.test",
            defaults={"is_verified": True}
        )

        company_profile, created = CompanyProfile.objects.get_or_create(
            user=company_user,
            defaults={
                "company_name": "LedgerPeak",
            }
        )
        print(f"Company 'LedgerPeak' {'created' if created else 'found'}.")

        # -----------------------------------------------------------------
        # 3. CREATE JOBS & SKILLS
        # -----------------------------------------------------------------
        jobs_spec = [
            {
                "title": "Junior Accountant",
                "level": "entry",
                "education_required": "Accounting & Finance",
                "required_degree_level": "bachelor",
                "accept_related_education_fields": True,
                "required_skills": ["Bookkeeping", "Advanced Excel for Finance", "Financial Reporting"],
                "optional_skills": ["QuickBooks"],
                "experience_required": 1.0,
                "description": "Entry-level position responsible for bookkeeping, MS Excel reporting, and basic accounting tasks.",
                "location": "New York, NY",
            },
            {
                "title": "Financial Analyst",
                "level": "mid",
                "education_required": "Accounting & Finance",
                "required_degree_level": "bachelor",
                "accept_related_education_fields": True,
                "required_skills": ["Financial Modeling", "Advanced Excel for Finance", "Financial Reporting"],
                "optional_skills": ["Budgeting & Forecasting"],
                "experience_required": 3.0,
                "description": "Mid-level position focusing on financial modeling, forecasting, and data-driven reporting.",
                "location": "New York, NY",
            },
            {
                "title": "Finance Manager",
                "level": "senior",
                "education_required": "Accounting & Finance",
                "required_degree_level": "bachelor",
                "accept_related_education_fields": False,
                "required_skills": ["Financial Modeling", "Budgeting & Forecasting", "Financial Reporting", "Cost Accounting"],
                "optional_skills": ["QuickBooks"],
                "experience_required": 5.0,
                "description": "Senior position driving budget planning, variance analysis, financial modeling, and department oversight.",
                "location": "New York, NY",
            },
        ]

        created_jobs = {}
        for jspec in jobs_spec:
            job, _ = Job.objects.update_or_create(
                company=company_profile,
                title=jspec["title"],
                defaults={
                    "level": jspec["level"],
                    "education_required": jspec["education_required"],
                    "required_degree_level": jspec["required_degree_level"],
                    "accept_related_education_fields": jspec["accept_related_education_fields"],
                    "experience_required": jspec["experience_required"],
                    "description": jspec["description"],
                    "location": jspec["location"],
                }
            )

            # Clear existing job skills for idempotency
            JobSkill.objects.filter(job=job).delete()

            # Attach required skills
            for sk_name in jspec["required_skills"]:
                skill_obj, _ = Skill.objects.get_or_create(name=sk_name)
                JobSkill.objects.create(job=job, skill=skill_obj, is_optional=False)

            # Attach optional skills
            for sk_name in jspec["optional_skills"]:
                skill_obj, _ = Skill.objects.get_or_create(name=sk_name)
                JobSkill.objects.create(job=job, skill=skill_obj, is_optional=True)

            created_jobs[jspec["title"]] = job
            print(f"  -> Job '{job.title}' ready.")

        # -----------------------------------------------------------------
        # 4. CREATE CANDIDATES (P through AA)
        # -----------------------------------------------------------------
        candidates_spec = [
            {
                "code": "P",
                "email": "candidate.p@ledgerpeak.test",
                "name": "Candidate P (Skill Alias)",
                "degree": "ACCA",
                "degree_level": "bachelor",
                "skills": ["Book Keeping", "MS Excel", "Financial Statement Drafting"],
                "experiences": [{"role": "Junior Accountant", "years": 1}],
            },
            {
                "code": "Q",
                "email": "candidate.q@ledgerpeak.test",
                "name": "Candidate Q (Acronym Match)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["Bookkeeping", "Advanced Excel for Finance", "FR"],
                "experiences": [{"role": "Junior Accountant", "years": 1}],
            },
            {
                "code": "R",
                "email": "candidate.r@ledgerpeak.test",
                "name": "Candidate R (Typo Match)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["Bookeeping", "Advanced Excel for Finance", "Finanical Reporting"],
                "experiences": [{"role": "Junior Accountant", "years": 1}],
            },
            {
                "code": "S",
                "email": "candidate.s@ledgerpeak.test",
                "name": "Candidate S (Education Phrase Alias)",
                "degree": "BS Accounting and Finance",
                "degree_level": "bachelor",
                "skills": ["Bookkeeping", "Advanced Excel for Finance", "Financial Reporting"],
                "experiences": [{"role": "Junior Accountant", "years": 1}],
            },
            {
                "code": "T",
                "email": "candidate.t@ledgerpeak.test",
                "name": "Candidate T (Role Title Phrasing)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["Bookkeeping", "Advanced Excel for Finance", "Financial Reporting"],
                "experiences": [{"role": "Accounts Officer", "years": 1}],
            },
            {
                "code": "U",
                "email": "candidate.u@ledgerpeak.test",
                "name": "Candidate U (Distinct Variant Trap)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["Bookkeeping", "Advanced Excel for Finance", "Financial Reporting", "Sage 50"],
                "experiences": [{"role": "Junior Accountant", "years": 1}],
            },
            {
                "code": "V",
                "email": "candidate.v@ledgerpeak.test",
                "name": "Candidate V (Related Education)",
                "degree": "BS Economics",
                "degree_level": "bachelor",
                "skills": ["Bookkeeping", "Advanced Excel for Finance", "Financial Reporting"],
                "experiences": [{"role": "Junior Accountant", "years": 1}],
            },
            {
                "code": "W",
                "email": "candidate.w@ledgerpeak.test",
                "name": "Candidate W (Mid Baseline)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["Financial Modeling", "Advanced Excel for Finance", "Financial Reporting", "Budgeting & Forecasting"],
                "experiences": [{"role": "Financial Analyst", "years": 3}],
            },
            {
                "code": "X",
                "email": "candidate.x@ledgerpeak.test",
                "name": "Candidate X (Mid Alias Combo)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["DCF Modeling", "Excel Financial Analysis", "Financial Reporting"],
                "experiences": [{"role": "Financial Analyst", "years": 3}],
            },
            {
                "code": "Y",
                "email": "candidate.y@ledgerpeak.test",
                "name": "Candidate Y (Senior Baseline)",
                "degree": "ACCA",
                "degree_level": "bachelor",
                "skills": ["Financial Modeling", "Budgeting & Forecasting", "Financial Reporting", "Cost Accounting", "QuickBooks"],
                "experiences": [{"role": "Finance Manager", "years": 6}],
            },
            {
                "code": "Z",
                "email": "candidate.z@ledgerpeak.test",
                "name": "Candidate Z (Level Mismatch)",
                "degree": "ACCA",
                "degree_level": "bachelor",
                "skills": ["Financial Modeling", "Budgeting & Forecasting", "Financial Reporting", "Cost Accounting", "QuickBooks"],
                "experiences": [{"role": "Financial Analyst", "years": 2}],
            },
            {
                "code": "AA",
                "email": "candidate.aa@ledgerpeak.test",
                "name": "Candidate AA (Compass Demo)",
                "degree": "BS Accounting & Finance",
                "degree_level": "bachelor",
                "skills": ["Bookkeeping", "Advanced Excel for Finance", "Financial Reporting"],
                "experiences": [
                    {"role": "Accounts Officer", "years": 1},
                    {"role": "Financial Analyst", "years": 2},
                ],
            },
        ]

        today = date.today()

        for cspec in candidates_spec:
            user, u_created = User.objects.get_or_create(
                email=cspec["email"]
            )
            if u_created:
                user.set_password("TestPass123!")
                user.is_verified = True
                user.save()

            applicant_profile, _ = ApplicantProfile.objects.get_or_create(
                user=user,
                defaults={"full_name": cspec["name"]}
            )

            Education.objects.filter(applicant=applicant_profile).delete()
            Experience.objects.filter(applicant=applicant_profile).delete()
            applicant_profile.skills.clear()

            Education.objects.create(
                applicant=applicant_profile,
                degree=cspec["degree"],
                degree_level=cspec["degree_level"],
                institution="Test University",
                start_date=today - timedelta(days=365 * 4),
                end_date=today
            )

            for exp in cspec["experiences"]:
                yrs = exp["years"]
                start_dt = today - timedelta(days=int(yrs * 365.25))
                Experience.objects.create(
                    applicant=applicant_profile,
                    role=exp["role"],
                    company="LedgerPeak Test Corp",
                    start_date=start_dt,
                    end_date=today
                )

            for sk_name in cspec["skills"]:
                skill_obj, _ = Skill.objects.get_or_create(name=sk_name)
                applicant_profile.skills.add(skill_obj)

            print(f"  -> Candidate {cspec['code']} ({cspec['name']}) created/updated.")

    print("\nSUCCESS: Seeding complete for LedgerPeak company, jobs, and candidates.")


if __name__ == "__main__":
    run_seed()