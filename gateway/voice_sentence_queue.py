"""Sentence chunking for low-latency Discord voice replies.

The model callback is synchronous and may split text at any character.  This
helper keeps that transport detail out of the gateway runner: it accepts text
deltas, emits the first two complete sentences together, then emits one
sentence at a time.  The final partial sentence is flushed when generation
ends.  Chunks are bounded to the active Audex provider's 600-character cap.
"""

from __future__ import annotations

import re
from typing import List


_BOUNDARY_RE = re.compile(r"(?<=[.!?…])(?:\s+)|(?:\n{2,})")


def _split_bounded(text: str, max_chars: int) -> List[str]:
    """Split *text* at a nearby word boundary without losing content."""
    remaining = " ".join((text or "").split())
    chunks: List[str] = []
    while len(remaining) > max_chars:
        cut = remaining.rfind(" ", 0, max_chars + 1)
        if cut < max_chars // 2:
            cut = max_chars
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


class VoiceSentenceChunker:
    """Turn arbitrary streamed deltas into conversational speech chunks."""

    def __init__(
        self,
        *,
        first_sentences: int = 2,
        later_sentences: int = 1,
        max_chars: int = 600,
    ) -> None:
        self.first_sentences = max(1, int(first_sentences))
        self.later_sentences = max(1, int(later_sentences))
        self.max_chars = max(80, int(max_chars))
        self._buffer = ""
        self._sentences: List[str] = []
        self._started = False

    def feed(self, delta: str) -> List[str]:
        if not delta:
            return []
        self._buffer += str(delta)
        self._extract_complete_sentences()
        return self._drain_ready(final=False)

    def finish(self) -> List[str]:
        tail = " ".join(self._buffer.split()).strip()
        self._buffer = ""
        if tail:
            self._sentences.append(tail)
        return self._drain_ready(final=True)

    def _extract_complete_sentences(self) -> None:
        start = 0
        matches = list(_BOUNDARY_RE.finditer(self._buffer))
        if not matches:
            return
        for match in matches:
            sentence = " ".join(self._buffer[start:match.start()].split()).strip()
            if sentence:
                self._sentences.append(sentence)
            start = match.end()
        self._buffer = self._buffer[start:]

    def _drain_ready(self, *, final: bool) -> List[str]:
        emitted: List[str] = []
        while self._sentences:
            required = self.first_sentences if not self._started else self.later_sentences
            if len(self._sentences) < required and not final:
                break
            take = min(required, len(self._sentences))
            combined = " ".join(self._sentences[:take]).strip()
            del self._sentences[:take]
            if not combined:
                continue
            emitted.extend(_split_bounded(combined, self.max_chars))
            self._started = True
        return emitted
