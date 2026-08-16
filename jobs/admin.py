from django.contrib import admin
from .models import (
    Job, Compatibility, InterviewInvite, JobSkill,
    SkillMatchFeedback, SkillAliasOverride, SkillDistinctOverride,
    TitleMatchFeedback, TitleMatchOverride, MatchFlag,
)


admin.site.register(Job)
admin.site.register(Compatibility)
admin.site.register(InterviewInvite)
admin.site.register(JobSkill)
admin.site.register(SkillAliasOverride)
admin.site.register(SkillDistinctOverride)
admin.site.register(TitleMatchOverride)
admin.site.register(MatchFlag)