"""The kids-mode policy model (data only). Rules that use it live in app/services/policy.py."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AppName = Literal["youtube", "netflix", "spotify"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str = "07:00"
    end: str = "21:00"
    apps: list[AppName] = Field(default_factory=lambda: ["youtube", "netflix", "spotify"], max_length=3)
    can_power_off: bool = False
    can_schedule: bool = False
    daily_limit_min: int | None = Field(default=None, ge=10, le=720)  # None = no daily limit

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("time must be HH:MM")
        return v

    @model_validator(mode="after")
    def _order(self) -> Policy:
        if self.start >= self.end:  # one window inside a single day keeps the rules easy to reason about
            raise ValueError("start must be before end")
        return self
