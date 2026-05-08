"""
Format an AnalysisResult into Telegram-safe message chunks.

Telegram has a 4096-char limit per message. We send analyses as plain text
(no Markdown/HTML parsing) so emoji/timestamps/etc. round-trip cleanly
without escape-character risk. Long results are split on paragraph
boundaries when possible.
"""

from __future__ import annotations

from bot.games.base import AnalysisResult


TELEGRAM_MAX = 4096
SAFE_CHUNK = 3900  # leave headroom for trailing markers


def format_result(result: AnalysisResult) -> list[str]:
    """Return one-or-more strings each within Telegram's per-message limit."""
    body = result.raw_text.strip()
    if len(body) <= TELEGRAM_MAX:
        return [body]
    return _split_text(body, SAFE_CHUNK)


def _split_text(text: str, limit: int) -> list[str]:
    """Split on blank lines, then single newlines, then hard slice."""
    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    buf = ""
    for para in paragraphs:
        candidate = (buf + "\n\n" + para) if buf else para
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) <= limit:
            buf = para
        else:
            for line_chunk in _split_lines(para, limit):
                chunks.append(line_chunk)
    if buf:
        chunks.append(buf)
    return chunks


def _split_lines(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for line in text.split("\n"):
        candidate = (buf + "\n" + line) if buf else line
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(line) <= limit:
            buf = line
        else:
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
    if buf:
        chunks.append(buf)
    return chunks
