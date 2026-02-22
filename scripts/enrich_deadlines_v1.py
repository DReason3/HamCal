#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hamcal_infra.registry import read_canonical_ndjson, write_canonical_ndjson


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_comment(line: str) -> str:
    if "#" in line:
        m = re.match(r'^(\s*)#', line)
        if m:
            return ""
        line = re.sub(r"\s+#.*$", "", line)
    return line.rstrip("\n")


def _unquote(v: str) -> str:
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def _coerce(v: str) -> Any:
    vv = v.strip().lower()
    if vv == "true":
        return True
    if vv == "false":
        return False
    return v


def load_rules_yaml(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(str(path))

    lines = [_strip_comment(x) for x in path.read_text(encoding="utf-8").splitlines()]
    lines = [x for x in lines if x.strip()]

    in_rules = False
    current: Optional[Dict[str, Any]] = None
    rules: List[Dict[str, Any]] = []

    for raw in lines:
        line = raw.rstrip()

        if re.match(r"^\s*rules\s*:\s*$", line):
            in_rules = True
            continue

        if not in_rules:
            continue

        m_item = re.match(r"^\s*-\s+(\w+)\s*:\s*(.+)\s*$", line)
        if m_item:
            if current:
                rules.append(current)
            current = {}
            k = m_item.group(1)
            v = _unquote(m_item.group(2))
            current[k] = _coerce(v)
            continue

        m_kv = re.match(r"^\s+(\w+)\s*:\s*(.+)\s*$", line)
        if m_kv and current is not None:
            k = m_kv.group(1)
            v = _unquote(m_kv.group(2))
            current[k] = _coerce(v)
            continue

        raise ValueError(f"Unsupported YAML syntax line: {raw}")

    if current:
        rules.append(current)

    for r in rules:
        r.setdefault("mode", "contains")
        r.setdefault("stop", False)
        r.setdefault("source", "manual")  # v1: this file is manual by nature

    return rules


def matches(rule: Dict[str, Any], name: str) -> bool:
    mode = str(rule.get("mode", "contains")).lower()
    needle = str(rule.get("match", "")).strip().lower()
    hay = (name or "").lower()
    if not needle:
        return False
    if mode == "contains":
        return needle in hay
    return False


def main() -> None:
    map_path = Path("data/enrichment/deadlines.v1.yaml")
    canonical_path = Path("data/canonical/events.ndjson")

    rules = load_rules_yaml(map_path)
    events = read_canonical_ndjson(canonical_path)
    if not events:
        raise SystemExit("No canonical events found. Run build_registry_v1.py first.")

    updated = 0
    out = []
    now = utc_now_iso()

    for ev in events:
        new_deadline = ev.log_deadline_utc
        new_source = ev.log_deadline_source
        new_asof = ev.log_deadline_asof_utc

        for r in rules:
            if not matches(r, ev.name):
                continue

            dl = str(r.get("deadline_utc", "")).strip()
            if dl:
                new_deadline = dl
                new_source = str(r.get("source", "manual")).strip() or "manual"
                new_asof = now

            if bool(r.get("stop", False)):
                break

        if (new_deadline != ev.log_deadline_utc) or (new_source != ev.log_deadline_source) or (new_asof != ev.log_deadline_asof_utc):
            updated += 1
            out.append(replace(ev, log_deadline_utc=new_deadline, log_deadline_source=new_source, log_deadline_asof_utc=new_asof))
        else:
            out.append(ev)

    write_canonical_ndjson(canonical_path, out)

    print(f"Loaded deadline rules: {len(rules)} from {map_path}")
    print(f"Canonical events: {len(events)}")
    print(f"Events updated with deadline/provenance: {updated}")

if __name__ == "__main__":
    main()
