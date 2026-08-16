"""
recalculate_all_matches.py

One-off backfill script. Run this ONCE after adding the `matched_skill_names`
field to Compatibility, to refresh every existing match so the new field
gets populated (old rows will otherwise sit with matched_skill_names=[]
until whatever normally triggers a rematch happens for them).

This does NOT do the scoring itself in this process — it just queues the
same Celery tasks your app already uses (generate_matches_for_job), so the
actual work happens on your Celery worker(s), exactly like normal rematching.

Place this file next to manage.py and run:

    python recalculate_all_matches.py

Requirements:
- A Celery worker must be running and able to reach the broker (Redis/etc),
  otherwise the tasks will just sit queued and nothing will happen.
- The model (JobBERT-v3) must be available to the worker process, same as
  during normal operation.
"""

import os
import django

# CHANGE THIS to match the DJANGO_SETTINGS_MODULE value used in your manage.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from celery import group
from jobs.models import Job
from jobs.tasks import generate_matches_for_job


def main():
    # Only active jobs are considered here because generate_matches_for_job
    # itself only ever produces matches for active jobs with a cached title
    # vector — inactive jobs never had live Compatibility rows kept fresh
    # anyway, so there's nothing meaningful to backfill for them.
    job_ids = list(
        Job.objects.filter(is_active=True)
        .exclude(cached_title_vec=None)
        .values_list("id", flat=True)
    )

    if not job_ids:
        print("No active, vector-ready jobs found — nothing to queue.")
        return

    print(f"Queuing rematch for {len(job_ids)} active job(s)...")

    task_group = group(generate_matches_for_job.si(job_id) for job_id in job_ids)
    result = task_group.apply_async()

    print(f"Queued successfully. Group id: {result.id}")
    print("Rematching will run in the background on your Celery worker(s).")
    print("Watch your worker logs (or Flower, if you use it) to track progress.")
    print(
        "Note: only candidates with is_open_to_opportunities=True and a "
        "cached profile get rescored — that matches your normal matching "
        "behavior, so it won't touch anyone who wouldn't normally be matched."
    )


if __name__ == "__main__":
    main()