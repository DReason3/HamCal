#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from hamcal_infra.registry import read_canonical_ndjson, write_canonical_ndjson
from hamcal_infra.types import HamCalEventV1, LinkV1
from hamcal_infra.link_policy import apply_primary_link


# ----------------------------
# Tiny YAML subset parser (purpose-built)
# Supports ONLY:
# - comments (# ...)
# - root key "rules:"
# - list items under rules:
#     - match: "..."
#       mode: "contains"
#       rel: "rules"
#       url: "https://..."
#       authority: "originator"
#       title: "..."
#       stop: true|false
#
# No nested maps beyond a single list of dicts.
# ----------------------------

def _strip_comment(line: str) -> str:
    if "#" in line:
        # allow URLs with # ? rare; we keep it simple: strip if leading spaces then #
        m = re.match(r'^(\s*)#', line)
        if m:
            return ""
        # Otherwise: strip inline comments only if preceded by whitespace
        line = re.sub(r"\s+#.*$", "", line)
    return line.rstrip("\n")


def _unquote(v: str) -> str:
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
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

        # list item start
        m_item = re.match(r"^\s*-\s+(\w+)\s*:\s*(.+)\s*$", line)
        if m_item:
            if current:
                rules.append(current)
            current = {}
            k = m_item.group(1)
            v = _unquote(m_item.group(2))
            current[k] = _coerce(v)
            continue

        # key: value under current item
        m_kv = re.match(r"^\s+(\w+)\s*:\s*(.+)\s*$", line)
        if m_kv and current is not None:
            k = m_kv.group(1)
            v = _unquote(m_kv.group(2))
            current[k] = _coerce(v)
            continue

        # if we get here, it's unsupported syntax
        raise ValueError(f"Unsupported YAML syntax line: {raw}")

    if current:
        rules.append(current)

    # defaults
    for r in rules:
        r.setdefault("mode", "contains")
        r.setdefault("rel", "rules")
        r.setdefault("authority", "originator")
        r.setdefault("stop", False)

    return rules


def _coerce(v: str) -> Any:
    vv = v.strip().lower()
    if vv == "true":
        return True
    if vv == "false":
        return False
    return v


def event_matches(rule: Dict[str, Any], ev: HamCalEventV1) -> bool:
    mode = str(rule.get("mode", "contains")).lower()
    needle = str(rule.get("match", "")).strip()
    if not needle:
        return False
    hay = (ev.name or "").lower()

    if mode == "contains":
        return needle.lower() in hay

    # v1: only contains
    return False


def upsert_link(ev: HamCalEventV1, rel: str, url: str, authority: str, title: Optional[str]) -> HamCalEventV1:
    rel = (rel or "info").lower()
    url = url.strip()
    authority = (authority or "unknown").lower()

    links = list(ev.links or [])

    # If exact URL already exists, just upgrade rel/authority/title if needed.
    for i, l in enumerate(links):
        if l.url == url:
            # Only upgrade (never downgrade) authority: originator > authority > unknown > directory
            order = {"originator": 3, "authority": 2, "unknown": 1, "directory": 0}
            cur = (l.authority or "unknown").lower()
            new = authority
            best_auth = cur
            if order.get(new, 0) > order.get(cur, 0):
                best_auth = new

            # Prefer better rel if current rel is weaker
            rel_score = {"rules": 6, "sponsor": 5, "announcement": 4, "log-upload": 3, "results": 2, "info": 1, "other": 0}
            best_rel = l.rel
            if rel_score.get(rel, 0) > rel_score.get(l.rel, 0):
                best_rel = rel  # type: ignore

            best_title = l.title or title

            links[i] = replace(l, rel=best_rel, authority=best_auth, title=best_title)
            return replace(ev, links=links)

    # Otherwise add new link
    links.append(LinkV1(rel=rel, url=url, authority=authority, title=title))
    return replace(ev, links=links)


def apply_rules(ev: HamCalEventV1, rules: List[Dict[str, Any]]) -> HamCalEventV1:
    changed = False
    out = ev

    for r in rules:
        if not event_matches(r, out):
            continue

        rel = str(r.get("rel", "rules"))
        url = str(r.get("url", "")).strip()
        if not url:
            continue

        authority = str(r.get("authority", "originator"))
        title = r.get("title")
        title_s = str(title) if title is not None else None

        before_links = len(out.links or [])
        out = upsert_link(out, rel=rel, url=url, authority=authority, title=title_s)
        after_links = len(out.links or [])
        if after_links != before_links:
            changed = True
        else:
            # could have upgraded
            changed = True

        if bool(r.get("stop", False)):
            break

    if changed:
        out = apply_primary_link(out)

    return out


def main() -> None:
    map_path = Path("data/enrichment/origin_links.v1.yaml")
    canonical_path = Path("data/canonical/events.ndjson")

    rules = load_rules_yaml(map_path)
    events = read_canonical_ndjson(canonical_path)
    if not events:
        raise SystemExit("No canonical events found. Run build_registry_v1.py first.")

    updated = 0
    sample_hits: List[str] = []

    out_events: List[HamCalEventV1] = []
    for ev in events:
        ev2 = apply_rules(ev, rules)
        if ev2.primary_link != ev.primary_link or (ev2.links != ev.links):
            updated += 1
            if len(sample_hits) < 10:
                sample_hits.append(f"{ev.name} -> {ev2.primary_link}")
        out_events.append(ev2)

    write_canonical_ndjson(canonical_path, out_events)

    print(f"Loaded rules: {len(rules)} from {map_path}")
    print(f"Canonical events: {len(events)}")
    print(f"Events updated by enrichment: {updated}")
    if sample_hits:
        print("Sample upgrades:")
        for s in sample_hits:
            print(" - " + s)


if __name__ == "__main__":
    main()
