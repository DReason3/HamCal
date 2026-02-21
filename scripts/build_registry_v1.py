#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from hamcal_infra.registry import read_staging_ndjson, read_canonical_ndjson, write_canonical_ndjson
from hamcal_infra.merge import create_new_canonical, merge_into_canonical
from hamcal_infra.ulid import ulid_monotonic
from hamcal_infra.types import HamCalEventV1, StagedEventV1, norm_name_key
from hamcal_infra.link_policy import apply_primary_link


DEFAULT_TRUST_BY_SOURCE = {
    "wa7bnm_gcal": 75,
}


def parse_isoz(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def time_overlap_ratio(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    latest_start = max(a_start, b_start)
    earliest_end = min(a_end, b_end)
    overlap = (earliest_end - latest_start).total_seconds()
    if overlap <= 0:
        return 0.0
    a_dur = max((a_end - a_start).total_seconds(), 1.0)
    b_dur = max((b_end - b_start).total_seconds(), 1.0)
    return overlap / min(a_dur, b_dur)


def rebuild_indexes(canonical: List[HamCalEventV1]) -> Tuple[Dict[Tuple[str, str], int], Dict[str, int]]:
    idx_ext: Dict[Tuple[str, str], int] = {}
    idx_fp: Dict[str, int] = {}
    for i, ev in enumerate(canonical):
        for ext in ev.external_ids:
            idx_ext[tuple(ext)] = i
        if ev.fingerprints and ev.fingerprints.primary:
            idx_fp[ev.fingerprints.primary] = i
    return idx_ext, idx_fp


def match_event(
    staged: StagedEventV1,
    canonical: List[HamCalEventV1],
    idx_ext: Dict[Tuple[str, str], int],
    idx_fp: Dict[str, int],
) -> Optional[int]:
    key = (staged.source, staged.source_uid)
    if key in idx_ext:
        return idx_ext[key]

    fp = staged.primary_fingerprint()
    if fp in idx_fp:
        return idx_fp[fp]

    # fallback: strict name_key equality + >=60% overlap
    s_name = norm_name_key(staged.name)
    try:
        s_start = parse_isoz(staged.start_utc)
        s_end = parse_isoz(staged.end_utc)
    except Exception:
        return None

    best_i = None
    best_score = 0.0
    for i, ev in enumerate(canonical):
        if norm_name_key(ev.name) != s_name:
            continue
        try:
            e_start = parse_isoz(ev.start_utc)
            e_end = parse_isoz(ev.end_utc)
        except Exception:
            continue
        overlap = time_overlap_ratio(s_start, s_end, e_start, e_end)
        if overlap >= 0.60 and overlap > best_score:
            best_score = overlap
            best_i = i

    return best_i


def main() -> None:
    staging_path = Path("data/staging/wa7bnm_gcal.ndjson")
    canonical_path = Path("data/canonical/events.ndjson")

    staged = read_staging_ndjson(staging_path)
    if not staged:
        raise SystemExit(f"No staged events found at {staging_path}. Run staging first.")

    canonical = read_canonical_ndjson(canonical_path)
    idx_ext, idx_fp = rebuild_indexes(canonical)

    created = 0
    updated = 0

    staged_sorted = sorted(staged, key=lambda s: (s.start_utc, s.name, s.source_uid))

    for st in staged_sorted:
        trust = DEFAULT_TRUST_BY_SOURCE.get(st.source, 50)

        mi = match_event(st, canonical, idx_ext, idx_fp)
        if mi is None:
            ev = create_new_canonical(ulid_monotonic(), st, trust)
            ev = apply_primary_link(ev)
            canonical.append(ev)
            created += 1
            idx_ext, idx_fp = rebuild_indexes(canonical)
        else:
            ev0 = canonical[mi]
            ev1 = merge_into_canonical(ev0, st, trust)
            ev1 = apply_primary_link(ev1)
            canonical[mi] = ev1
            updated += 1
            idx_ext, idx_fp = rebuild_indexes(canonical)

    # Ensure every event has primary_link set
    canonical = [apply_primary_link(ev) for ev in canonical]

    write_canonical_ndjson(canonical_path, canonical)

    print(f"Read staged: {len(staged)} from {staging_path}")
    print(f"Canonical out: {len(canonical)} to {canonical_path}")
    print(f"Created: {created}  Updated: {updated}")
    print("Sample (first 10):")
    for i, ev in enumerate(sorted(canonical, key=lambda e: (e.start_utc, e.name))[:10]):
        print(f"{i+1}. {ev.start_utc} :: {ev.name} :: {ev.primary_link or '(no link)'}")


if __name__ == "__main__":
    main()
