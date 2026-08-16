from django.contrib.auth import authenticate, login, logout, update_session_auth_hash, get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from jobs.models import Compatibility, InterviewInvite, MatchFlag
from collections import Counter
from users.utils import get_or_create_skill
from django.core.mail import send_mail
from django.utils import timezone
from .models import OTPVerification
from datetime import date
from urllib.parse import unquote

from .models import ApplicantProfile, CompanyProfile, Education, Experience, Skill
from constants import DEGREE_LEVEL_MODEL_CHOICES

User = get_user_model()


# =========================================
# AUTH  (messages.* KEPT — these render on auth/*.html pages)
# =========================================
def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect("admin_dashboard")
        if hasattr(request.user, "companyprofile"):
            return redirect("post_job")
        return redirect("dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, "Invalid credentials")
            return render(request, "auth/login.html")

        user = authenticate(request, username=user_obj.email, password=password)

        if user:
            if not user.is_verified and not user.is_superuser:
               request.session["pending_verification_email"] = user.email
               messages.error(request, "Please verify your email before logging in.")
               return redirect("verify_otp")

            login(request, user)
            if user.is_superuser:
                return redirect("admin_dashboard")
            if hasattr(user, "companyprofile"):
                return redirect("post_job")
            return redirect("dashboard")

        messages.error(request, "Invalid credentials")
        return render(request, "auth/login.html")

    return render(request, "auth/login.html")



# =========================================
# REGISTER APPLICANT  (auth flow — messages kept)
# =========================================
def register_applicant(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        full_name = request.POST.get("full_name", "").strip()

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return render(request, "auth/register.html")

        user = User.objects.create_user(email=email, password=password)
        ApplicantProfile.objects.get_or_create(
            user=user,
            defaults={"full_name": full_name}
        )

        _send_otp(user)
        request.session["pending_verification_email"] = email
        return redirect("verify_otp")

    return render(request, "auth/register.html")
# =========================================
# REGISTER Company  (auth flow — messages kept)
# =========================================

def register_company(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        company_name = request.POST.get("company_name", "").strip()

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return render(request, "auth/register_company.html")

        user = User.objects.create_user(email=email, password=password)
        CompanyProfile.objects.create(user=user, company_name=company_name)

        _send_otp(user)
        request.session["pending_verification_email"] = email
        return redirect("verify_otp")

    return render(request, "auth/register_company.html")

# OTP

def _send_otp(user):
    code = OTPVerification.generate_code()
    OTPVerification.objects.update_or_create(
        user=user,
        defaults={"code": code}
    )
    send_mail(
        subject="Your CareerMatch verification code",
        message=f"Your verification code is: {code}\nThis code expires in 10 minutes.",
        from_email=None,
        recipient_list=[user.email],
    )


def verify_otp(request):
    email = request.session.get("pending_verification_email")
    if not email:
        return redirect("login")

    if request.method == "POST":
        code = request.POST.get("otp_code", "").strip()

        try:
            user = User.objects.get(email=email)
            otp = user.otp
        except (User.DoesNotExist, OTPVerification.DoesNotExist):
            messages.error(request, "Verification session expired. Please register again.")
            return redirect("register_applicant")

        if otp.is_expired():
            messages.error(request, "Code expired. Please request a new one.")
            return render(request, "auth/verify_otp.html", {"email": email})

        if otp.code != code:
            messages.error(request, "Incorrect code. Please try again.")
            return render(request, "auth/verify_otp.html", {"email": email})

        user.is_verified = True
        user.save()
        otp.delete()
        del request.session["pending_verification_email"]

        messages.success(request, "Email verified successfully. You can now log in.")
        return redirect("login")

    return render(request, "auth/verify_otp.html", {"email": email})


def resend_otp(request):
    email = request.session.get("pending_verification_email")
    if not email:
        return redirect("login")

    try:
        user = User.objects.get(email=email)
        _send_otp(user)
        messages.success(request, "A new code has been sent to your email.")
    except User.DoesNotExist:
        messages.error(request, "Something went wrong. Please register again.")
        return redirect("register_applicant")

    return redirect("verify_otp")



## FORGOT  PASSWORD  (auth flow — messages kept)

def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, "No account found with that email.")
            return render(request, "auth/forgot_password.html")

        _send_otp(user)
        request.session["pending_reset_email"] = email
        return redirect("reset_password")

    return render(request, "auth/forgot_password.html")


def reset_password(request):
    email = request.session.get("pending_reset_email")
    if not email:
        return redirect("forgot_password")

    if request.method == "POST":
        code = request.POST.get("otp_code", "").strip()
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        try:
            user = User.objects.get(email=email)
            otp = user.otp
        except (User.DoesNotExist, OTPVerification.DoesNotExist):
            messages.error(request, "Reset session expired. Please try again.")
            return redirect("forgot_password")

        if otp.is_expired():
            messages.error(request, "Code expired. Please request a new one.")
            return render(request, "auth/reset_password.html", {"email": email})

        if otp.code != code:
            messages.error(request, "Incorrect code.")
            return render(request, "auth/reset_password.html", {"email": email})

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "auth/reset_password.html", {"email": email})

        user.set_password(new_password)
        user.save()
        otp.delete()
        del request.session["pending_reset_email"]

        messages.success(request, "Password reset successfully. Please log in.")
        return redirect("login")

    return render(request, "auth/reset_password.html", {"email": email})

# =========================================
# LOGOUT
# =========================================
def logout_view(request):
    logout(request)
    return redirect("login")


# =========================================
# PROFILE (DISPLAY ONLY)
# =========================================
@login_required
def profile(request):
    if not hasattr(request.user, "applicantprofile"):
        return redirect("post_job")

    applicant = request.user.applicantprofile

    total = 4
    done = 0
    if applicant.full_name: done += 1
    if applicant.skills.exists(): done += 1
    if applicant.educations.exists(): done += 1
    if applicant.experiences.exists(): done += 1

    completion_percent = int((done / total) * 100)

    return render(request, "user/profile.html", {
        "applicant": applicant,
        "educations": applicant.educations.all().order_by("-start_date"),
        "experiences": applicant.experiences.prefetch_related("skills_used").all().order_by("-start_date"),
        "skills": applicant.skills.all(),
        "completion_percent": completion_percent,
        "degree_level_choices": DEGREE_LEVEL_MODEL_CHOICES,
    })


# =========================================
# UPDATE BASIC INFO ONLY
# =========================================
@login_required
def update_personal_info(request):
    if request.method != "POST":
        return redirect("profile")

    applicant = request.user.applicantprofile

    applicant.full_name = request.POST.get("full_name", applicant.full_name).strip()
    applicant.current_level = request.POST.get("current_level", applicant.current_level)

    if "resume" in request.FILES:
        resume_file = request.FILES["resume"]
        if not resume_file.name.lower().endswith(".pdf"):
            return redirect("profile")
        applicant.resume = resume_file

    applicant.save()

    return redirect("profile")


# =========================================
# EDUCATION - ADD
# =========================================
@login_required
def add_education(request):
    if request.method != "POST":
        return redirect("profile")

    applicant = request.user.applicantprofile
    degree_level = request.POST.get("degree_level", "").strip()
    degree = request.POST.get("degree", "").strip()

    if not degree_level:
        return redirect("profile")

    if not degree:
        return redirect("profile")

    Education.objects.create(
        applicant=applicant,
        degree=degree,
        degree_level=degree_level,
        institution=request.POST.get("institution", "").strip(),
        start_date=request.POST.get("start_date"),
        end_date=request.POST.get("end_date") or None
    )

    return redirect("profile")

# =========================================
# EDUCATION - DELETE
# =========================================
@login_required
def delete_education(request, edu_id):
    edu = get_object_or_404(Education, id=edu_id, applicant=request.user.applicantprofile)
    edu.delete()
    return redirect("profile")



def _orphaned_skills(applicant, excluded_experience, skill_ids):
    """
    Removes skills from the applicant's overall skill list only if they
    are no longer referenced by ANY experience (other than the one just
    edited/deleted). Skills added manually via the Skills section, or
    still used by another experience, are left untouched.
    """
    if not skill_ids:
        return

    still_used_ids = set(
        Skill.objects.filter(
            used_in_experiences__applicant=applicant,
            id__in=skill_ids,
        )
        .exclude(used_in_experiences=excluded_experience)
        .values_list("id", flat=True)
    )

    orphaned_ids = skill_ids - still_used_ids
    if orphaned_ids:
        applicant.skills.remove(*orphaned_ids)


# =========================================
# EXPERIENCE - ADD
# =========================================
@login_required
def add_experience(request):
    if request.method != "POST":
        return redirect("profile")

    applicant = request.user.applicantprofile
    role = request.POST.get("role", "").strip()
    skill_names = [s.strip() for s in request.POST.get("skills_used", "").split(",") if s.strip()]

    if not role:
        return redirect("profile")

    if not skill_names:
        return redirect("profile")

    experience = Experience.objects.create(
        applicant=applicant,
        role=role,
        company=request.POST.get("company", "").strip(),
        start_date=request.POST.get("start_date"),
        end_date=request.POST.get("end_date") or None,
        is_current=request.POST.get("is_current") == "on"
    )

    skills = [get_or_create_skill(name) for name in skill_names]
    experience.skills_used.set(skills)
    applicant.skills.add(*skills)

    return redirect("profile")


# =========================================
# EXPERIENCE - DELETE
# =========================================
@login_required
def delete_experience(request, exp_id):
    applicant = request.user.applicantprofile
    exp = get_object_or_404(Experience, id=exp_id, applicant=applicant)

    skill_ids = set(exp.skills_used.values_list("id", flat=True))
    exp.delete()
    _orphaned_skills(applicant, exp, skill_ids)

    return redirect("profile")

# =========================================
# EDUCATION - EDIT
# =========================================
@login_required
def edit_education(request, edu_id):
    edu = get_object_or_404(Education, id=edu_id, applicant=request.user.applicantprofile)

    if request.method == "POST":
        degree = request.POST.get("degree", "").strip()
        degree_level = request.POST.get("degree_level", "").strip()

        if not degree_level:
            return redirect("edit_education", edu_id=edu.id)

        if not degree:
            return redirect("edit_education", edu_id=edu.id)

        edu.degree = degree
        edu.degree_level = degree_level
        edu.institution = request.POST.get("institution", "").strip()
        edu.start_date = request.POST.get("start_date")
        edu.end_date = request.POST.get("end_date") or None
        edu.save()

        return redirect("profile")

    return render(request, "user/edit_education.html", {
        "education": edu,
        "degree_level_choices": DEGREE_LEVEL_MODEL_CHOICES,
    })

# =========================================
# EXPERIENCE - EDIT
# =========================================
@login_required
def edit_experience(request, exp_id):
    exp = get_object_or_404(Experience, id=exp_id, applicant=request.user.applicantprofile)

    if request.method == "POST":
        role = request.POST.get("role", "").strip()
        skill_names = [s.strip() for s in request.POST.get("skills_used", "").split(",") if s.strip()]

        if not role:
            return redirect("edit_experience", exp_id=exp.id)

        if not skill_names:
            return redirect("edit_experience", exp_id=exp.id)

        old_skill_ids = set(exp.skills_used.values_list("id", flat=True))

        exp.role = role
        exp.company = request.POST.get("company", "").strip()
        exp.start_date = request.POST.get("start_date")
        exp.end_date = request.POST.get("end_date") or None
        exp.is_current = request.POST.get("is_current") == "on"
        exp.save()

        skills = [get_or_create_skill(name) for name in skill_names]
        new_skill_ids = {s.id for s in skills}
        exp.skills_used.set(skills)
        request.user.applicantprofile.skills.add(*skills)

        removed_ids = old_skill_ids - new_skill_ids
        _orphaned_skills(request.user.applicantprofile, exp, removed_ids)

        return redirect("profile")

    existing_skills = ", ".join(exp.skills_used.values_list("name", flat=True))
    return render(request, "user/edit_experience.html", {
        "experience": exp,
        "existing_skills": existing_skills,
    })


# =========================================
# SKILL - ADD
# =========================================
@login_required
def add_skill(request):
    if request.method != "POST":
        return redirect("profile")

    name = request.POST.get("skill_name", "").strip()
    if not name:
        return redirect("profile")

    try:
        skill = get_or_create_skill(name)
        request.user.applicantprofile.skills.add(skill)
    except ValueError:
        pass

    return redirect("profile")


# =========================================
# SKILL - REMOVE
# =========================================
@login_required
def remove_skill(request, skill_id):
    skill = get_object_or_404(Skill, id=skill_id)
    request.user.applicantprofile.skills.remove(skill)
    return redirect("profile")


# =========================================
# PASSWORD CHANGE
# =========================================
@login_required
def change_password(request):
    if request.method != "POST":
        return redirect("profile")

    user = request.user

    if not user.check_password(request.POST.get("current_password")):
        return redirect("profile")

    new = request.POST.get("new_password")
    confirm = request.POST.get("confirm_password")

    if new != confirm:
        return redirect("profile")

    user.set_password(new)
    user.save()
    update_session_auth_hash(request, user)

    return redirect("profile")


# =========================================
# DELETE ACCOUNT
# =========================================
@login_required
def delete_account(request):
    user = request.user

    logout(request)
    user.delete()
    return redirect("login")

# =========================================
# TOGGLE  OPPORTUNITIES
# =========================================

@login_required
def toggle_opportunities(request):
    if request.method != "POST":
        return redirect("profile")

    applicant = request.user.applicantprofile
    applicant.is_open_to_opportunities = not applicant.is_open_to_opportunities
    applicant.save()

    return redirect("profile")


# =========================================
# DASHBOARD
# =========================================
@login_required
def dashboard(request):
    if not hasattr(request.user, "applicantprofile"):
        return redirect("manage_jobs")

    profile = request.user.applicantprofile

    matches = Compatibility.objects.filter(
        user=profile
    ).select_related("job", "job__company").order_by("-score")

    recent_invites = InterviewInvite.objects.filter(
        applicant=profile
    ).select_related("job", "job__company").order_by("-sent_at")[:3]

    invited_jobs = set(
        InterviewInvite.objects.filter(applicant=profile)
        .values_list("job_id", flat=True)
    )

    return render(request, "user/dashboard.html", {
        "matches": matches,
        "recent_invites": recent_invites,
        "invited_jobs": invited_jobs
    })


# =========================================
# JOB MATCH DETAIL
# =========================================


def _score_color(score):
    if score >= 70:
        return "green"
    if score >= 50:
        return "amber"
    return "red"


@login_required
def job_match_detail(request, compatibility_id):
    if not hasattr(request.user, "applicantprofile"):
        return redirect("dashboard")

    profile = request.user.applicantprofile
    match   = get_object_or_404(Compatibility, id=compatibility_id, user=profile)
    job     = match.job

    weights = {
        "entry":  {"skills": 0.60, "education": 0.30, "experience": 0.10},
        "mid":    {"skills": 0.50, "education": 0.20, "experience": 0.30},
        "senior": {"skills": 0.40, "education": 0.10, "experience": 0.50},
    }
    w = weights.get(job.level, weights["entry"])

    # ── Skills ──────────────────────────────────────────────────────────
    user_skills     = list(profile.skills.values_list("name", flat=True))
    required_skills = job.required_skill_names
    optional_skills = job.optional_skill_names
    missing_set     = set(match.missing_skills or [])
    job_skill_set   = set(required_skills + optional_skills)

    skill_data = {
        "score":            round(match.skill_score, 1),
        "color":            _score_color(match.skill_score),
        "explanation":      _skill_explanation(match.skill_score),
        "matched_required": [s for s in required_skills if s not in missing_set],
        "missing_required": list(match.missing_skills or []),
        "matched_optional": [s for s in optional_skills if s in user_skills],
        "missing_optional": [s for s in optional_skills if s not in user_skills],
        "bonus_skills":     [s for s in user_skills if s not in job_skill_set],
    }

    # ── Education ───────────────────────────────────────────────────────
    matched_edu_id = match.matched_education_id
    if matched_edu_id:
        matched_edu_qs = profile.educations.filter(id=matched_edu_id)
    else:
        matched_edu_qs = profile.educations.none()

    user_educations = []
    for edu in matched_edu_qs:
        end   = edu.end_date or date.today()
        years = round((end - edu.start_date).days / 365.25, 1)
        user_educations.append({
            "degree":         edu.degree,
            "degree_level":   edu.get_degree_level_display(),
            "institution":    edu.institution,
            "start_date":     edu.start_date,
            "end_date":       edu.end_date,
            "is_ongoing":     edu.end_date is None,
            "duration_years": years,
        })

    education_data = {
        "score":               round(match.education_score, 1),
        "color":               _score_color(match.education_score),
        "explanation":         _education_explanation(match.education_score),
        "job_requirement":     job.education_required,
        "required_degree_level": job.get_required_degree_level_display() if job.required_degree_level else None,
        "user_educations":     user_educations,
    }

    # ── Experience ──────────────────────────────────────────────────────
    relevant_exp_ids = set(match.relevant_experience_ids or [])
    if relevant_exp_ids:
        relevant_exp_qs = profile.experiences.filter(id__in=relevant_exp_ids).order_by("-start_date")
    else:
        relevant_exp_qs = profile.experiences.none()

    user_experiences       = []
    total_experience_years = 0.0
    for exp in relevant_exp_qs:
        end   = date.today() if (exp.is_current or not exp.end_date) else exp.end_date
        years = round(max((end - exp.start_date).days / 365.25, 0), 1)
        user_experiences.append({
            "role":       exp.role,
            "company":    exp.company,
            "start_date": exp.start_date,
            "end_date":   exp.end_date,
            "is_ongoing": exp.is_current or not exp.end_date,
            "years":      years,
        })
        total_experience_years += years

    total_experience_years = round(total_experience_years, 1)

    experience_data = {
        "score":               round(match.experience_score, 1),
        "color":               _score_color(match.experience_score),
        "explanation":         _experience_explanation(match.experience_score, job.experience_required),
        "user_experiences":    user_experiences,
        "total_years":         total_experience_years,
        "required_years":      job.experience_required,
        "years_gap":           round(max(job.experience_required - total_experience_years, 0), 1),
        "exceeds_requirement": match.exceeds_experience,
    }

    is_invited = InterviewInvite.objects.filter(job=job, applicant=profile).exists()
    is_flagged = MatchFlag.objects.filter(compatibility=match, status="open").exists()

    return render(request, "user/job_match_detail.html", {
        "match":      match,
        "job":        job,
        "skill":      skill_data,
        "education":  education_data,
        "experience": experience_data,
        "is_invited": is_invited,
        "overall_color": _score_color(match.score),
        "is_flagged": is_flagged,
    })


def _skill_explanation(score):
    if score >= 80:
        return "You have most of the required skills for this role — a strong match."
    if score >= 55:
        return "You match the core skills. A few gaps remain — adding them would noticeably strengthen your profile."
    if score >= 30:
        return "You have some relevant skills, but several key ones are missing."
    return "There are significant skill gaps for this role. Consider building the missing ones before applying."


def _education_explanation(score):
    if score >= 85:
        return "Your educational background aligns very well with what this role requires."
    if score >= 60:
        return "Your degree is in a related but different field. It still contributes positively to your score."
    if score >= 35:
        return "Your education is somewhat relevant, though not a close match to the job's requirement."
    return "Your current education may not meet this role's requirements. Relevant certifications could help."


def _experience_explanation(score, required_years):
    if required_years == 0:
        return "This role is open to fresh graduates — no prior experience is needed."
    if score >= 80:
        return f"Your experience covers the {required_years} year(s) this role requires, and the work you have done is relevant."
    if score >= 50:
        return f"Your total experience is slightly below what this role expects. The work you have is relevant, which keeps the score healthy."
    if score > 0:
        return f"You have some experience, but this role expects {required_years} year(s) of work in a relevant area."
    return f"No relevant experience was found on your profile. This role requires {required_years} year(s)."
# =========================================
# MY INVITES
# =========================================
@login_required
def my_invites(request):
    profile = request.user.applicantprofile

    invites = InterviewInvite.objects.filter(
        applicant=profile
    ).select_related("job", "job__company").order_by("-sent_at")

    # Build a map: invite.id → compatibility.id, so the template can link to job_match_detail
    compatibility_map = {}
    for invite in invites:
        match = Compatibility.objects.filter(job=invite.job, user=profile).first()
        if match:
            compatibility_map[invite.id] = match.id

    return render(request, "user/my_invites.html", {
        "invites": invites,
        "compatibility_map": compatibility_map,
    })


# =========================================
# RESPOND TO INVITE
# =========================================
@login_required
def respond_to_invite(request, invite_id):
    if request.method != "POST":
        return redirect("my_invites")

    profile = request.user.applicantprofile

    invite = get_object_or_404(
        InterviewInvite,
        id=invite_id,
        applicant=profile
    )

    if invite.status != "pending":
        return redirect("my_invites")

    action = request.POST.get("action")

    if action == "accepted":
        candidate_response = request.POST.get("candidate_response", "").strip()

        if not candidate_response:
            return redirect("my_invites")

        from django.utils import timezone
        invite.status             = "accepted"
        invite.candidate_response = candidate_response
        invite.responded_at       = timezone.now()
        invite.save()

    elif action == "declined":
        from django.utils import timezone
        invite.status       = "declined"
        invite.responded_at = timezone.now()
        invite.save()

    else:
        pass

    return redirect("my_invites")


# =========================================
# SKILL COMPASS
# =========================================


@login_required
def skill_compass(request):
    profile = request.user.applicantprofile

    matches = Compatibility.objects.filter(
        user=profile,
        score__gte=50
    ).select_related("job")

    total_jobs = matches.count()

    if total_jobs == 0:
        return render(request, "user/skill_compass.html", {
            "top_priority": None,
            "next_in_line": [],
            "total_jobs": 0
        })

    missing = []
    for m in matches:
        missing.extend(m.missing_skills or [])

    skill_counts = Counter(missing).most_common()

    compass_data = []
    for skill, count in skill_counts:
        impact_percent = round((count / total_jobs) * 100, 1)

        if impact_percent >= 70:
            priority = "High Priority"
            reason = "This skill unlocks most of your matched jobs"
        elif impact_percent >= 40:
            priority = "Medium Priority"
            reason = "This skill unlocks a significant number of jobs"
        else:
            priority = "Low Priority"
            reason = "Nice to have for better matching"

        compass_data.append({
            "skill": skill,
            "jobs_affected": count,
            "impact_percent": impact_percent,
            "priority": priority,
            "reason": reason
        })

    compass_data = sorted(compass_data, key=lambda x: x["impact_percent"], reverse=True)

    top_priority = compass_data[0] if compass_data else None
    next_in_line = compass_data[1:] if len(compass_data) > 1 else []

    return render(request, "user/skill_compass.html", {
        "top_priority": top_priority,
        "next_in_line": next_in_line,
        "total_jobs": total_jobs
    })


# =========================================
# MARK SKILL AS COMPLETED (adds to profile + removes from compass)
# =========================================


@login_required
def mark_skill_complete(request, skill_name):
    if request.method != "POST":
        return redirect("skill_compass")

    profile = request.user.applicantprofile
    clean_skill_name = unquote(skill_name)  # Decodes %20, %2B, etc.
    skill = get_or_create_skill(clean_skill_name)
    profile.skills.add(skill)

    return redirect("skill_compass")




###################flag job


@login_required
def flag_match(request, compatibility_id):
    if request.method != "POST":
        return redirect("job_match_detail", compatibility_id=compatibility_id)

    profile = request.user.applicantprofile
    match = get_object_or_404(Compatibility, id=compatibility_id, user=profile)

    MatchFlag.objects.create(
        compatibility=match,
        applicant=profile,
        note=request.POST.get("note", "").strip(),
    )

    return redirect("job_match_detail", compatibility_id=compatibility_id)