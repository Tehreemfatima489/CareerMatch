from django.urls import path
from . import views

urlpatterns = [

    path("post-job/", views.post_job, name="post_job"),

    path("manage-jobs/", views.manage_jobs, name="manage_jobs"),

    path("job/<int:job_id>/applicants/", views.view_applicants, name="view_applicants"),
    path("job/<int:job_id>/edit/", views.edit_job, name="edit_job"),
    path("job/<int:job_id>/delete/", views.delete_job, name="delete_job"),
     path(
        "job/<int:job_id>/candidate/<int:applicant_id>/breakdown/",
        views.candidate_breakdown,
        name="candidate_breakdown"
    ),

    path("resume/<int:applicant_id>/download/", views.download_resume, name="download_resume"),
    path("invitations/sent/", views.sent_invitations, name="sent_invitations"),


    path(
        "job/<int:job_id>/invite/<int:applicant_id>/",
        views.send_invite,
        name="send_invite"
    ),

    # Company-side feedback submission
    path(
        "job/<int:job_id>/candidate/<int:applicant_id>/feedback/skill/",
        views.submit_skill_feedback,
        name="submit_skill_feedback"
    ),
    path(
        "job/<int:job_id>/candidate/<int:applicant_id>/feedback/title/",
        views.submit_title_feedback,
        name="submit_title_feedback"
    ),
]