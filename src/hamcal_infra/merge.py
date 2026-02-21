from __future__ import annotations

from dataclasses import replace
from typing import List
from .types import (
    HamCalEventV1,
    StagedEventV1,
    SourceRecordV1,
    QualityV1,
    FingerprintsV1,
    utc_now_iso,
    sha256_text,
    norm_name_key,
    clamp01,
)


def compute_quality(event: HamCalEventV1) -> QualityV1:
    max_trust = 0
    for s in event.sources:
        if s.trust > max_trust:
            max_trust = s.trust

    confidence = clamp01(max_trust / 100.0)

    fields_total = 6
    present = 0
    if event.sponsor and (event.sponsor.name or event.sponsor.callsign or event.sponsor.org):
        present += 1
    if event.modes:
        present += 1
    if event.bands:
        present += 1
    if event.exchange:
        present += 1
    if any(l.rel in ("rules", "sponsor") for l in event.links):
        present += 1
    if event.geo_scope and event.geo_scope != "unknown":
        present += 1

    completeness = present / fields_total
    return QualityV1(confidence=confidence, completeness=clamp01(completeness))


def stage_to_source_record(st: StagedEventV1, trust_default: int) -> SourceRecordV1:
    return SourceRecordV1(
        source=st.source,
        source_uid=st.source_uid,
        first_seen_utc=st.observed_utc,
        last_seen_utc=st.observed_utc,
        raw_hash=st.raw_hash,
        raw_excerpt=st.raw_excerpt[:500],
        fields={
            "name": True,
            "start_utc": True,
            "end_utc": True,
            "status": True,
            "type": True,
            "modes": bool(st.modes),
            "bands": bool(st.bands),
            "links": bool(st.links),
            "exchange": bool(st.exchange),
            "scoring": bool(st.scoring),
            "sponsor": bool(st.sponsor),
            "geo_scope": (st.geo_scope != "unknown"),
        },
        trust=trust_default,
    )


def better_value(existing_val, existing_trust: int, new_val, new_trust: int):
    empty_existing = existing_val is None or existing_val == "" or existing_val == []
    empty_new = new_val is None or new_val == "" or new_val == []

    if empty_new:
        return existing_val
    if empty_existing:
        return new_val
    if new_trust > existing_trust:
        return new_val
    return existing_val


def union_list(a: List[str], b: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in (a or []) + (b or []):
        if not x:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def union_links(a, b):
    out = []
    seen = set()
    for link in (a or []) + (b or []):
        key = (link.rel, link.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out


def update_or_append_source(event: HamCalEventV1, sr: SourceRecordV1) -> HamCalEventV1:
    sources = list(event.sources)
    for i, s in enumerate(sources):
        if s.source == sr.source and s.source_uid == sr.source_uid:
            sources[i] = replace(
                s,
                last_seen_utc=sr.last_seen_utc,
                raw_hash=sr.raw_hash,
                raw_excerpt=sr.raw_excerpt,
                fields=sr.fields,
                trust=max(s.trust, sr.trust),
            )
            return replace(event, sources=sources)
    sources.append(sr)
    external_ids = list(event.external_ids)
    ext = (sr.source, sr.source_uid)
    if ext not in external_ids:
        external_ids.append(ext)
    return replace(event, sources=sources, external_ids=external_ids)


def ensure_fingerprints(event: HamCalEventV1) -> HamCalEventV1:
    if event.fingerprints and event.fingerprints.primary:
        return event
    name_key = norm_name_key(event.name)
    start_date = event.start_utc[:10]
    dur = sha256_text(event.start_utc + "|" + event.end_utc)[:8]
    primary = sha256_text(f"{name_key}|{start_date}|{dur}")
    return replace(event, fingerprints=FingerprintsV1(primary=primary))


def merge_into_canonical(
    canonical: HamCalEventV1,
    staged: StagedEventV1,
    staged_trust: int,
) -> HamCalEventV1:
    existing_trust = 0
    for s in canonical.sources:
        if s.source == staged.source and s.source_uid == staged.source_uid:
            existing_trust = s.trust
            break

    name = better_value(canonical.name, existing_trust, staged.name, staged_trust)
    start_utc = better_value(canonical.start_utc, existing_trust, staged.start_utc, staged_trust)
    end_utc = better_value(canonical.end_utc, existing_trust, staged.end_utc, staged_trust)

    status = canonical.status
    if staged.status == "cancelled":
        if staged_trust >= max(60, existing_trust):
            status = "cancelled"
    else:
        status = better_value(canonical.status, existing_trust, staged.status, staged_trust)

    modes = union_list(canonical.modes, staged.modes)
    bands = union_list(canonical.bands, staged.bands)
    tags = union_list(canonical.tags, staged.tags)
    links = union_links(canonical.links, staged.links)

    sponsor = canonical.sponsor
    if staged.sponsor:
        sponsor = better_value(canonical.sponsor, existing_trust, staged.sponsor, staged_trust)

    exchange = better_value(canonical.exchange, existing_trust, staged.exchange, staged_trust)
    scoring = better_value(canonical.scoring, existing_trust, staged.scoring, staged_trust)
    geo_scope = better_value(canonical.geo_scope, existing_trust, staged.geo_scope, staged_trust)

    notes = canonical.notes
    if staged.notes and staged.notes != canonical.notes:
        add = f"[{staged.source}] {staged.notes}"
        notes = (notes + "\n" + add) if notes else add

    timezone_hint = better_value(canonical.timezone_hint, existing_trust, staged.timezone_hint, staged_trust)

    updated = replace(
        canonical,
        name=name,
        start_utc=start_utc,
        end_utc=end_utc,
        status=status,
        modes=modes,
        bands=bands,
        tags=tags,
        links=links,
        sponsor=sponsor,
        exchange=exchange,
        scoring=scoring,
        geo_scope=geo_scope,
        notes=notes,
        timezone_hint=timezone_hint,
        last_modified_utc=utc_now_iso(),
    )

    sr = stage_to_source_record(staged, staged_trust)
    updated = update_or_append_source(updated, sr)

    updated = ensure_fingerprints(updated)
    updated = replace(updated, quality=compute_quality(updated))
    return updated


def create_new_canonical(hamcal_id: str, staged: StagedEventV1, staged_trust: int) -> HamCalEventV1:
    base = HamCalEventV1(
        hamcal_id=hamcal_id,
        type=staged.type,
        name=staged.name,
        start_utc=staged.start_utc,
        end_utc=staged.end_utc,
        status=staged.status,
        timezone_hint=staged.timezone_hint,
        sponsor=staged.sponsor,
        modes=list(staged.modes),
        bands=list(staged.bands),
        exchange=staged.exchange,
        scoring=staged.scoring,
        geo_scope=staged.geo_scope,
        tags=list(staged.tags),
        notes=staged.notes,
        links=list(staged.links),
        external_ids=[(staged.source, staged.source_uid)],
        sources=[],
    )
    base = ensure_fingerprints(base)
    sr = stage_to_source_record(staged, staged_trust)
    base = update_or_append_source(base, sr)
    base = replace(base, quality=compute_quality(base))
    return base
