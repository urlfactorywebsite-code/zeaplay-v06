"""Validation shared by self-service and administrative profile updates."""

from pydantic import BaseModel, Field, field_validator


def validate_profile_write(value):
    limits = {
        "name": 255,
        "employer_id": 255,
        "title": 255,
        "phone": 50,
        "location": 255,
        "timezone": 64,
        "manager_email": 255,
        "shift_name": 255,
        "shift_start": 16,
        "shift_end": 16,
        "morning_break_start": 16,
        "morning_break_end": 16,
        "lunch_break_start": 16,
        "lunch_break_end": 16,
        "evening_break_start": 16,
        "evening_break_end": 16,
    }
    for field, limit in limits.items():
        content = getattr(value, field, None)
        if content is not None:
            content = content.strip()
            if len(content) > limit or (field == "name" and not content):
                raise ValueError(f"Invalid {field}: maximum length is {limit}")
            setattr(value, field, content)
    frame = getattr(value, "avatar_frame", None)
    if frame is not None and frame not in {
        "classic",
        "aurora",
        "solar",
        "emerald",
        "role-ring",
        "achievement-glow",
        "minimal",
    }:
        raise ValueError("Unknown avatar frame")
    return value


class ProfileFields(BaseModel):
    profile_bio: str | None = Field(default=None, max_length=500)
    skills: list[str] | None = Field(default=None, max_length=30)

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value):
        if value is None:
            return None
        result, seen = [], set()
        for skill in value:
            skill = " ".join(skill.split())
            if not skill or len(skill) > 60:
                raise ValueError("Skills must contain between 1 and 60 characters")
            if skill.casefold() not in seen:
                result.append(skill)
                seen.add(skill.casefold())
        return result
