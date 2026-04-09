from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ProfileRequest(BaseModel):
    pool_id: str = Field(min_length=2, max_length=32)
    pool_name: str = Field(min_length=1, max_length=64)
    gate_id: str = Field(min_length=2, max_length=32)
    gate_name: str = Field(min_length=1, max_length=64)


class ProfileNamesRequest(BaseModel):
    pool_name: str = Field(min_length=1, max_length=64)
    gate_name: str = Field(min_length=1, max_length=64)


class AdoptRequest(BaseModel):
    pending_pool_id: Optional[str] = Field(default=None, min_length=2, max_length=32)
    kit_id: Optional[str] = Field(default=None, min_length=2, max_length=32)
    kit_name: Optional[str] = Field(default=None, min_length=1, max_length=64)


class KitRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class DisplayRequest(BaseModel):
    msg: str = Field(min_length=1, max_length=64)
    duration: int = Field(default=5000, ge=500, le=60000)


class SkillRefRequest(BaseModel):
    kit_id: str = Field(min_length=2, max_length=32)
    skill_id: str = Field(min_length=2, max_length=64)


class EventConditionRequest(BaseModel):
    source_kit_id: str = Field(min_length=2, max_length=32)
    source_skill: str = Field(min_length=2, max_length=64)
    operator: Literal["==", "!=", ">", ">=", "<", "<="]
    threshold: Any


class EventActionRequest(BaseModel):
    target_kit_id: str = Field(min_length=2, max_length=32)
    target_skill: str = Field(min_length=2, max_length=64)
    action: str = Field(default="SET", min_length=2, max_length=32)
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    mode: Literal["form", "code"] = "form"
    enabled: bool = True
    cooldown_ms: int = Field(default=1000, ge=100, le=120000)
    condition: Optional[EventConditionRequest] = None
    action: Optional[EventActionRequest] = None
    code: str = ""
    required_skills: List[SkillRefRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "EventUpsertRequest":
        if self.mode == "form":
            if self.condition is None or self.action is None:
                raise ValueError("Form mode requires condition and action.")
        if self.mode == "code":
            if not self.code.strip():
                raise ValueError("Code mode requires non-empty code.")
        return self


class EventToggleRequest(BaseModel):
    enabled: bool
