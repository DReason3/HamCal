from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal, Tuple
import hashlib
import json
import re


EventType = Literal["contest", "hamfest", "club", "activation", "field_day", "other"]
EventStatus = Literal["scheduled", "tentative", "cancelled"]
GeoScope = Literal["worldwide", "region", "country", "state", "local", "unknown"]

LinkRel = Literal["rules", "sponsor", "log-upload", "announcement", "results", "info", "other"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(s: str) -> str:
    h = hashlib.sha256()
    h.update(s.encode("utf-8", errors="replace"))
    return h.hexdigest()


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def norm_name_key(name: str) -> str:
    """
    Name normalization for matching.
    Keep it conservative; don't destroy meaning.
    """
    s = norm_space(name).lower()
    s = re.sub(r"[^\w\s\-]+", "", s)  # drop punctuation except hyphen
    s = re.sub(r"\b(the|a|an)\b", "", s)
    s = norm_space(s)
    return s


def clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


@dataclass
class LinkV1:
    rel: LinkRel
    url: str
    title: Optional[str] = None


@dataclass
class SponsorV1:
    name: Optional[str] = None
    callsign: Optional[str] = None
    org: Optional[str] = None


@dataclass
class SourceRecordV1:
    source: str
    source_uid: str
    first_seen_utc: str
    last_seen_utc: str
    raw_hash: str
    fields: Dict[str, Any] = field(default_factory=dict)
    trust: int = 50
    raw_excerpt: Optional[str] = None


@dataclass
class QualityV1:
    confidence: float = 0.0
    completeness: float = 0.0


@dataclass
class FingerprintsV1:
    primary: str
    alternates: List[str] = field(default_factory=list)


@dataclass
class StagedEventV1:
    source: str
    source_uid: str
    name: str
    start_utc: str
    end_utc: str
    status: EventStatus
    raw_hash: str
    raw_excerpt: str
    observed_utc: str

    type: EventType = "contest"
    timezone_hint: Optional[str] = None
    sponsor: Optional[SponsorV1] = None
    modes: List[str] = field(default_factory=list)
    bands: List[str] = field(default_factory=list)
    exchange: Optional[str] = None
    scoring: Optional[str] = None
    geo_scope: GeoScope = "unknown"
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    links: List[LinkV1] = field(default_factory=list)

    def name_key(self) -> str:
        return norm_name_key(self.name)

    def primary_fingerprint(self) -> str:
        """
        v1 fingerprint: name_key + start date (YYYY-MM-DD) + duration bucket.
        """
        start_date = self.start_utc[:10]
        dur_bucket = duration_bucket_minutes(self.start_utc, self.end_utc)
        base = f"{self.name_key()}|{start_date}|{dur_bucket}"
        return sha256_text(base)


@dataclass
class HamCalEventV1:
    hamcal_id: str
    type: EventType
    name: str
    start_utc: str
    end_utc: str
    status: EventStatus

    timezone_hint: Optional[str] = None
    sponsor: Optional[SponsorV1] = None
    modes: List[str] = field(default_factory=list)
    bands: List[str] = field(default_factory=list)
    exchange: Optional[str] = None
    scoring: Optional[str] = None
    geo_scope: GeoScope = "unknown"
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    links: List[LinkV1] = field(default_factory=list)

    quality: QualityV1 = field(default_factory=QualityV1)
    fingerprints: Optional[FingerprintsV1] = None
    external_ids: List[Tuple[str, str]] = field(default_factory=list)  # (source, source_uid)
    sources: List[SourceRecordV1] = field(default_factory=list)

    last_modified_utc: str = field(default_factory=utc_now_iso)


def duration_bucket_minutes(start_utc: str, end_utc: str) -> str:
    """
    Buckets help matching even if slight time shifts occur:
    - short: <= 3h
    - halfday: <= 8h
    - day: <= 28h
    - weekend: <= 60h
    - long: > 60h
    """
    def parse(s: str) -> datetime:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    a = parse(start_utc)
    b = parse(end_utc)
    minutes = int((b - a).total_seconds() // 60)
    if minutes <= 180:
        return "short"
    if minutes <= 480:
        return "halfday"
    if minutes <= 1680:
        return "day"
    if minutes <= 3600:
        return "weekend"
    return "long"


def dataclass_to_json(obj: Any) -> str:
    """
    Stable JSON for NDJSON writing.
    """
    return json.dumps(asdict(obj), ensure_ascii=False, sort_keys=True)
