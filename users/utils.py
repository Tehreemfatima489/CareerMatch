from .models import Skill


def get_or_create_skill(name):
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Skill name cannot be empty")

    skill = Skill.objects.filter(name__iexact=trimmed).first()
    if skill:
        return skill

    return Skill.objects.create(name=trimmed)