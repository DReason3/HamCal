from __future__ import annotations

import os
import time
from typing import Optional

# ULID (Universally Unique Lexicographically Sortable Identifier)
# Spec: 48-bit timestamp (ms) + 80-bit randomness, Crockford Base32 => 26 chars.
#
# This is a small, dependency-free ULID generator for HamCal infra v1.
# Not crypto-strong for adversarial settings (uses os.urandom for randomness),
# but perfectly fine for stable IDs in a normal app pipeline.

_CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford_base32(data: bytes) -> str:
    """
    Encode bytes into Crockford Base32 with no padding.
    We treat data as a big-endian integer and emit enough 5-bit groups.
    """
    if not data:
        return ""

    n = int.from_bytes(data, "big", signed=False)
    bit_len = len(data) * 8
    out_len = (bit_len + 4) // 5  # ceil(bit_len/5)

    out = []
    for i in range(out_len):
        shift = (out_len - 1 - i) * 5
        idx = (n >> shift) & 0x1F
        out.append(_CROCKFORD32[idx])

    return "".join(out)


def ulid(timestamp_ms: Optional[int] = None, randomness: Optional[bytes] = None) -> str:
    """
    Create a ULID string (26 chars).
    - timestamp_ms: if None, uses current time in ms.
    - randomness: if None, uses os.urandom(10).
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    if timestamp_ms < 0 or timestamp_ms > 0xFFFFFFFFFFFF:
        raise ValueError("timestamp_ms out of range for 48-bit ULID timestamp")

    if randomness is None:
        randomness = os.urandom(10)

    if len(randomness) != 10:
        raise ValueError("randomness must be exactly 10 bytes (80 bits)")

    ts_bytes = timestamp_ms.to_bytes(6, "big", signed=False)  # 48 bits
    payload = ts_bytes + randomness  # 16 bytes = 128 bits

    # Encode 128 bits into 26 chars base32 (26*5=130 bits, top bits are zero-padded)
    s = _encode_crockford_base32(payload)

    # Left-pad to 26 characters if needed (should be 26 for 128-bit input, but safe)
    if len(s) < 26:
        s = ("0" * (26 - len(s))) + s
    elif len(s) > 26:
        # Trim any extra (shouldn't happen)
        s = s[-26:]

    return s


# Optional monotonic helper (good for burst inserts in the same ms)
_last_ts: Optional[int] = None
_last_rand: Optional[bytearray] = None


def ulid_monotonic(timestamp_ms: Optional[int] = None) -> str:
    """
    ULID generator that is monotonic within the same millisecond:
    if multiple ULIDs are requested in the same ms, the 80-bit randomness increments.
    """
    global _last_ts, _last_rand

    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    if _last_ts != timestamp_ms or _last_rand is None:
        _last_ts = timestamp_ms
        _last_rand = bytearray(os.urandom(10))
        return ulid(timestamp_ms=timestamp_ms, randomness=bytes(_last_rand))

    # increment 80-bit random as big-endian integer
    for i in range(9, -1, -1):
        _last_rand[i] = (_last_rand[i] + 1) & 0xFF
        if _last_rand[i] != 0:
            break

    return ulid(timestamp_ms=timestamp_ms, randomness=bytes(_last_rand))
