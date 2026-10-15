"""Nginx/Apache combined access log -> Event. Scanner-looking requests are typed web_scan."""
import re
from datetime import datetime, timezone

from ..models import Event

LINE = re.compile(
    r'^(?P<ip>\S+) \S+ (?P<user>\S+) \[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) \S+(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?')
SCAN_UA = ("nikto", "sqlmap", "nmap", "masscan", "dirbuster", "gobuster", "wpscan")
SCAN_PATH = ("/.env", "/.git", "/wp-login", "/phpmyadmin", "/admin", "/etc/passwd", "../", "/cgi-bin")


def parse(line: str, host: str = "WEB-BO-01") -> Event:
    m = LINE.match(line.strip())
    if not m:
        raise ValueError("not a combined access log line")
    ts = datetime.strptime(m["ts"], "%d/%b/%Y:%H:%M:%S %z").astimezone(timezone.utc)
    ua = (m["ua"] or "").lower()
    path = m["path"].lower()
    scan = any(s in ua for s in SCAN_UA) or any(s in path for s in SCAN_PATH)
    status = int(m["status"])
    return Event(
        ts=ts.isoformat().replace("+00:00", "Z"), source="web_access",
        type="web_scan" if scan else "web_request", actor="" if m["user"] == "-" else m["user"],
        host=host, src_ip=m["ip"], dst=host, outcome="success" if status < 400 else "failure",
        attack="T1595.002" if scan else "", raw=line.strip()[:2000])
