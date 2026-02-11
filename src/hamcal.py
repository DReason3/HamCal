#!/usr/bin/env python3
"""
HAMCAL - build pre-filtered iCal (.ics) calendars for ham contests + hamfests + Field Day.

MVP:
- Rolling ~2-month lookahead
- 3 sources:
  1) WA7BNM via public Google Calendar ICS
  2) ARRL Contest Calendar (best-effort parse + Field Day rule)
  3) ARRL Hamfests database (best-effort parse)

Outputs:
- docs/all.ics
- docs/cw.ics
- docs/phone.ics
- docs/digital.ics
- docs/hamfests.ics
- docs/field-day.ics
- docs/summary.html (printable monthly summary with UTC + Central and duration)
- docs/index.html (subscribe page + link to summary)
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, date
from typing import List, Optional, Dict, Tuple

import requests
from dateutil import parser as dtparser
from zoneinfo import ZoneInfo

UA = "HAMCAL/0.1 (+https://github.com/dreason3/hamcal) python-requests"

# ---- Time window ----
NOW_UTC = datetime.now(timezone.utc)
HORIZON_END_UTC = NOW_UTC + timedelta(days=62)  # ~2 months

# ---- Timezones ----
CHI_TZ = ZoneInfo("America/Chicago")

# ---- Source URLs ----
WA7BNM_GCAL_ID = "9o3or51jjdsantmsqoadmm949k@group.calendar.google.com"
WA7BNM_GCAL_ICS = f"https://calendar.google.com/calendar/ical/{WA7BNM_GCAL_ID}/public/basic.ics"

ARRL_CONTEST_CAL_URL = "https://www.arrl.org/contest-calendar"
ARRL_HAMFEST_PAGE_URL = "https://www.arrl.org/hamfests/search/page:{page}/model:event"

OUT_DIR = os.path.join("docs")

# ---- Tagging rules ----
DIGITAL_KEYWORDS = ["RTTY", "FT8", "FT4", "PSK", "DIGI", "DIGITAL", "SSTV", "JS8", "MFSK"]
PHONE_KEYWORDS = ["SSB", "PHONE", "AM", "FM"]
CW_KEYWORDS = ["CW"]

FIELD_DAY_KEYWORDS = ["FIELD DAY"]


@dataclass
class Event:
    title: str
    start: datetime  # UTC
    end: datetime    # UTC
    url: Optional[str] = None
    description: Optional[str] = None
    categories: List[str] = field(default_factory=list)  # e.g. ["contest","cw"]
    source: str = "unknown"

    def uid(self) -> str:
        h = hashlib.sha256()
        h.update((self.source + "|" + self.title + "|" + self.start.isoformat() + "|" + (self.url or "")).encode("utf-8"))
        return h.hexdigest()[:32] + "@hamcal"

    def is_in_window(self) -> bool:
        return (self.end > NOW_UTC) and (self.start < HORIZON_END_UTC)

    def add_category(self, c: str) -> None:
        if c not in self.categories:
            self.categories.append(c)


# ---------------- Dual time + duration helpers ----------------

def fmt_dual(dt_utc: datetime) -> str:
    """Return 'UTC … | CT …' with CT showing CST/CDT automatically."""
    dt_utc = dt_utc.astimezone(timezone.utc)
    dt_ct = dt_utc.astimezone(CHI_TZ)

    utc_s = dt_utc.strftime("%Y-%m-%d %H:%MZ")
    ct_s = dt_ct.strftime("%Y-%m-%d %I:%M%p %Z").lstrip("0").replace(" 0", " ")
    return f"{utc_s} | {ct_s}"


def fmt_duration(start_utc: datetime, end_utc: datetime) -> str:
    """Human duration like 2h, 30m, 1d 4h 15m."""
    delta = end_utc.astimezone(timezone.utc) - start_utc.astimezone(timezone.utc)
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "0m"

    mins = total_seconds // 60
    days = mins // (60 * 24)
    mins = mins % (60 * 24)
    hours = mins // 60
    mins = mins % 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


# ---------------- ICS helpers ----------------

def ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\")
                .replace("\n", "\\n")
                .replace(",", "\\,")
                .replace(";", "\\;"))


def dt_to_ics(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def build_ics(calendar_name: str, events: List[Event]) -> str:
    lines = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//HAMCAL//hamcal//EN")
    lines.append("CALSCALE:GREGORIAN")
    lines.append(f"X-WR-CALNAME:{ics_escape(calendar_name)}")
    lines.append("X-WR-TIMEZONE:UTC")

    events = sorted(events, key=lambda e: e.start)

    for e in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{e.uid()}")
        lines.append(f"DTSTAMP:{dt_to_ics(NOW_UTC)}")
        lines.append(f"DTSTART:{dt_to_ics(e.start)}")
        lines.append(f"DTEND:{dt_to_ics(e.end)}")
        lines.append(f"SUMMARY:{ics_escape(e.title)}")

        # Always include the URL field when present
        if e.url:
            lines.append(f"URL:{ics_escape(e.url)}")

        # Make the link visible in Description too (some calendar apps hide URL)
        desc_out = (e.description or "").strip()
        if e.url and (e.url not in desc_out):
            if desc_out:
                desc_out += "\n\n"
            desc_out += f"Rules & details:\n{e.url}"

        if desc_out:
            lines.append(f"DESCRIPTION:{ics_escape(desc_out)}")

        if e.categories:
            lines.append(f"CATEGORIES:{ics_escape(','.join(e.categories))}")

        lines.append("END:VEVENT")
    return "\r\n".join(lines) + "\r\n"


# ---------------- Ingest: WA7BNM via Google Calendar ICS ----------------

def parse_google_ics_datetime(value: str) -> datetime:
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value, "%Y%m%d").date()
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    dt = dtparser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ingest_wa7bnm_gcal() -> List[Event]:
    r = requests.get(WA7BNM_GCAL_ICS, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    text = r.text

    events: List[Event] = []
    blocks = text.split("BEGIN:VEVENT")
    for b in blocks[1:]:
        vevent = "BEGIN:VEVENT" + b

        dtstart = extract_ics_field(vevent, "DTSTART")
        dtend = extract_ics_field(vevent, "DTEND")
        summary = extract_ics_field(vevent, "SUMMARY") or "Contest"
        url = extract_ics_field(vevent, "URL")
        desc = extract_ics_field(vevent, "DESCRIPTION")

        if not dtstart:
            continue

        start = parse_google_ics_datetime(dtstart)
        end = parse_google_ics_datetime(dtend) if dtend else (start + timedelta(hours=1))

        e = Event(
            title=unfold_ics_text(summary),
            start=start,
            end=end,
            url=unfold_ics_text(url) if url else None,
            description=unfold_ics_text(desc) if desc else None,
            source="wa7bnm-gcal"
        )
        e.add_category("contest")
        tag_modes(e)
        tag_field_day(e)

        if e.is_in_window():
            events.append(e)

    return events


def extract_ics_field(vevent: str, field_name: str) -> Optional[str]:
    vevent_u = unfold_ics(vevent)
    m = re.search(rf"^{field_name}(;[^:]*)?:(.*)$", vevent_u, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(2).strip()


def unfold_ics(ics_text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", ics_text)


def unfold_ics_text(value: str) -> str:
    if value is None:
        return ""
    v = value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    return v.strip()


# ---------------- Ingest: ARRL contest calendar (best-effort) ----------------

def ingest_arrl_contests() -> List[Event]:
    r = requests.get(ARRL_CONTEST_CAL_URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    html_text = r.text

    text = strip_html(html_text)

    events: List[Event] = []

    # Best-effort: look for ISO date strings if present, otherwise rely on WA7BNM for most contests.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", line)
        if m:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            title = line
            start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            e = Event(
                title=f"ARRL: {title}",
                start=start,
                end=end,
                url=ARRL_CONTEST_CAL_URL,
                source="arrl-contest"
            )
            e.add_category("contest")
            tag_modes(e)
            tag_field_day(e)
            if e.is_in_window():
                events.append(e)

    # Always add Field Day by rule (only included if it falls inside the 2-month window)
    events.extend(add_field_day_fixed())

    return events


def add_field_day_fixed() -> List[Event]:
    out: List[Event] = []
    for yr in [NOW_UTC.year, NOW_UTC.year + 1]:
        fd_start_date = fourth_full_weekend_saturday_of_june(yr)
        start = datetime(fd_start_date.year, fd_start_date.month, fd_start_date.day, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(days=2)  # Sat+Sun (simple block; contest is Sat-Sun)
        e = Event(
            title="ARRL Field Day",
            start=start,
            end=end,
            url="https://www.arrl.org/field-day",
            description="Computed as the 4th full weekend of June (Sat-Sun).",
            source="arrl-field-day"
        )
        e.add_category("field-day")
        tag_field_day(e)
        if e.is_in_window():
            out.append(e)
    return out


def fourth_full_weekend_saturday_of_june(year: int) -> date:
    d = date(year, 6, 1)
    while d.weekday() != 5:  # Saturday
        d = d.replace(day=d.day + 1)
    return d + timedelta(weeks=3)  # 4th weekend


# ---------------- Ingest: ARRL hamfests (best-effort) ----------------

HAMFEST_ROW_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(.+)")

def ingest_arrl_hamfests() -> List[Event]:
    events: List[Event] = []
    page = 1
    max_pages = 12
    cutoff_date = HORIZON_END_UTC.date()

    while page <= max_pages:
        url = ARRL_HAMFEST_PAGE_URL.format(page=page)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code == 404:
            break
        r.raise_for_status()

        text = strip_html(r.text)

        page_events = 0
        for line in text.splitlines():
            line = line.strip()
            m = HAMFEST_ROW_RE.search(line)
            if not m:
                continue

            d = datetime.strptime(m.group(1), "%m/%d/%Y").date()
            title = m.group(2).strip()

            start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=timezone.utc)
            end = start + timedelta(days=1)

            e = Event(
                title=f"Hamfest: {title}",
                start=start,
                end=end,
                url="https://www.arrl.org/hamfests/search",
                source="arrl-hamfest"
            )
            e.add_category("hamfest")

            if e.is_in_window():
                events.append(e)

            page_events += 1

        if page_events == 0:
            break

        if page >= 2 and any_event_date_in_text_after(text, cutoff_date):
            break

        page += 1

    return events


def any_event_date_in_text_after(text: str, cutoff: date) -> bool:
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})", text):
        d = datetime.strptime(m.group(1), "%m/%d/%Y").date()
        if d > cutoff:
            return True
    return False


# ---------------- Tagging / splitting ----------------

def tag_modes(e: Event) -> None:
    blob = (e.title + " " + (e.description or "")).upper()

    if any(k in blob for k in CW_KEYWORDS):
        e.add_category("cw")
    if any(k in blob for k in PHONE_KEYWORDS):
        e.add_category("phone")
    if any(k in blob for k in DIGITAL_KEYWORDS):
        e.add_category("digital")


def tag_field_day(e: Event) -> None:
    blob = (e.title + " " + (e.description or "")).upper()
    if any(k in blob for k in FIELD_DAY_KEYWORDS):
        e.add_category("field-day")


def split_calendars(all_events: List[Event]) -> Dict[str, List[Event]]:
    out: Dict[str, List[Event]] = {
        "all": [],
        "cw": [],
        "phone": [],
        "digital": [],
        "hamfests": [],
        "field-day": [],
    }

    for e in all_events:
        out["all"].append(e)

        if "hamfest" in e.categories:
            out["hamfests"].append(e)
        if "field-day" in e.categories:
            out["field-day"].append(e)

        if "contest" in e.categories:
            if "cw" in e.categories:
                out["cw"].append(e)
            if "phone" in e.categories:
                out["phone"].append(e)
            if "digital" in e.categories:
                out["digital"].append(e)

    return out


# ---------------- Printable monthly summary ----------------

def build_summary_html(all_events: List[Event]) -> str:
    events = sorted([e for e in all_events if e.is_in_window()], key=lambda e: e.start)

    def month_key(dt: datetime) -> str:
        return dt.astimezone(CHI_TZ).strftime("%Y-%m")

    months: Dict[str, List[Event]] = {}
    for e in events:
        months.setdefault(month_key(e.start), []).append(e)

    rows = []
    rows.append("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>HAMCAL – Monthly Summary</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; line-height: 1.35; }
    h1 { margin: 0 0 6px 0; }
    .meta { color: #444; margin-bottom: 18px; }
    .month { margin-top: 22px; }
    .event { padding: 10px 0; border-bottom: 1px solid #eee; }
    .title { font-weight: 700; }
    .when { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 0.95em; color: #222; }
    .tags { display: inline-block; margin-left: 10px; color: #444; font-size: 0.95em; }
    a { color: inherit; }
    @media print {
      a { text-decoration: none; }
      .event { break-inside: avoid; }
    }
  </style>
</head>
<body>
  <h1>HAMCAL – Monthly Summary</h1>
  <div class="meta">
    Rolling lookahead: now → next ~2 months.<br/>
    Times shown as: <strong>Zulu (UTC)</strong> | <strong>Central Time</strong> (CST/CDT auto).<br/>
    Duration shown in parentheses.
  </div>
""")

    for m in sorted(months.keys()):
        month_title = datetime.strptime(m, "%Y-%m").strftime("%B %Y")
        rows.append(f'<div class="month"><h2>{html.escape(month_title)}</h2>')

        for e in months[m]:
            tags = ", ".join(e.categories) if e.categories else ""
            start_s = fmt_dual(e.start)
            end_s = fmt_dual(e.end)
            dur_s = fmt_duration(e.start, e.end)

            link = e.url or ""
            title_html = html.escape(e.title)
            if link:
                title_html = f'<a href="{html.escape(link)}">{title_html}</a>'

            rows.append('<div class="event">')
            rows.append(f'  <div class="title">{title_html}</div>')
            rows.append(
                f'  <div class="when">{html.escape(start_s)} → {html.escape(end_s)} '
                f'({html.escape(dur_s)})'
                + (f'<span class="tags">[{html.escape(tags)}]</span>' if tags else '')
                + '</div>'
            )
            rows.append('</div>')

        rows.append("</div>")

    rows.append("""
</body>
</html>
""")
    return "\n".join(rows)


