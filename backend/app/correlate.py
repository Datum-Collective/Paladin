"""Events confirm inventory edges: observed=true, p rises, evidence ids attach."""
from .models import Edge, Event

P_CAP = 0.99
P_STEP = 0.5
MAX_EVIDENCE = 20


def _field_ok(want, got: str) -> bool:
    if want == "*":
        return True
    if isinstance(want, list):
        return got in want
    return got == want


def matches(edge: Edge, ev: Event) -> bool:
    specs = edge.match if isinstance(edge.match, list) else [edge.match]
    return any(s and all(_field_ok(w, getattr(ev, k, "")) for k, w in s.items()) for s in specs)


def correlate(edges: list[Edge], events: list[Event]) -> list[Edge]:
    """Return fresh edges with p/observed/evidence updated from events. Pure; inputs are not mutated."""
    out = [e.model_copy(deep=True) for e in edges]
    for ev in events:
        for e in out:
            if ev.id in e.evidence:
                continue
            if matches(e, ev):
                e.observed = True
                e.p = min(P_CAP, e.p + (1 - e.p) * P_STEP)
                if len(e.evidence) < MAX_EVIDENCE:
                    e.evidence.append(ev.id)
    return out
