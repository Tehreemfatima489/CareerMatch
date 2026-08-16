from django.db import models
from django.core.exceptions import ValidationError
from users.models import CompanyProfile, Skill, ApplicantProfile
from constants import DEGREE_LEVEL_MODEL_CHOICES
from django.conf import settings     

# =========================================
# JOB
# =========================================

class Job(models.Model):
    LEVEL_CHOICES = [
        ("entry",  "Entry"),
        ("mid",    "Mid"),
        ("senior", "Senior"),
    ]

    company             = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name="jobs")
    title               = models.CharField(max_length=150)
    description         = models.TextField()
    level               = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    education_required  = models.TextField(blank=True)
    required_degree_level = models.CharField(
        max_length=30, choices=DEGREE_LEVEL_MODEL_CHOICES, blank=True, null=True,
        
    )
    accept_related_education_fields = models.BooleanField(
        default=True,
       
    )
   
    cached_title_vec = models.JSONField(null=True, blank=True)

    
    required_skills     = models.ManyToManyField(
                            Skill,
                            through="JobSkill",
                            blank=True,
                            related_name="jobs"
                          )

    experience_required = models.FloatField(default=0)
    location            = models.CharField(max_length=150)
    salary              = models.IntegerField(null=True, blank=True)
    is_active           = models.BooleanField(default=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    

    cached_job_vec      = models.JSONField(null=True, blank=True)
    cached_edu_fields = models.JSONField(null=True, blank=True)

    
    @property
    def required_skill_names(self):
        return list(
            self.job_skills.filter(is_optional=False)
                .values_list("skill__name", flat=True)
        )

    @property
    def optional_skill_names(self):
        return list(
            self.job_skills.filter(is_optional=True)
                .values_list("skill__name", flat=True)
        )

    def clean(self):
        if self.level == "entry" and self.experience_required > 1:
            raise ValidationError("Entry level jobs cannot require more than 1 year of experience.")
        if self.level == "mid" and not (2 <= self.experience_required <= 4):
            raise ValidationError("Mid level jobs require 2–4 years of experience.")
        if self.level == "senior" and self.experience_required < 5:
            raise ValidationError("Senior level jobs require 5+ years of experience.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
       

    def __str__(self):
        return self.title


# =========================================
# JOB SKILL  
# =========================================

class JobSkill(models.Model):
    job         = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="job_skills")
    skill       = models.ForeignKey(Skill, on_delete=models.CASCADE)
    is_optional = models.BooleanField(
                    default=False,
                    help_text="False = required (must-have). True = optional (nice-to-have)."
                  )

    class Meta:
        unique_together = ("job", "skill")

    def __str__(self):
        label = "optional" if self.is_optional else "required"
        return f"{self.skill.name} ({label}) — {self.job.title}"


# =========================================
# COMPATIBILITY
# =========================================

class Compatibility(models.Model):
    user             = models.ForeignKey(ApplicantProfile, on_delete=models.CASCADE, related_name="compatibilities")
    job              = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="compatibilities")

    score            = models.FloatField(default=0)
    skill_score      = models.FloatField(default=0)
    experience_score = models.FloatField(default=0)
    education_score  = models.FloatField(default=0)
    exceeds_experience = models.BooleanField(default=False)

    missing_skills   = models.JSONField(default=list, blank=True)

    
    matched_education_id   = models.IntegerField(null=True, blank=True)
    relevant_experience_ids = models.JSONField(default=list, blank=True)
    matched_skill_names = models.JSONField(default=list, blank=True)

    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "job")
        ordering        = ["-score"]

    def __str__(self):
        return f"{self.user.full_name} — {self.job.title} ({self.score}%)"


# =========================================
# INVITE
# =========================================