# ---------------- Subscribe page ----------------

def build_index_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>HAMCAL – Subscribe</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; line-height: 1.4; }
    .box { border: 1px solid #ddd; border-radius: 10px; padding: 16px; max-width: 760px; }
    h1 { margin-top: 0; }
    .row { display: flex; gap: 12px; align-items: center; margin: 10px 0; }
    code { padding: 2px 6px; background: #f6f6f6; border-radius: 6px; }
    .url { display:none; margin-left: 28px; }
    .note { color: #444; font-size: 0.95em; }
  </style>
</head>
<body>
  <div class="box">
    <h1>HAMCAL</h1>
    <p class="note">
      Subscribe to one or more calendars below, then set notifications inside your calendar app (Google/Apple/Outlook).
    </p>

    <p><strong>Printable:</strong> <a href="./summary.html">Monthly Summary (UTC + Central + Duration)</a></p>

    <div class="row">
      <input type="checkbox" id="all" data-target="u-all" />
      <label for="all"><strong>All events</strong> (contests + hamfests + Field Day)</label>
    </div>
    <div id="u-all" class="url">
      <div><code>all.ics</code> — <a href="./all.ics">open</a></div>
    </div>

    <div class="row">
      <input type="checkbox" id="cw" data-target="u-cw" />
      <label for="cw"><strong>CW contests</strong></label>
    </div>
    <div id="u-cw" class="url">
      <div><code>cw.ics</code> — <a href="./cw.ics">open</a></div>
    </div>

    <div class="row">
      <input type="checkbox" id="phone" data-target="u-phone" />
      <label for="phone"><strong>Phone contests</strong> (SSB/AM/FM)</label>
    </div>
    <div id="u-phone" class="url">
      <div><code>phone.ics</code> — <a href="./phone.ics">open</a></div>
    </div>

    <div class="row">
      <input type="checkbox" id="digital" data-target="u-digital" />
      <label for="digital"><strong>Digital contests</strong> (RTTY/FT8/etc)</label>
    </div>
    <div id="u-digital" class="url">
      <div><code>digital.ics</code> — <a href="./digital.ics">open</a></div>
    </div>

    <div class="row">
      <input type="checkbox" id="hamfests" data-target="u-hamfests" />
      <label for="hamfests"><strong>Hamfests</strong></label>
    </div>
    <div id="u-hamfests" class="url">
      <div><code>hamfests.ics</code> — <a href="./hamfests.ics">open</a></div>
    </div>

    <div class="row">
      <input type="checkbox" id="fieldday" data-target="u-fieldday" />
      <label for="fieldday"><strong>Field Day</strong></label>
    </div>
    <div id="u-fieldday" class="url">
      <div><code>field-day.ics</code> — <a href="./field-day.ics">open</a></div>
    </div>

    <hr />
    <p class="note">
      Notes: rolling ~2-month lookahead. Times in the summary show both UTC (Zulu) and Central (CST/CDT auto).
    </p>
  </div>

<script>
  for (const cb of document.querySelectorAll('input[type="checkbox"][data-target]')) {
    cb.addEventListener('change', () => {
      const t = document.getElementById(cb.dataset.target);
      if (t) t.style.display = cb.checked ? 'block' : 'none';
    });
  }
</script>
</body>
</html>
"""


# ---------------- Utilities ----------------

def strip_html(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", h)
    h = re.sub(r"(?s)<br\\s*/?>", "\\n", h)
    h = re.sub(r"(?s)</p>", "\\n", h)
    h = re.sub(r"(?s)<.*?>", "", h)
    return html.unescape(h)


def ensure_out_dir() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)


def write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


# ---------------- main ----------------

def main() -> int:
    ensure_out_dir()

    all_events: List[Event] = []

    # 1) WA7BNM contests (Google ICS)
    try:
        wa = ingest_wa7bnm_gcal()
        all_events.extend(wa)
        print(f"[ok] WA7BNM events: {len(wa)}")
    except Exception as ex:
        print(f"[warn] WA7BNM ingest failed: {ex}", file=sys.stderr)

    # 2) ARRL contests (best-effort)
    try:
        arrl = ingest_arrl_contests()
        all_events.extend(arrl)
        print(f"[ok] ARRL contest events: {len(arrl)}")
    except Exception as ex:
        print(f"[warn] ARRL contest ingest failed: {ex}", file=sys.stderr)

    # 3) ARRL hamfests
    try:
        hf = ingest_arrl_hamfests()
        all_events.extend(hf)
        print(f"[ok] ARRL hamfest events: {len(hf)}")
    except Exception as ex:
        print(f"[warn] ARRL hamfest ingest failed: {ex}", file=sys.stderr)

    # De-dupe
    dedup: Dict[Tuple[str, str, str], Event] = {}
    for e in all_events:
        key = (e.title, e.start.isoformat(), e.source)
        dedup[key] = e
    all_events = list(dedup.values())

    cals = split_calendars(all_events)

    write_file(os.path.join(OUT_DIR, "all.ics"), build_ics("HAMCAL – All", cals["all"]))
    write_file(os.path.join(OUT_DIR, "cw.ics"), build_ics("HAMCAL – CW Contests", cals["cw"]))
    write_file(os.path.join(OUT_DIR, "phone.ics"), build_ics("HAMCAL – Phone Contests", cals["phone"]))
    write_file(os.path.join(OUT_DIR, "digital.ics"), build_ics("HAMCAL – Digital Contests", cals["digital"]))
    write_file(os.path.join(OUT_DIR, "hamfests.ics"), build_ics("HAMCAL – Hamfests", cals["hamfests"]))
    write_file(os.path.join(OUT_DIR, "field-day.ics"), build_ics("HAMCAL – Field Day", cals["field-day"]))

    # NEW: printable monthly summary with UTC + Central + duration
    write_file(os.path.join(OUT_DIR, "summary.html"), build_summary_html(all_events))

    # Subscribe page (links + checkboxes)
    write_file(os.path.join(OUT_DIR, "index.html"), build_index_page())

    print("[done] wrote calendars + summary to ./docs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
