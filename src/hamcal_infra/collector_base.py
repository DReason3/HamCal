from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Protocol
from .types import StagedEventV1


@dataclass
class CollectorMeta:
    name: str
    trust_default: int
    homepage: Optional[str] = None
    notes: Optional[str] = None


class Collector(Protocol):
    """
    Collector interface: turn an upstream into StagedEventV1 records.

    Rule: collectors MUST NOT do canonical merging.
    They only:
      - fetch/parse upstream
      - normalize into StagedEventV1
      - set a trust_default via meta()
    """

    def meta(self) -> CollectorMeta:
        ...

    def collect(self) -> List[StagedEventV1]:
        ...


def require_nonempty(events: Iterable[StagedEventV1], collector_name: str) -> List[StagedEventV1]:
    out = list(events)
    if len(out) == 0:
        raise RuntimeError(f"Collector '{collector_name}' produced 0 events (unexpected).")
    return out
