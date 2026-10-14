"""Linux auth syslog (sshd) -> Event. Raises ValueError on lines it does not understand."""
import re
from datetime import datetime, timezone

from ..models import Event

LINE = re.compile(
    r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d\d:\d\d:\d\d)\s+(?P<host>\S+)\s+"
    r"(?P<proc>[\w\-/]+)(?:\[\d+\])?:\s+(?P<msg>.*)$")
ACCEPT = re.compile(r"Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<ip>\S+) port \d+")
FAIL = re.compile(r"Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port \d+")
INVALID = re.compile(r"Invalid user (?P<user>\S+) from (?P<ip>\S+)")


def _ts(mon: str, day: str, t: str, year: int) -> str:
    dt = datetime.strptime(f"{year} {mon} {day} {t}", "%Y %b %d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def parse(line: str, year: int = 2024) -> Event:
    m = LINE.match(line.strip())
    if not m:
        raise ValueError("not a syslog line")
    host, msg = m["host"], m["msg"]
    base = dict(ts=_ts(m["mon"], m["day"], m["time"], year), source="linux_auth", host=host, dst=host,
                raw=line.strip()[:2000])
    if m["proc"] != "sshd" and not m["proc"].startswith("sshd"):
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
