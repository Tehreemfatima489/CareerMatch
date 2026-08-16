from django.db.models.signals import m2m_changed, post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from celery import chain

from users.models import ApplicantProfile, Experience, Education
from jobs.models import Job


def _queue_profile_rematch(applicant_id):
    def _dispatch():
        from jobs.tasks import cache_profile_vectors, generate_matches_for_student
        chain(
            cache_profile_vectors.si(applicant_id),
            generate_matches_for_student.si(applicant_id),
        ).delay()

    transaction.on_commit(_dispatch)


# -------------------------------------------------------
# STUDENT-SIDE SIGNALS
# -------------------------------------------------------

@receiver(m2m_changed, sender=ApplicantProfile.skills.through)
def skills_changed(sender, instance, action, **kwargs):
    if action in ("post_add", "post_remove"):
        _queue_profile_rematch(instance.id)


@receiver(post_save, sender=Experience)
def experience_saved(sender, instance, **kwargs):
    _queue_profile_rematch(instance.applicant.id)


@receiver(post_save, sender=Education)
def education_saved(sender, instance, **kwargs):
    _queue_profile_rematch(instance.applicant.id)


@receiver(post_delete, sender=Experience)
def experience_deleted(sender, instance, **kwargs):
    _queue_profile_rematch(instance.applicant_id)


@receiver(post_delete, sender=Education)
def education_deleted(sender, instance, **kwargs):
    _queue_profile_rematch(instance.applicant_id)


@receiver(post_save, sender=ApplicantProfile)
def profile_saved(sender, instance, created, **kwargs):
    if not created:
        _queue_profile_rematch(instance.id)