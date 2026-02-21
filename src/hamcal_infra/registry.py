from __future__ import annotations

from pathlib import Path
from typing import List

from .types import HamCalEventV1, StagedEventV1, dataclass_to_json


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
