from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .types import HamCalEventV1, LinkV1

# Domain classification buckets
# - originator: contest sponsor / official rules domain
# - authority: recognized org authority (ARRL/RSGB/DARC/etc.)
# - directory: aggregators or transport feeds (contestcalendar.com, google calendar)
# - unknown: everything else

DIRECTORY_DOMAINS = {
    "contestcalendar.com",
    "www.contestcalendar.com",
    "calendar.google.com",
    "www.google.com",
    "google.com",
}

AUTHORITY_DOMAINS = {
    "arrl.org",
    "www.arrl.org",
    "rsgbcc.org",
    "www.rsgbcc.org",
    "darc.de",
    "www.darc.de",
    "iaru.org",
    "www.iaru.org",
}

# rel ranking: higher is better for “primary click”
REL_SCORE = {
    "rules": 100,
    "sponsor": 90,
    "announcement": 80,
    "log-upload": 70,
    "results": 60,
    "info": 50,
    "other": 10,
}

AUTHORITY_BONUS = {
    "originator": 30,
    "authority": 15,
    "directory": 0,
    "unknown": 0,
}


def _netloc(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def classify_url_authority(url: str, rel: str) -> str:
    """
    Heuristic:
    - If domain is explicitly directory -> directory
    - If domain is explicitly authority -> authority
    - If rel is rules/sponsor/announcement/log-upload and not directory -> originator
    - Else unknown
    """
    host = _netloc(url)

    if host in DIRECTORY_DOMAINS:
        return "directory"
    if host in AUTHORITY_DOMAINS:
        return "authority"

    rel = (rel or "info").lower()
    if rel in ("rules", "sponsor", "announcement", "log-upload"):
        return "originator"

    return "unknown"


def score_link(link: LinkV1) -> int:
    rel = (link.rel or "info").lower()
    base = REL_SCORE.get(rel, 10)
    auth = (link.authority or "unknown").lower()
    bonus = AUTHORITY_BONUS.get(auth, 0)
    return base + bonus


def normalize_link_authorities(links: List[LinkV1]) -> List[LinkV1]:
    out: List[LinkV1] = []
    for l in links or []:
        auth = l.authority or classify_url_authority(l.url, l.rel)
        out.append(replace(l, authority=auth))
    return out


def select_primary_link(links: List[LinkV1]) -> Optional[str]:
    if not links:
        return None
    best = None
    best_score = -1
    for l in links:
        s = score_link(l)
        if s > best_score:
            best = l
            best_score = s
    return best.url if best else None


def apply_primary_link(event: HamCalEventV1) -> HamCalEventV1:
    links = normalize_link_authorities(event.links)
    primary = select_primary_link(links)
    return replace(event, links=links, primary_link=primary)
