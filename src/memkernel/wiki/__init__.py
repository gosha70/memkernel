# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.
"""LLM-wiki bridge: compile long-term memories into markdown pages and index wiki pages as memories.

The wiki (Karpathy's "LLM Wiki" pattern) is the human-readable, git-versioned
form of the long-term semantic tier. MemKernel's vector store is the index
over it plus the home of everything that is *not* wiki-worthy (episodes,
observations, working state). See docs/architecture/memory-tiers.md.
"""

from memkernel.wiki.pages import WikiPage, parse_page, render_page
from memkernel.wiki.sync import WikiExporter, WikiImporter

__all__ = ["WikiExporter", "WikiImporter", "WikiPage", "parse_page", "render_page"]
