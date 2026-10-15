"""Linux auth syslog (sshd) -> Event. Raises ValueError on lines it does not understand."""
import re
from datetime import datetime, timezone

from ..models import Event

LINE = re.compile(
    r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d\d:\d\d:\d\d)\s+(?P<host>\S+)\s+"
    r"(?P<proc>[\w\-/]+)(?:\[\d+\])?:\s+(?P<msg>.*)$")
RFC5424 = re.compile(
    r"^<\d+>\d+\s+(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<proc>\S+)\s+"
    r"\S+\s+\S+\s+(?:-|\[[^\]]*\])\s+(?P<msg>.*)$")
ACCEPT = re.compile(r"Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<ip>\S+) port \d+")
FAIL = re.compile(r"Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port \d+")
INVALID = re.compile(r"Invalid user (?P<user>\S+) from (?P<ip>\S+)")


def _ts(mon: str, day: str, t: str, year: int) -> str:
    dt = datetime.strptime(f"{year} {mon} {day} {t}", "%Y %b %d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def parse(line: str, year: int = 2024) -> Event:
    text = line.strip()
    modern = RFC5424.match(text)
    legacy = LINE.match(text) if modern is None else None
    if modern is None and legacy is None:
        raise ValueError("not a syslog line")
    if modern is not None:
        host, msg, proc = modern["host"], modern["msg"], modern["proc"]
        ts = modern["ts"]
    else:
        assert legacy is not None
        host, msg, proc = legacy["host"], legacy["msg"], legacy["proc"]
        ts = _ts(legacy["mon"], legacy["day"], legacy["time"], year)
    base = dict(ts=ts, source="linux_auth", host=host, dst=host, raw=text[:2000])
    if proc != "sshd" and not proc.startswith("sshd"):
        return Event(**base, type="syslog", outcome="info")
    if a := ACCEPT.search(msg):
        return Event(**base, type="auth_success", actor=a["user"], src_ip=a["ip"], outcome="success",
                     attack="T1078")
    if f := FAIL.search(msg):
        return Event(**base, type="auth_failure", actor=f["user"], src_ip=f["ip"], outcome="failure",
                     attack="T1110")
    if i := INVALID.search(msg):
        return Event(**base, type="auth_failure", actor=i["user"], src_ip=i["ip"], outcome="failure",
                     attack="T1110")
    return Event(**base, type="syslog", outcome="info")
