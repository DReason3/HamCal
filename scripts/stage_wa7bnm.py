#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from hamcal_infra.collectors.wa7bnm_ics import WA7BNMICSCollector, SOURCE_NAME
from hamcal_infra.registry import write_staging_ndjson

def main() -> None:
    c = WA7BNMICSCollector()
    staged = c.collect()

    out_path = Path("data/staging") / f"{SOURCE_NAME}.ndjson"
    write_staging_ndjson(out_path, staged)

    print(f"Staged events: {len(staged)}")
    print(f"Wrote: {out_path}")
    for i, ev in enumerate(staged[:10]):
        print(f"{i+1}. {ev.start_utc} -> {ev.end_utc} :: {ev.name} (uid={ev.source_uid})")

if __name__ == "__main__":
    main()
