from typing import Literal, Optional

from pydantic import BaseModel, Field

# component = a source file, weakness = a finding in it (both come only from a code scan)
NodeKind = Literal["identity", "host", "secret", "role", "service", "data", "external", "component", "weakness"]


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


class Node(BaseModel):
    id: str
    kind: NodeKind
    label: str
    criticality: int = Field(default=1, ge=1, le=10)
    meta: dict = {}          # evidence shown in the inspector: file, line, cwe, snippet, ...


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
    # how the step is supported: 'finding' = a rule or review hit in code, 'assumed' = a stated assumption with no
    # evidence behind it, '' = log-based (see `observed`/`evidence`). `note` says why, in one sentence.
    basis: Literal['', 'finding', 'assumed'] = ''
    note: str = Field(default='', max_length=300)
