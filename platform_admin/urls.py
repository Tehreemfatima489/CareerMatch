from django.urls import path
from . import views

urlpatterns = [
    path("admin-dashboard/", views.usage_stats, name="admin_dashboard"),
    path("admin-dashboard/management/", views.management, name="admin_management"),
    path("admin-dashboard/management/user/<int:user_id>/remove/", views.confirm_remove_user, name="admin_remove_user"),
    path("admin-dashboard/management/company/<int:company_id>/remove/", views.confirm_remove_company, name="admin_remove_company"),

    # Feedback moderation
    path("admin-dashboard/feedback/", views.feedback_queue, name="admin_feedback_queue"),
    path("admin-dashboard/feedback/skill/<int:feedback_id>/resolve/", views.resolve_skill_feedback, name="resolve_skill_feedback"),
    path("admin-dashboard/feedback/title/<int:feedback_id>/resolve/", views.resolve_title_feedback, name="resolve_title_feedback"),
    path("admin-dashboard/feedback/flag/<int:flag_id>/resolve/", views.resolve_match_flag, name="resolve_match_flag"),
]