"""Persistent publishing preferences shared by the API and worker."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import Settings


class PublishingPreferences(BaseModel):
    enabled: bool = False
    description: str = Field(default="", max_length=4000, pattern=r"^[^<>]*$")
    hashtags: str = Field(default="#Shorts", max_length=500, pattern=r"^[^<>]*$")
    privacy: Literal["public", "unlisted", "private"] = "public"


def preferences(settings: Settings) -> PublishingPreferences:
    from app.services.youtube import ledger

    with ledger(settings) as db:
        db.execute("CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY, data TEXT)")
        row = db.execute("SELECT data FROM preferences WHERE id=1").fetchone()
    if row:
        return PublishingPreferences.model_validate_json(row[0])
    return PublishingPreferences(
        enabled=settings.youtube_auto_publish, privacy=settings.youtube_privacy
    )


def save_preferences(settings: Settings, value: PublishingPreferences) -> None:
    from app.services.youtube import ledger

    preferences(settings)
    with ledger(settings) as db:
        db.execute("INSERT OR REPLACE INTO preferences VALUES (1, ?)", (value.model_dump_json(),))


def description_text(value: PublishingPreferences) -> str:
    tags = list(
        dict.fromkeys("#" + tag.lstrip("#") for tag in value.hashtags.split() if tag != "#")
    )
    return "\n\n".join(part for part in [value.description.strip(), " ".join(tags)] if part)
