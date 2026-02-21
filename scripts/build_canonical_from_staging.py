#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from hamcal_infra.registry import read_staging_ndjson, write_canonical_ndjson
from hamcal_infra.merge import create_new_canonical
from hamcal_infra.ulid import ulid_monotonic


DEFAULT_TRUST_BY_SOURCE = {
    "wa7bnm_gcal": 75,
}


def main() -> None:
    staging_path = Path("data/staging/wa7bnm_gcal.ndjson")
    staged = read_staging_ndjson(staging_path)
    if not staged:
        raise SystemExit(f"No staged events found at {staging_path}. Run staging first.")

    canonical = []
    for st in staged:
        trust = DEFAULT_TRUST_BY_SOURCE.get(st.source, 50)
        hamcal_id = ulid_monotonic()
        canonical.append(create_new_canonical(hamcal_id, st, trust))

    out_path = Path("data/canonical/events.ndjson")
    write_canonical_ndjson(out_path, canonical)

    print(f"Read staged: {len(staged)} from {staging_path}")
    print(f"Wrote canonical: {len(canonical)} to {out_path}")
    for i, ev in enumerate(canonical[:10]):
        print(f"{i+1}. {ev.start_utc} -> {ev.end_utc} :: {ev.name} (hamcal_id={ev.hamcal_id})")


if __name__ == "__main__":
    main()
