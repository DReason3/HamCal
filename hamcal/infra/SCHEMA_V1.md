# HamCal Infrastructure — Schema v1

Goal: Define a canonical HamCalEvent (source-of-truth) with full provenance.
All downstream outputs (ICS, HTML, JSON views) render from canonical records.

## Terms
- Canonical Event: the merged, best-known representation of a real-world event.
- Source Record: an immutable observation from an upstream source.
- Staging: normalized-but-not-merged records produced by collectors.

## Identifiers
- hamcal_id: ULID (Universally Unique Lexicographically Sortable Identifier) string. Permanent.
- external_ids: list of upstream identifiers (source + uid).

## Canonical Event: HamCalEventV1
Required:
- hamcal_id: string (ULID)
- type: "contest" | "hamfest" | "club" | "activation" | "field_day" | "other"
- name: string
- start_utc: RFC3339 string (UTC, ends with "Z")
- end_utc: RFC3339 string (UTC, ends with "Z")
- status: "scheduled" | "tentative" | "cancelled"
- sources: SourceRecordV1[]  (>=1)

Optional:
- timezone_hint: string (IANA TZ, e.g. "America/Chicago")
- sponsor: { name?: string, callsign?: string, org?: string }
- modes: string[] (normalized tokens: "cw","ssb","digital","mixed","fm","am","satellite","other")
- bands: string[] (tokens: "160m","80m","40m","20m","15m","10m","6m","2m","70cm","microwave","all","other")
- exchange: string
- scoring: string
- geo_scope: "worldwide" | "region" | "country" | "state" | "local" | "unknown"
- tags: string[]
- notes: string
- links: LinkV1[]
- quality: { confidence: 0..1, completeness: 0..1 }
- fingerprints: { primary: string, alternates?: string[] }
- last_modified_utc: RFC3339 string (UTC)

## Links: LinkV1
- rel: "rules" | "sponsor" | "log-upload" | "announcement" | "results" | "info" | "other"
- url: string
- title?: string

## Source Record: SourceRecordV1
Required:
- source: string (e.g. "wa7bnm_gcal", "arrl_contest", "sponsor_site", "user_submission")
- source_uid: string (stable id in upstream; for ICS this is UID if available)
- first_seen_utc: RFC3339 UTC
- last_seen_utc: RFC3339 UTC
- raw_hash: string (sha256 of raw payload/excerpt)
- fields: object  (field_attributions: keys written by this source)
- trust: number (0..100)  (collector-defined default, can be overridden later)

Optional:
- raw_excerpt: string (<= 500 chars for debugging)

## Staged Event: StagedEventV1
A normalized collector output before canonical merge.

Required:
- source: string
- source_uid: string
- name: string
- start_utc: RFC3339 UTC
- end_utc: RFC3339 UTC
- status: "scheduled" | "tentative" | "cancelled"
- raw_hash: string
- raw_excerpt: string
- observed_utc: RFC3339 UTC

Optional:
- type, sponsor, modes, bands, exchange, scoring, geo_scope, tags, notes, links, timezone_hint

## Normalization rules (v1)
- Times must be UTC RFC3339 with trailing Z.
- modes/bands should be lowercased tokens from allowed vocab. Unknown -> "other".
- geo_scope unknown if not inferred.
- Do not delete upstream info; keep it in raw_excerpt or notes if needed.

## Storage suggestion (v1)
- Canonical: NDJSON (Newline Delimited JSON) in `data/canonical/events.ndjson`
- Staging: NDJSON in `data/staging/{source}.ndjson`
- Or SQLite later (Phase 2).
