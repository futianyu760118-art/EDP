"""LeadIntakeV1 contract models at the internal EDP intake boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9._:-]{1,160}$"


class LeadContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    email_or_phone: str = Field(min_length=3, max_length=320)


class LeadConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted: Literal[True]
    version: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=160)
    retention_until: datetime
    deletion_requested: bool = False


class LeadIntakeIn(BaseModel):
    """AEOS LeadIntakeV1; tenant_id is checked against authenticated context."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["LeadIntakeV1"]
    intake_id: str = Field(min_length=1, max_length=160)
    source_system: Literal["PUBLIC_BFF"]
    submitted_at: datetime
    contact: LeadContact
    interest: str = Field(min_length=1, max_length=160)
    message: str | None = Field(default=None, max_length=4000)
    consent: LeadConsent
    trace_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=160)


class LeadIntakeResponse(BaseModel):
    lead_reference: str
    deduplicated: bool = False
