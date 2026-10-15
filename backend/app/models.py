from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

NodeKind = Literal["identity", "host", "secret", "role", "service", "data", "external"]


class Event(BaseModel):
    id: str = ""
    ts: str
    source: str = Field(max_length=32)
    type: str = Field(max_length=64)
    actor: str = Field(default="", max_length=128)
    host: str = Field(default="", max_length=128)
    src_ip: str = Field(default="", max_length=64)
    dst: str = Field(default="", max_length=128)
    outcome: str = Field(default="info", max_length=16)
    attack: str = Field(default="", max_length=16)
    raw: str = Field(default="", max_length=2000)

    @field_validator("ts")
    @classmethod
    def _ts_is_a_timestamp(cls, v: str) -> str:
        # the timeline and risk series parse every event's ts; one unparseable value would 500 them for the
        # whole workspace, so it is refused here, where the event enters
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError("ts must be an ISO-8601 timestamp, e.g. 2024-05-14T13:05:11Z") from None
        return v


class Node(BaseModel):
    id: str
    kind: NodeKind
    label: str
    criticality: int = Field(default=1, ge=1, le=10)


class Edge(BaseModel):
    id: str
    src: str
    dst: str
    technique: str
    p: float = Field(gt=0, le=1)
    cost: Optional[float] = None
    observed: bool = False
    evidence: list[str] = []
    mitigation: str = ""
    match: dict | list[dict] = {}
