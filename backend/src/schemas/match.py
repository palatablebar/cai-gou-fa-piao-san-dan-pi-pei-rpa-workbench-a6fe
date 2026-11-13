from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MatchRunIn(BaseModel):
    period: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    trigger: Literal["manual", "schedule", "seed"] = "manual"
    remark: str | None = Field(default=None, max_length=200)
    # 批次幂等键：同一批次的重复推送必须带同一个 key；留空 = period:<账期>
    batch_key: str | None = Field(default=None, min_length=3, max_length=120)
    # 强制重算（默认同一水位直接复用已有版本，不新增运行）
    force: bool = False


class BatchCreateIn(BaseModel):
    period: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    batch_key: str | None = Field(default=None, min_length=3, max_length=120)
    remark: str | None = Field(default=None, max_length=200)
    trigger: Literal["manual", "schedule", "seed"] = "manual"
    force: bool = False


class BatchRecomputeIn(BaseModel):
    trigger: Literal["manual", "schedule", "seed"] = "manual"
    force: bool = True


class BatchSwitchIn(BaseModel):
    version_id: int | None = Field(default=None, ge=1)
    # 故障注入（验收「切换失败恢复上一版」）：在事务内制造异常，验证回滚
    simulate_failure: bool = False


class BatchRollbackIn(BaseModel):
    version_id: int | None = Field(default=None, ge=1)


class CaseReviewIn(BaseModel):
    status: Literal["pending", "returned", "written_off", "accepted"]
    note: str | None = Field(default=None, max_length=1000)
