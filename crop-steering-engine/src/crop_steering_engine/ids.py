"""ULID ids: 48-bit ms timestamp + 80 random bits, Crockford base32, 26 chars. Stdlib only."""

import hashlib
import os
import re
from datetime import UTC, datetime

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _encode(at: datetime, rand: bytes) -> str:
    if len(rand) != 10:
        raise ValueError("rand must be 10 bytes")
    ms = int(at.timestamp() * 1000)
    n = (ms << 80) | int.from_bytes(rand, "big")
    return "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def new_id(now: datetime | None = None, rand: bytes | None = None) -> str:
    return _encode(now or datetime.now(UTC), os.urandom(10) if rand is None else rand)


def derived_id(at: datetime, key: str) -> str:
    """Stable id for a pre-existing row: the same (at, key) always gives the same id."""
    return _encode(at, hashlib.sha256(key.encode()).digest()[:10])
