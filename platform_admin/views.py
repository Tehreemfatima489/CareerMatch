from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test

from users.models import ApplicantProfile, CompanyProfile
from django.db import transaction
from django.core.cache import cache
from django.utils import timezone
from celery import group

from jobs.models import (
    SkillMatchFeedback, SkillAliasOverride, SkillDistinctOverride,
    TitleMatchFeedback, TitleMatchOverride, MatchFlag, Job,
)
from jobs.services import (
    _light_normalise_skill_text, _normalise_field_text, _ordered_pair,
    jobs_using_skill_pair, jobs_using_title, jobs_using_edu_field, _approve_skill_feedback, _approve_title_feedback,
)
from jobs.tasks import generate_matches_for_job


def is_platform_admin(user):
    return user.is_authenticated and user.is_superuser


@user_passes_test(is_platform_admin, login_url="login")
def usage_stats(request):
    context = {
        
        "total_users": ApplicantProfile.objects.filter(user__is_superuser=False).count(),
        "total_companies": CompanyProfile.objects.count(),
        "total_jobs": Job.objects.count(),
    }
    return render(request, "platform_admin/usage_stats.html", context)


@user_passes_test(is_platform_admin, login_url="login")
def management(request):
    applicants = ApplicantProfile.objects.filter(
        user__is_superuser=False
    ).select_related("user").order_by("-id")

    companies = CompanyProfile.objects.select_related("user").order_by("-id")

    return render(request, "platform_admin/management.html", {
        "applicants": applicants,
        "companies": companies,
    })


import os  # Ensure os is imported at top of platform_admin/views.py


@user_passes_test(is_platform_admin, login_url="login")
def confirm_remove_user(request, user_id):
    applicant = get_object_or_404(ApplicantProfile, id=user_id)

    if request.method == "POST":
        # 1. Check and remove resume file from disk before deleting database record
        if applicant.resume and os.path.isfile(applicant.resume.path):
            os.remove(applicant.resume.path)

        # 2. Delete the user (which cascades to ApplicantProfile)
        applicant.user.delete()

        return redirect("admin_management")

    return render(
        request,
        "platform_admin/confirm_remove.html",
        {
            "target_type": "user",
            "target_name": applicant.full_name,
            "cancel_url": "admin_management",
        },
    )

@user_passes_test(is_platform_admin, login_url="login")
def confirm_remove_company(request, company_id):
    company = get_object_or_404(CompanyProfile, id=company_id)
    job_count = company.jobs.count()  # related_name="jobs" on Job.company

    if request.method == "POST":
        company.user.delete()
        return redirect("admin_management")

    return render(request, "platform_admin/confirm_remove.html", {
        "target_type": "company",
        "target_name": company.company_name,
        "job_count": job_count,
        "cancel_url": "admin_management",
    })



##########################feedback views


@user_passes_test(is_platform_admin, login_url="login")
def feedback_queue(request):
    return render(request, "platform_admin/feedback_queue.html", {
        "skill_pending": SkillMatchFeedback.objects.filter(status="pending").select_related("job", "applicant"),
        "title_pending": TitleMatchFeedback.objects.filter(status="pending").select_related("job", "applicant"),
        "open_flags": MatchFlag.objects.filter(status="open").select_related("compatibility__job", "applicant"),
    })


@user_passes_test(is_platform_admin, login_url="login")
@transaction.atomic
def resolve_skill_feedback(request, feedback_id):
    fb = get_object_or_404(SkillMatchFeedback, id=feedback_id, status="pending")
    decision = request.POST.get("decision")

    if decision == "approve":
        _approve_skill_feedback(fb, reviewed_by=request.user)
    else:
        fb.status = "rejected"
        fb.reviewed_by = request.user
        fb.reviewed_at = timezone.now()
        fb.save()

    return redirect("admin_feedback_queue")


@user_passes_test(is_platform_admin, login_url="login")
@transaction.atomic
def resolve_title_feedback(request, feedback_id):
    fb = get_object_or_404(TitleMatchFeedback, id=feedback_id, status="pending")
    decision = request.POST.get("decision")

    if decision == "approve":
        _approve_title_feedback(fb, reviewed_by=request.user)
    else:
        fb.status = "rejected"
        fb.reviewed_by = request.user
        fb.reviewed_at = timezone.now()
        fb.save()

    return redirect("admin_feedback_queue")


@user_passes_test(is_platform_admin, login_url="login")
def resolve_match_flag(request, flag_id):
    flag = get_object_or_404(MatchFlag, id=flag_id, status="open")
    if request.method == "POST":
        flag.status = "resolved"
        flag.resolved_at = timezone.now()
        flag.save()
        generate_matches_for_job.delay(flag.compatibility.job_id)
        return redirect("admin_feedback_queue")
    return render(request, "platform_admin/resolve_flag.html", {"flag": flag})