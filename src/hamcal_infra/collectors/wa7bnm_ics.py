from __future__ import annotations

import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from ..collector_base import Collector, CollectorMeta
from ..types import (
    StagedEventV1,
    LinkV1,
    utc_now_iso,
    sha256_text,
)

DEFAULT_WA7BNM_CAL_ID = "9o3or51jjdsantmsqoadmm949k@group.calendar.google.com"
DEFAULT_WA7BNM_ICS_URL = (
    "https://calendar.google.com/calendar/ical/"
    + urllib.parse.quote(DEFAULT_WA7BNM_CAL_ID, safe="")
    + "/public/basic.ics"
)

SOURCE_NAME = "wa7bnm_gcal"
DEFAULT_TRUST = 75


def _unfold_ics_lines(text: str) -> List[str]:
    raw = text.splitlines()
    out: List[str] = []
    for line in raw:
        if not line:
            out.append(line)
            continue
        if line.startswith((" ", "\t")) and out:
            out[-1] = out[-1] + line[1:]
        else:
            out.append(line)
    return out


def _parse_ics_datetime(value: str) -> Tuple[str, Optional[str]]:
    value = value.strip()

    # All-day date
    if re.fullmatch(r"\d{8}", value):
        y = value[0:4]
        m = value[4:6]
        d = value[6:8]
        return f"{y}-{m}-{d}T00:00:00Z", None

    # Date-time
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?", value)
    if not m:
        raise ValueError(f"Unsupported DTSTART/DTEND format: {value}")

    y, mo, d, hh, mm, ss, z = m.groups()
    if z == "Z":
        return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}Z", None

    # If no Z, assume UTC in v1.
    return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}Z", None


def _extract_prop(line: str) -> Tuple[str, Dict[str, str], str]:
    if ":" not in line:
        return line.strip(), {}, ""
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].strip().upper()
    params: Dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().upper()] = v.strip()
        else:
            params[p.strip().upper()] = ""
    return name, params, value.strip()


def _parse_vevents(ics_text: str) -> List[Dict[str, List[Tuple[Dict[str, str], str]]]]:
    lines = _unfold_ics_lines(ics_text)
    events: List[Dict[str, List[Tuple[Dict[str, str], str]]]] = []
    in_event = False
    cur: Dict[str, List[Tuple[Dict[str, str], str]]] = {}

    for line in lines:
        line = line.rstrip("\r\n")
        if line == "BEGIN:VEVENT":
            in_event = True
            cur = {}
            continue
        if line == "END:VEVENT":
            if in_event:
                events.append(cur)
            in_event = False
            cur = {}
            continue
        if not in_event:
            continue
        if not line or line.startswith("BEGIN:") or line.startswith("END:"):
            continue
        name, params, value = _extract_prop(line)
        cur.setdefault(name, []).append((params, value))

    return events


def _first(prop: Dict[str, List[Tuple[Dict[str, str], str]]], key: str) -> Optional[Tuple[Dict[str, str], str]]:
    items = prop.get(key.upper())
    if not items:
        return None
    return items[0]


def _parse_isoz(s: str) -> datetime:
    # RFC3339 UTC "....Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


class WA7BNMICSCollector(Collector):
    def __init__(self, ics_url: Optional[str] = None) -> None:
        self.ics_url = ics_url or os.environ.get("WA7BNM_ICS_URL") or DEFAULT_WA7BNM_ICS_URL

        # Window controls (days relative to now UTC)
        self.from_days = int(os.environ.get("HAMCAL_FROM_DAYS", "-30"))
        self.to_days = int(os.environ.get("HAMCAL_TO_DAYS", "120"))
        self.max_events = int(os.environ.get("HAMCAL_MAX_EVENTS", "5000"))

    def meta(self) -> CollectorMeta:
        return CollectorMeta(
            name=SOURCE_NAME,
            trust_default=DEFAULT_TRUST,
            homepage="https://www.contestcalendar.com/",
            notes="ICS-based collector reading the public WA7BNM Google Calendar feed (bounded window).",
        )

    def _fetch_ics(self) -> str:
        req = urllib.request.Request(
            self.ics_url,
            headers={
                "User-Agent": "HamCal/infra-v1 (+https://github.com/DReason3/HamCal)",
                "Accept": "text/calendar,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        return data.decode("utf-8", errors="replace")

    def collect(self) -> List[StagedEventV1]:
        observed = utc_now_iso()
        ics_text = self._fetch_ics()
        vevents = _parse_vevents(ics_text)

        now = datetime.now(timezone.utc)
        window_start = now + timedelta(days=self.from_days)
        window_end = now + timedelta(days=self.to_days)

        out: List[StagedEventV1] = []

        for ev in vevents:
            uid_t = _first(ev, "UID")
            sum_t = _first(ev, "SUMMARY")
            dtstart_t = _first(ev, "DTSTART")
            dtend_t = _first(ev, "DTEND")

            if not uid_t or not sum_t or not dtstart_t:
                continue

            uid = uid_t[1]
            summary = sum_t[1]

            start_utc, _ = _parse_ics_datetime(dtstart_t[1])
            if dtend_t:
                end_utc, _ = _parse_ics_datetime(dtend_t[1])
            else:
                end_utc = start_utc

            # Window filter based on start time
            try:
                start_dt = _parse_isoz(start_utc)
            except Exception:
                continue

            if start_dt < window_start or start_dt > window_end:
                continue

            desc_t = _first(ev, "DESCRIPTION")
            url_t = _first(ev, "URL")

            raw_excerpt_parts = [summary]
            if desc_t and desc_t[1]:
                raw_excerpt_parts.append(desc_t[1])
            raw_excerpt = " | ".join(raw_excerpt_parts)
            raw_excerpt = raw_excerpt.replace("\\n", " ").replace("\n", " ").strip()
            raw_excerpt = re.sub(r"\s+", " ", raw_excerpt)

            links: List[LinkV1] = []
            if url_t and url_t[1]:
                links.append(LinkV1(rel="info", url=url_t[1]))

            raw_hash = sha256_text(f"{uid}|{start_utc}|{end_utc}|{summary}|{raw_excerpt}")

            out.append(
                StagedEventV1(
                    source=SOURCE_NAME,
                    source_uid=uid,
                    name=summary,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    status="scheduled",
                    raw_hash=raw_hash,
                    raw_excerpt=raw_excerpt[:500],
                    observed_utc=observed,
                    type="contest",
                    links=links,
                )
            )

            if len(out) >= self.max_events:
                break

        return out
