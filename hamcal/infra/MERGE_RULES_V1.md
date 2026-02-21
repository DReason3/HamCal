# HamCal Infrastructure — Merge Rules v1

This document defines how staged (collector) records become canonical events.

## Overview pipeline
1) Collect -> StagedEventV1 (normalized per collector)
2) Match -> find canonical HamCalEventV1 or create new
3) Merge -> field-by-field selection + provenance update
4) Emit canonical NDJSON + derived outputs

## Trust weights (default v1)
Collectors assign a trust score 0..100 on each SourceRecord:
- verified_sponsor_submission: 95
- sponsor_site: 90
- arrl_contest: 85
- wa7bnm_gcal: 75
- reputable_aggregator: 60
- unverified_user_submission: 40
- scrape_unknown: 30

Trust is used only when conflicts exist.

## Matching (dedupe) strategy v1
A staged event matches an existing canonical event if ANY rule hits:

### Rule 1 — External ID match (strong)
If (source, source_uid) exists in canonical.external_ids => match.

### Rule 2 — Fingerprint match (strong)
If staged.primary_fingerprint == canonical.fingerprints.primary => match.

### Rule 3 — Name + time overlap (medium)
If normalized_name similarity >= 0.92 AND time overlap >= 60% => match.

### Rule 4 — Weekend heuristic (weak)
If same normalized_name family AND start dates within 36 hours AND duration bucket matches => match.

If multiple matches, pick highest score and record a merge_note.

## Field merge policy (v1)
General rule: pick the best value by:
1) human_override (future feature) always wins
2) highest trust source wins
3) if equal trust: prefer most recently seen
4) if still tied: keep existing canonical (stability bias)

Per-field notes:
- name: prefer more specific (longer after normalization) if trust >= existing trust
- start_utc/end_utc: if conflicts, choose higher trust; else choose the earlier first_seen for stability
- links: union by URL; de-duplicate exact URLs
- tags: union
- notes: append with attribution if conflicting
- modes/bands: union if both plausible; if one is "mixed" and other has specifics, keep specifics and include "mixed" only if warranted
- status: "cancelled" beats others only if trust >= existing trust; otherwise keep existing and add note

## Provenance updates
Each merge updates canonical.sources:
- if SourceRecord exists for (source, source_uid): update last_seen_utc, raw_hash, raw_excerpt
- else append new SourceRecord with first_seen_utc=observed_utc and last_seen_utc=observed_utc

## Quality scoring (v1)
confidence: map of max(trust)/100 capped at 1.0
completeness: fraction of key optional fields present:
  sponsor, modes, bands, exchange, links(rules/sponsor), geo_scope

## Output invariants
- canonical event must always have >=1 SourceRecord
- canonical event must always have hamcal_id, name, start_utc, end_utc, status, type
