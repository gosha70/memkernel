# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""Moved: the transcript reader now lives in ``memkernel.transcripts.claude_code`` (memkernel-0-12-capture-core FR-004).

The repeated-mistake count reads through it; this module only re-exports it for older imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from memkernel.transcripts.claude_code import ClaudeCodeTranscriptReader, transcript_files  # noqa: E402

__all__ = ["ClaudeCodeTranscriptReader", "transcript_files"]
