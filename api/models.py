from typing import Any, Literal

from pydantic import BaseModel, Field


class Sample(BaseModel):
    """One 5-minute reading from the ring. Any sensor value can be missing."""

    t: int = Field(ge=0, description="minutes since the start of the night")
    hr: float | None = Field(None, ge=20, le=250)
    hrv: float | None = Field(None, ge=0, le=300)
    movement: float | None = Field(None, ge=0, le=1)
    temp: float | None = Field(None, ge=25, le=45)


class Packet(BaseModel):
    seq: int = Field(ge=0)
    # Kept as raw dicts: the checksum is computed over what was sent, not over a
    # re-serialised model. Each sample is validated against `Sample` in the handler.
    samples: list[dict[str, Any]]
    checksum: int


class SyncRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    night_id: str = Field(min_length=1, max_length=64)
    total_packets: int = Field(ge=1, le=1000)
    packets: list[Packet] = Field(max_length=1000)


class Rejection(BaseModel):
    seq: int
    reason: Literal[
        "seq_out_of_range",
        "empty_packet",
        "bad_checksum",
        "invalid_samples",
        "conflicting_duplicate",
    ]


class SyncStatus(BaseModel):
    night_id: str
    sync_status: Literal["complete", "partial"]
    received_packets: int
    total_packets: int
    missing_packets: list[int]


class SyncResponse(SyncStatus):
    accepted: int
    duplicates: int
    rejected: list[Rejection]


class Insights(SyncStatus):
    sleep_minutes: int | None
    sleep_score: int | None = Field(None, ge=0, le=100)
    readiness_score: int | None = Field(None, ge=0, le=100)
    readiness_formula: str
