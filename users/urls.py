from django.urls import path
from . import views

urlpatterns = [

    path("login/", views.login_view, name="login"),
    path("register/", views.register_applicant, name="register_applicant"),
    path("register-company/", views.register_company, name="register_company"),
    path("logout/", views.logout_view, name="logout"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("skill-compass/", views.skill_compass, name="skill_compass"),
    path("my-invites/", views.my_invites, name="my_invites"),
    path("job/<int:compatibility_id>/detail/", views.job_match_detail, name="job_match_detail"),

    path("profile/update/", views.update_personal_info, name="update_personal_info"),

    path("education/add/", views.add_education, name="add_education"),
    path("education/delete/<int:edu_id>/", views.delete_education, name="delete_education"),

    path("experience/add/", views.add_experience, name="add_experience"),
    path("experience/delete/<int:exp_id>/", views.delete_experience, name="delete_experience"),

    path("education/edit/<int:edu_id>/", views.edit_education, name="edit_education"),
    path("experience/edit/<int:exp_id>/", views.edit_experience, name="edit_experience"),

  
    path("skill/add/", views.add_skill, name="add_skill"),
    path("skill/remove/<int:skill_id>/", views.remove_skill, name="remove_skill"),
    path("invite/respond/<int:invite_id>/", views.respond_to_invite, name="respond_to_invite"),

    path("password/change/", views.change_password, name="change_password"),
    path("account/delete/", views.delete_account, name="delete_account"),

    path("verify-otp/", views.verify_otp, name="verify_otp"),
    path("resend-otp/", views.resend_otp, name="resend_otp"),
    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("reset-password/", views.reset_password, name="reset_password"),
    path("skill-compass/mark-complete/<str:skill_name>/", views.mark_skill_complete, name="mark_skill_complete"),
    path("profile/toggle-opportunities/", views.toggle_opportunities, name="toggle_opportunities"),

    # Candidate-side match flag
    path("match/<int:compatibility_id>/flag/", views.flag_match, name="flag_match"),
]