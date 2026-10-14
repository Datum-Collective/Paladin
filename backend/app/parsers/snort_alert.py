"""Snort/Suricata fast-format alert -> Event (EvidenceForge emits snort_alert).

  05/14-12:55:03.123456  [**] [1:2013504:3] ET SCAN Nikto [**] [Classification: ...] [Priority: 2] {TCP} 1.2.3.4:5 -> 5.6.7.8:80
"""
import re

from ..models import Event

LINE = re.compile(
    r"^(?P<ts>\d\d/\d\d(?:/\d{2,4})?-\d\d:\d\d:\d\d)(?:\.\d+)?\s+\[\*\*\]\s+\[(?P<sid>[\d:]+)\]\s+"
    r"(?P<msg>.*?)\s+\[\*\*\].*?\{(?P<proto>\w+)\}\s+(?P<src>[\d.]+)(?::(?P<sp>\d+))?\s+->\s+"
    r"(?P<dst>[\d.]+)(?::(?P<dp>\d+))?")


def parse(line: str, year: int = 2024) -> Event:
    m = LINE.match(line.strip())
    if not m:
        raise ValueError("not a snort fast alert")
    mo_d, t = m["ts"].split("-")
    parts = mo_d.split("/")
    mon, day = parts[0], parts[1]
    ts = f"{year}-{mon}-{day}T{t}Z"
    msg = m["msg"]
    low = msg.lower()
    attack = "T1046" if "scan" in low else "T1190" if ("exploit" in low or "web" in low) else ""
    return Event(ts=ts, source="ids_alert", type="ids_alert", host=m["dst"], src_ip=m["src"],
                 dst=m["dst"], outcome="alert", attack=attack, raw=line.strip()[:2000])