class InterviewInvite(models.Model):
    STATUS_CHOICES = [
        ("pending",   "Pending"),    
        ("accepted",  "Accepted"),   
        ("declined",  "Declined"),   
    ]

    job             = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="invites")
    applicant       = models.ForeignKey(ApplicantProfile, on_delete=models.CASCADE, related_name="invites")

    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    
    compatibility_score = models.FloatField(default=0)
    message         = models.TextField(blank=True)

    sent_at         = models.DateTimeField(auto_now_add=True)
    responded_at    = models.DateTimeField(null=True, blank=True)

    candidate_response  = models.TextField(blank=True)
   

    class Meta:
        unique_together = ("job", "applicant")   
        ordering        = ["-sent_at"]

    def __str__(self):
        return f"{self.job.title} → {self.applicant.full_name} [{self.status}]"



# =========================================
# SKILL FEEDBACK
# =========================================

class SkillMatchFeedback(models.Model):
    STATUS = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]

    job             = models.ForeignKey(Job, on_delete=models.CASCADE)
    applicant       = models.ForeignKey(ApplicantProfile, on_delete=models.CASCADE)
    submitted_by    = models.ForeignKey(CompanyProfile, null=True, blank=True, on_delete=models.SET_NULL)

    job_skill_text  = models.CharField(max_length=150)
    user_skill_text = models.CharField(max_length=150)
    judged_same     = models.BooleanField()

    status          = models.CharField(max_length=10, choices=STATUS, default="pending")
    reviewed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SkillAliasOverride(models.Model):
    skill_a_norm    = models.CharField(max_length=150, db_index=True)
    skill_b_norm    = models.CharField(max_length=150, db_index=True)
    source_feedback = models.ForeignKey(SkillMatchFeedback, null=True, on_delete=models.SET_NULL)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("skill_a_norm", "skill_b_norm")


class SkillDistinctOverride(models.Model):
    skill_a_norm    = models.CharField(max_length=150, db_index=True)
    skill_b_norm    = models.CharField(max_length=150, db_index=True)
    source_feedback = models.ForeignKey(SkillMatchFeedback, null=True, on_delete=models.SET_NULL)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("skill_a_norm", "skill_b_norm")


# =========================================
# TITLE FEEDBACK (education field OR experience role)
# =========================================

class TitleMatchFeedback(models.Model):
    KIND = [("experience_role", "Experience Role"), ("education_field", "Education Field")]
    STATUS = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]

    kind            = models.CharField(max_length=20, choices=KIND)
    job             = models.ForeignKey(Job, on_delete=models.CASCADE)
    applicant       = models.ForeignKey(ApplicantProfile, on_delete=models.CASCADE)
    submitted_by    = models.ForeignKey(CompanyProfile, null=True, blank=True, on_delete=models.SET_NULL)

    job_text        = models.CharField(max_length=200)
    user_text       = models.CharField(max_length=200)
    judged_same     = models.BooleanField()

    status          = models.CharField(max_length=10, choices=STATUS, default="pending")
    reviewed_by     = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TitleMatchOverride(models.Model):
    kind            = models.CharField(max_length=20, choices=TitleMatchFeedback.KIND)
    text_a_norm     = models.CharField(max_length=200, db_index=True)
    text_b_norm     = models.CharField(max_length=200, db_index=True)
    judged_same     = models.BooleanField()
    source_feedback = models.ForeignKey(TitleMatchFeedback, null=True, on_delete=models.SET_NULL)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("kind", "text_a_norm", "text_b_norm")


# =========================================
# MATCH FLAG (candidate-side)
# =========================================

class MatchFlag(models.Model):
    STATUS = [("open", "Open"), ("resolved", "Resolved")]

    compatibility = models.ForeignKey(Compatibility, on_delete=models.CASCADE, related_name="flags")
    applicant     = models.ForeignKey(ApplicantProfile, on_delete=models.CASCADE)
    note          = models.TextField(blank=True)
    status        = models.CharField(max_length=10, choices=STATUS, default="open")
    created_at    = models.DateTimeField(auto_now_add=True)
    resolved_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]