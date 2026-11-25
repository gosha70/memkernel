# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Content-hash deduplication helpers."""

from __future__ import annotations

import hashlib
import unicodedata

from memkernel.core.models import HASH_SCHEME_CANONICAL, HASH_SCHEME_RAW

# The scheme new records are hashed with (memkernel-0-17-supersede-and-canonical-hash D5, D6). A record states its own
# scheme (``Memory.hash_scheme``); a receipt records it (memkernel-0-15-harness-foundations A8).
CONTENT_HASH_SCHEME = HASH_SCHEME_CANONICAL
HASH_SCHEMES = (HASH_SCHEME_RAW, HASH_SCHEME_CANONICAL)
_BOM = "\ufeff"
_TRAILING = " \t"


def canonical_form(text: str) -> str:
    """The text ``sha256-canonical-v1`` hashes (D5): a leading byte-order mark removed, Unicode NFC, line endings to
    ``\\n``, trailing spaces and tabs removed from every line, blank lines removed at both ends. Case, inner spaces and
    indentation are kept. Only the hash uses it: the stored text stays as given."""
    if text.startswith(_BOM):
        text = text[len(_BOM) :]
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(_TRAILING) for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def compute_content_hash(content: str, scheme: str = CONTENT_HASH_SCHEME) -> str:
    """The SHA-256 hex digest of ``content`` under ``scheme``: its UTF-8 bytes (``sha256-raw``) or its canonical form
    (``sha256-canonical-v1``). An unknown scheme raises ``ValueError``."""
    if scheme == HASH_SCHEME_RAW:
        data = content
    elif scheme == HASH_SCHEME_CANONICAL:
        data = canonical_form(content)
    else:
        raise ValueError(f"unknown content hash scheme {scheme!r}; expected one of {', '.join(HASH_SCHEMES)}")
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
