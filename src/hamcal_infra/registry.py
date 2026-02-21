from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
import json

from .types import (
    HamCalEventV1,
    StagedEventV1,
    dataclass_to_json,
    LinkV1,
    SponsorV1,
    QualityV1,
    FingerprintsV1,
    SourceRecordV1,
)


def write_canonical_ndjson(path: Path, events: List[HamCalEventV1]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(dataclass_to_json(ev))
            f.write("\n")


def write_staging_ndjson(path: Path, staged: List[StagedEventV1]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for st in staged:
            f.write(dataclass_to_json(st))
            f.write("\n")


def _link_from_dict(d: Dict[str, Any]) -> LinkV1:
    return LinkV1(
        rel=d["rel"],
        url=d["url"],
        title=d.get("title"),
        authority=d.get("authority"),
    )


def _sponsor_from_dict(d: Dict[str, Any]) -> SponsorV1:
    return SponsorV1(name=d.get("name"), callsign=d.get("callsign"), org=d.get("org"))


def _quality_from_dict(d: Dict[str, Any]) -> QualityV1:
    return QualityV1(confidence=float(d.get("confidence", 0.0)), completeness=float(d.get("completeness", 0.0)))


def _fingerprints_from_dict(d: Dict[str, Any]) -> FingerprintsV1:
    return FingerprintsV1(primary=d["primary"], alternates=list(d.get("alternates") or []))


def _source_record_from_dict(d: Dict[str, Any]) -> SourceRecordV1:
    return SourceRecordV1(
        source=d["source"],
        source_uid=d["source_uid"],
        first_seen_utc=d["first_seen_utc"],
        last_seen_utc=d["last_seen_utc"],
        raw_hash=d["raw_hash"],
        fields=dict(d.get("fields") or {}),
        trust=int(d.get("trust", 50)),
        raw_excerpt=d.get("raw_excerpt"),
    )


def read_staging_ndjson(path: Path) -> List[StagedEventV1]:
    if not path.exists():
        return []

    out: List[StagedEventV1] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)

            sponsor = None
            if isinstance(d.get("sponsor"), dict):
                sponsor = _sponsor_from_dict(d["sponsor"])

            links: List[LinkV1] = []
            for ld in (d.get("links") or []):
                if isinstance(ld, dict) and "rel" in ld and "url" in ld:
                    links.append(_link_from_dict(ld))

            out.append(
                StagedEventV1(
                    source=d["source"],
                    source_uid=d["source_uid"],
                    name=d["name"],
                    start_utc=d["start_utc"],
                    end_utc=d["end_utc"],
                    status=d["status"],
                    raw_hash=d["raw_hash"],
                    raw_excerpt=d.get("raw_excerpt", ""),
                    observed_utc=d["observed_utc"],
                    type=d.get("type", "contest"),
                    timezone_hint=d.get("timezone_hint"),
                    sponsor=sponsor,
                    modes=list(d.get("modes") or []),
                    bands=list(d.get("bands") or []),
                    exchange=d.get("exchange"),
                    scoring=d.get("scoring"),
                    geo_scope=d.get("geo_scope", "unknown"),
                    tags=list(d.get("tags") or []),
                    notes=d.get("notes"),
                    links=links,
                )
            )
    return out


def read_canonical_ndjson(path: Path) -> List[HamCalEventV1]:
    if not path.exists():
        return []

    out: List[HamCalEventV1] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)

            sponsor = None
            if isinstance(d.get("sponsor"), dict):
                sponsor = _sponsor_from_dict(d["sponsor"])

            links: List[LinkV1] = []
            for ld in (d.get("links") or []):
                if isinstance(ld, dict) and "rel" in ld and "url" in ld:
                    links.append(_link_from_dict(ld))

            quality = QualityV1()
            if isinstance(d.get("quality"), dict):
                quality = _quality_from_dict(d["quality"])

            fingerprints = None
            if isinstance(d.get("fingerprints"), dict) and d["fingerprints"].get("primary"):
                fingerprints = _fingerprints_from_dict(d["fingerprints"])

            sources: List[SourceRecordV1] = []
            for sd in (d.get("sources") or []):
                if isinstance(sd, dict) and "source" in sd and "source_uid" in sd:
                    sources.append(_source_record_from_dict(sd))

            external_ids: List[Tuple[str, str]] = []
            for pair in (d.get("external_ids") or []):
                if isinstance(pair, list) and len(pair) == 2:
                    external_ids.append((str(pair[0]), str(pair[1])))

            out.append(
                HamCalEventV1(
                    hamcal_id=d["hamcal_id"],
                    type=d["type"],
                    name=d["name"],
                    start_utc=d["start_utc"],
                    end_utc=d["end_utc"],
                    status=d["status"],
                    primary_link=d.get("primary_link"),
                    timezone_hint=d.get("timezone_hint"),
                    sponsor=sponsor,
                    modes=list(d.get("modes") or []),
                    bands=list(d.get("bands") or []),
                    exchange=d.get("exchange"),
                    scoring=d.get("scoring"),
                    geo_scope=d.get("geo_scope", "unknown"),
                    tags=list(d.get("tags") or []),
                    notes=d.get("notes"),
                    links=links,
                    quality=quality,
                    fingerprints=fingerprints,
                    external_ids=external_ids,
                    sources=sources,
                    last_modified_utc=d.get("last_modified_utc", ""),
                )
            )
    return out
