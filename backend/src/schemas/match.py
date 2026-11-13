from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MatchRunIn(BaseModel):
    period: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    trigger: Literal["manual", "schedule", "seed"] = "manual"
    remark: str | None = Field(default=None, max_length=200)


class CaseReviewIn(BaseModel):
    status: Literal["pending", "returned", "written_off", "accepted"]
    note: str | None = Field(default=None, max_length=1000)
