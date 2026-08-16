from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from datetime import date, timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
import random
from django.utils import timezone
from constants import DEGREE_LEVEL_MODEL_CHOICES



# =========================================================
# USER MANAGER
# =========================================================
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        return self.create_user(email, password, **extra_fields)


# =========================================================
# USER
# =========================================================
class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    is_verified = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

# =========================================================
# OTPVerification
# =========================================================

class OTPVerification(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="otp")
    code       = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now=True)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    @staticmethod
    def generate_code():
        return str(random.randint(100000, 999999))

    def __str__(self):
        return f"OTP for {self.user.email}"


# =========================================================
# SKILL
# =========================================================
class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


# =========================================================
# APPLICANT PROFILE
# =========================================================
class ApplicantProfile(models.Model):
    LEVEL_CHOICES = [
        ("entry", "Entry"),
        ("mid", "Mid"),
        ("senior", "Senior"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=150)
    is_open_to_opportunities = models.BooleanField(default=True)

    skills = models.ManyToManyField(Skill, blank=True)
    current_level = models.CharField(
        max_length=20,
        choices=LEVEL_CHOICES,
        default="entry"
    )
    resume = models.FileField(upload_to="resumes/", null=True, blank=True)

    cached_profile_data = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.full_name

    @property
    def education_text(self):
        all_educations = self.educations.all()
        valid_degrees = []
    
        for edu in all_educations:
            degree_name = edu.degree
            if degree_name:
                cleaned_name = degree_name.strip()
                if cleaned_name != "":
                    valid_degrees.append(cleaned_name)
    
        combined_text = " ".join(valid_degrees)
        final_text = combined_text.strip()
        return final_text

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
  

# =========================================================
# EDUCATION
# =========================================================
class Education(models.Model):
    applicant = models.ForeignKey(
        ApplicantProfile,
        on_delete=models.CASCADE,
        related_name="educations"
    )
    degree = models.CharField(max_length=120)
    degree_level = models.CharField(
        max_length=30, choices=DEGREE_LEVEL_MODEL_CHOICES
    )
    institution = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.degree} — {self.institution}"


# =========================================================
# EXPERIENCE
# =========================================================
class Experience(models.Model):
    applicant = models.ForeignKey(
        ApplicantProfile,
        on_delete=models.CASCADE,
        related_name="experiences"
    )
    role = models.CharField(max_length=150)
    company = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    skills_used = models.ManyToManyField(
        Skill,
        blank=False,
        related_name="used_in_experiences",
    )

    

    @property
    def years(self):
        if self.is_current or not self.end_date:
            end = date.today()
        else:
            end = self.end_date

        days_worked = (end - self.start_date).days
        delta = days_worked / 365.25

        return round(max(delta, 0), 1)

    def __str__(self):
        return f"{self.role} at {self.company}"


# =========================================================
# COMPANY PROFILE
# =========================================================
class CompanyProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=150)

    def __str__(self):
        return self.company_name


