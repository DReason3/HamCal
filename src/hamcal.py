#!/usr/bin/env python3
"""
HAMCAL - build pre-filtered iCal (.ics) calendars for ham contests + hamfests + Field Day.

MVP:
- Rolling ~18 month lookahead
- 4 sources:
  1) WA7BNM via public Google Calendar ICS
  2) SM3CER contest calendar
  3) ARRL Contest Calendar
  4) ARRL Hamfests database
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import sys
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, date
from typing import List, Optional, Dict, Tuple

import requests
from dateutil import parser as dtparser
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

UA = "HAMCAL/0.2 (+https://github.com/dreason3/hamcal)"

NOW_UTC = datetime.now(timezone.utc)
HORIZON_END_UTC = NOW_UTC + timedelta(days=548)

CHI_TZ = ZoneInfo("America/Chicago")

WA7BNM_GCAL_ID = "9o3or51jjdsantmsqoadmm949k@group.calendar.google.com"
WA7BNM_GCAL_ICS = f"https://calendar.google.com/calendar/ical/{WA7BNM_GCAL_ID}/public/basic.ics"

ARRL_CONTEST_CAL_URL = "https://www.arrl.org/contest-calendar"
ARRL_HAMFEST_PAGE_URL = "https://www.arrl.org/hamfests/search/page:{page}/model:event"

SM3CER_URL = "https://www.sm3cer.com/contest/"

OUT_DIR = os.path.join("docs")

DIGITAL_KEYWORDS = ["RTTY","FT8","FT4","PSK","DIGI","DIGITAL","SSTV","JS8","MFSK"]
PHONE_KEYWORDS = ["SSB","PHONE","AM","FM"]
CW_KEYWORDS = ["CW"]

FIELD_DAY_KEYWORDS = ["FIELD DAY"]


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    url: Optional[str] = None
    description: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    source: str = "unknown"

    def uid(self) -> str:
        h = hashlib.sha256()
        h.update((self.source + "|" + self.title + "|" + self.start.isoformat() + "|" + (self.url or "")).encode())
        return h.hexdigest()[:32] + "@hamcal"

    def is_in_window(self) -> bool:
        return (self.end > NOW_UTC) and (self.start < HORIZON_END_UTC)

    def add_category(self, c: str):
        if c not in self.categories:
            self.categories.append(c)


# ---------------- JSON export ----------------

def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def export_all_json(all_events: List["Event"], out_path: str):

    payload = []

    for e in all_events:

        mode = ""
        if "cw" in e.categories:
            mode="CW"
        elif "phone" in e.categories:
            mode="PHONE"
        elif "digital" in e.categories:
            mode="DIGITAL"

        payload.append({
            "uid": e.uid(),
            "summary": e.title,
            "description": e.description or "",
            "url": e.url or "",
            "categories": e.categories,
            "mode": mode,
            "start_utc": _iso_z(e.start),
            "end_utc": _iso_z(e.end),
            "source": e.source
        })

    os.makedirs(os.path.dirname(out_path) or ".",exist_ok=True)

    with open(out_path,"w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,indent=2)


# ---------------- ICS helpers ----------------

def ics_escape(text:str)->str:
    return text.replace("\\","\\\\").replace("\n","\\n").replace(",","\\,").replace(";","\\;")

def dt_to_ics(dt:datetime)->str:
    dt=dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")

def build_ics(calendar_name:str,events:List[Event])->str:

    lines=[]

    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//HAMCAL//hamcal//EN")
    lines.append("CALSCALE:GREGORIAN")
    lines.append(f"X-WR-CALNAME:{ics_escape(calendar_name)}")
    lines.append("X-WR-TIMEZONE:UTC")

    for e in sorted(events,key=lambda e:e.start):

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{e.uid()}")
        lines.append(f"DTSTAMP:{dt_to_ics(NOW_UTC)}")
        lines.append(f"DTSTART:{dt_to_ics(e.start)}")
        lines.append(f"DTEND:{dt_to_ics(e.end)}")
        lines.append(f"SUMMARY:{ics_escape(e.title)}")

        if e.url:
            lines.append(f"URL:{ics_escape(e.url)}")

        if e.description:
            lines.append(f"DESCRIPTION:{ics_escape(e.description)}")

        if e.categories:
            lines.append(f"CATEGORIES:{','.join(e.categories)}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    return "\r\n".join(lines)+"\r\n"


# ---------------- WA7BNM ----------------

def parse_google_ics_datetime(value:str)->datetime:

    value=value.strip()

    if re.fullmatch(r"\d{8}",value):
        d=datetime.strptime(value,"%Y%m%d").date()
        return datetime(d.year,d.month,d.day,tzinfo=timezone.utc)

    dt=dtparser.parse(value)

    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def ingest_wa7bnm_gcal()->List[Event]:

    r=requests.get(WA7BNM_GCAL_ICS,headers={"User-Agent":UA},timeout=30)
    r.raise_for_status()

    text=r.text

    events=[]

    blocks=text.split("BEGIN:VEVENT")

    for b in blocks[1:]:

        vevent="BEGIN:VEVENT"+b

        dtstart=extract_ics_field(vevent,"DTSTART")
        dtend=extract_ics_field(vevent,"DTEND")
        summary=extract_ics_field(vevent,"SUMMARY") or "Contest"
        url=extract_ics_field(vevent,"URL")
        desc=extract_ics_field(vevent,"DESCRIPTION")

        if not dtstart:
            continue

        start=parse_google_ics_datetime(dtstart)
        end=parse_google_ics_datetime(dtend) if dtend else start+timedelta(hours=1)

        e=Event(
            title=summary,
            start=start,
            end=end,
            url=url,
            description=desc,
            source="wa7bnm-gcal"
        )

        e.add_category("contest")

        tag_modes(e)
        tag_field_day(e)

        if e.is_in_window():
            events.append(e)

    return events


def extract_ics_field(vevent:str,field:str):

    m=re.search(rf"{field}.*:(.*)",vevent)

    if not m:
        return None

    return m.group(1).strip()


# ---------------- SM3CER ----------------

def ingest_sm3cer_contests()->List[Event]:

    events=[]

    try:

        r=requests.get(SM3CER_URL,headers={"User-Agent":UA},timeout=30)
        r.raise_for_status()

        soup=BeautifulSoup(r.text,"html.parser")

        rows=soup.select("table tr")

        for tr in rows:

            cols=tr.find_all("td")

            if len(cols)<2:
                continue

            date_txt=cols[0].get_text(strip=True)
            title=cols[1].get_text(strip=True)

            if not date_txt or not title:
                continue

            try:
                start=dtparser.parse(date_txt)
            except:
                continue

            if start.tzinfo is None:
                start=start.replace(tzinfo=timezone.utc)

            end=start+timedelta(hours=48)

            e=Event(
                title=title,
                start=start,
                end=end,
                url=SM3CER_URL,
                source="sm3cer"
            )

            e.add_category("contest")

            tag_modes(e)

            if e.is_in_window():
                events.append(e)

    except Exception as ex:

        print(f"[warn] SM3CER ingest failed: {ex}",file=sys.stderr)

    return events


# ---------------- ARRL contest calendar ----------------

def ingest_arrl_contests()->List[Event]:

    r=requests.get(ARRL_CONTEST_CAL_URL,headers={"User-Agent":UA},timeout=30)
    r.raise_for_status()

    text=strip_html(r.text)

    events=[]

    for line in text.splitlines():

        m=re.search(r"\b(\d{4}-\d{2}-\d{2})\b",line)

        if not m:
            continue

        d=datetime.strptime(m.group(1),"%Y-%m-%d").date()

        start=datetime(d.year,d.month,d.day,tzinfo=timezone.utc)
        end=start+timedelta(days=1)

        e=Event(
            title=line.strip(),
            start=start,
            end=end,
            url=ARRL_CONTEST_CAL_URL,
            source="arrl-contest"
        )

        e.add_category("contest")

        tag_modes(e)

        if e.is_in_window():
            events.append(e)

    events.extend(add_field_day_fixed())

    return events


# ---------------- Field Day rule ----------------

def add_field_day_fixed():

    out=[]

    for yr in [NOW_UTC.year,NOW_UTC.year+1]:

        d=fourth_full_weekend_saturday_of_june(yr)

        start=datetime(d.year,d.month,d.day,tzinfo=timezone.utc)
        end=start+timedelta(days=2)

        e=Event(
            title="ARRL Field Day",
            start=start,
            end=end,
            url="https://www.arrl.org/field-day",
            source="arrl-field-day"
        )

        e.add_category("field-day")

        out.append(e)

    return out


def fourth_full_weekend_saturday_of_june(year):

    d=date(year,6,1)

    while d.weekday()!=5:
        d+=timedelta(days=1)

    return d+timedelta(weeks=3)


# ---------------- hamfests ----------------

def ingest_arrl_hamfests():

    events=[]

    page=1

    while page<=12:

        url=ARRL_HAMFEST_PAGE_URL.format(page=page)

        r=requests.get(url,headers={"User-Agent":UA},timeout=30)

        if r.status_code==404:
            break

        r.raise_for_status()

        text=strip_html(r.text)

        for m in re.finditer(r"(\d{2}/\d{2}/\d{4})\s*-\s*(.+)",text):

            d=datetime.strptime(m.group(1),"%m/%d/%Y").date()

            start=datetime(d.year,d.month,d.day,tzinfo=timezone.utc)
            end=start+timedelta(days=1)

            e=Event(
                title=m.group(2),
                start=start,
                end=end,
                url="https://www.arrl.org/hamfests/search",
                source="arrl-hamfest"
            )

            e.add_category("hamfest")

            if e.is_in_window():
                events.append(e)

        page+=1

    return events


# ---------------- tagging ----------------

def tag_modes(e:Event):

    blob=(e.title+" "+(e.description or "")).upper()

    if any(k in blob for k in CW_KEYWORDS):
        e.add_category("cw")

    if any(k in blob for k in PHONE_KEYWORDS):
        e.add_category("phone")

    if any(k in blob for k in DIGITAL_KEYWORDS):
        e.add_category("digital")


def tag_field_day(e:Event):

    blob=(e.title+" "+(e.description or "")).upper()

    if any(k in blob for k in FIELD_DAY_KEYWORDS):
        e.add_category("field-day")


# ---------------- utilities ----------------

def strip_html(h):

    h=re.sub(r"(?is)<(script|style).*?>.*?</\\1>","",h)
    h=re.sub(r"<br\\s*/?>","\n",h)
    h=re.sub(r"</p>","\n",h)
    h=re.sub(r"<.*?>","",h)

    return html.unescape(h)


def ensure_out_dir():
    os.makedirs(OUT_DIR,exist_ok=True)


def write_file(path,content):

    with open(path,"w",encoding="utf-8",newline="") as f:
        f.write(content)


# ---------------- main ----------------

def main():

    ensure_out_dir()

    all_events=[]

    try:
        wa=ingest_wa7bnm_gcal()
        all_events.extend(wa)
        print(f"[ok] WA7BNM events: {len(wa)}")
    except Exception as ex:
        print(f"[warn] WA7BNM ingest failed: {ex}",file=sys.stderr)

    try:
        sm3=ingest_sm3cer_contests()
        all_events.extend(sm3)
        print(f"[ok] SM3CER events: {len(sm3)}")
    except Exception as ex:
        print(f"[warn] SM3CER ingest failed: {ex}",file=sys.stderr)

    try:
        arrl=ingest_arrl_contests()
        all_events.extend(arrl)
        print(f"[ok] ARRL contest events: {len(arrl)}")
    except Exception as ex:
        print(f"[warn] ARRL contest ingest failed: {ex}",file=sys.stderr)

    try:
        hf=ingest_arrl_hamfests()
        all_events.extend(hf)
        print(f"[ok] ARRL hamfest events: {len(hf)}")
    except Exception as ex:
        print(f"[warn] ARRL hamfest ingest failed: {ex}",file=sys.stderr)

    dedup={}

    for e in all_events:
        key=(e.title,e.start.isoformat(),e.source)
        dedup[key]=e

    all_events=list(dedup.values())

    write_file(os.path.join(OUT_DIR,"all.ics"),build_ics("HAMCAL – All",all_events))
    export_all_json(all_events,os.path.join(OUT_DIR,"all.json"))

    print("[done] wrote calendars + json to ./docs/")

    return 0


if __name__=="__main__":
    raise SystemExit(main())
