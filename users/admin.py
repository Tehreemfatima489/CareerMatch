from django.contrib import admin
from .models import User, Education, Experience, Skill, ApplicantProfile, CompanyProfile


# Register your models here.

admin.site.register(User)
admin.site.register(Education)
admin.site.register(Experience)
admin.site.register(Skill)
admin.site.register(ApplicantProfile)
admin.site.register(CompanyProfile)