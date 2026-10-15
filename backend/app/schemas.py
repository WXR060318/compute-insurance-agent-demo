from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .data import COMPANIES, SCENARIOS


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvaluateRequest(RequestModel):
    company_id: str = "xinghe"
    scenario_id: str = "surge"
    minute: int = Field(default=30, ge=0, le=240, multiple_of=5, strict=True)
    budget: Decimal | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    min_quality: float = Field(default=98, ge=0, le=100, allow_inf_nan=False)
    sort_by: Literal["cost", "quality"] = "cost"

    @field_validator("company_id")
    @classmethod
    def known_company(cls, value: str) -> str:
        if value not in {company["id"] for company in COMPANIES}:
            raise ValueError("未知模拟企业")
        return value

    @field_validator("scenario_id")
    @classmethod
    def known_scenario(cls, value: str) -> str:
        if value not in {scenario["id"] for scenario in SCENARIOS}:
            raise ValueError("未知模拟场景")
        return value


class ChatRequest(RequestModel):
    snapshot_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1200)


class PlanCreateRequest(RequestModel):
    snapshot_id: str = Field(min_length=1, max_length=100)
    supplier_id: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=128)


class PlanConfirmRequest(RequestModel):
    reviewer: str = Field(default="演示操作员", min_length=1, max_length=80)
