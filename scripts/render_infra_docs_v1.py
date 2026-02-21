#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from hamcal_infra.registry import read_canonical_ndjson

def main() -> None:
    canonical_path = Path("data/canonical/events.ndjson")
    events = read_canonical_ndjson(canonical_path)
    if not events:
        raise SystemExit("No canonical events found. Run build_registry_v1.py first.")

    # Build a lightweight JSON view for the UI (safe for static hosting)
    out: List[Dict[str, Any]] = []
    for e in events:
        out.append({
            "hamcal_id": e.hamcal_id,
            "type": e.type,
            "name": e.name,
            "start_utc": e.start_utc,
            "end_utc": e.end_utc,
            "status": e.status,
            "primary_link": e.primary_link,
            "modes": e.modes,
            "bands": e.bands,
            "exchange": e.exchange,
            "scoring": e.scoring,
            "geo_scope": e.geo_scope,
            "notes": e.notes,
            "links": [
                {"rel": l.rel, "url": l.url, "title": l.title, "authority": l.authority}
                for l in (e.links or [])
            ],
        })

    out_path = Path("docs/api/infra_events.v1.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {out_path} ({len(out)} events)")

if __name__ == "__main__":
    main()
