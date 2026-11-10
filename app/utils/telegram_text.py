"""
Telegram text-size helpers (CHG-028). Standard library only; pure and deterministic.

Telegram rejects a message whose text exceeds 4096 characters *after entity
parsing*: HTML tags and Markdown markers are not counted, character references
such as ``&lt;`` count as one character, and literal wrapper text (titles,
separators, footers) does count. Lengths are measured in UTF-16 code units,
which is never smaller than the code-point count, so the check stays
conservative whichever way Telegram counts.

Python strings are sequences of code points, so splitting at code-point
boundaries can never cut a surrogate pair or corrupt a character.
"""

from __future__ import annotations

from html.parser import HTMLParser

TELEGRAM_MESSAGE_LIMIT = 4096
# Budget per message when text is split into several messages (conservative).
CHUNK_BUDGET = 3500
# Guard for replies that are not split: below the hard limit, above CHUNK_BUDGET,
# so results that used to send fine (up to ~4000) are not newly rejected.
SINGLE_MESSAGE_BUDGET = 4000
# Smallest useful room for text inside a wrapper; guards absurd configurations.
MIN_ROOM = 200


def utf16_len(text: str) -> int:
    """Length of ``text`` in UTF-16 code units (astral characters count 2)."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_visible_text(html_text: str) -> str:
    """Text Telegram counts for an HTML-mode message (tags removed, refs resolved)."""
    parser = _VisibleText()
    parser.feed(html_text)
    parser.close()
    return "".join(parser.parts)


def html_visible_len(html_text: str) -> int:
    """UTF-16 length of an HTML-mode message after entity parsing."""
    return utf16_len(html_visible_text(html_text))


def fits(visible_text: str, budget: int = SINGLE_MESSAGE_BUDGET) -> bool:
    """True if the text Telegram will count is within ``budget`` UTF-16 units."""
    return utf16_len(visible_text) <= budget


def chunk_room(overhead_visible: str, budget: int = CHUNK_BUDGET) -> int:
    """UTF-16 units left for payload text once the wrapper's visible text is counted.

    ``overhead_visible`` is the worst-case literal text surrounding the payload
    (title, separators, footer, notices), without markup.
    """
    room = budget - utf16_len(overhead_visible)
    if room < MIN_ROOM:
        raise ValueError(f"wrapper leaves only {room} units of room (minimum {MIN_ROOM})")
    return room


def split_text(text: str, max_units: int) -> list[str]:
    """Split ``text`` into chunks of at most ``max_units`` UTF-16 units.

    * ``"".join(result) == text`` always (lossless).
    * Splits only between code points; astral characters count as two units.
    * Prefers to end a chunk after a newline when one lies in the second half
      of the window; otherwise fills the window.
    """
    if max_units < 2:
        raise ValueError("max_units must be at least 2")
    chunks: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        units = 0
        j = i
        while j < n:
            step = 2 if ord(text[j]) > 0xFFFF else 1
            if units + step > max_units:
                break
            units += step
            j += 1
        if j == n:
            chunks.append(text[i:j])
            break
        newline = text.rfind("\n", i + (j - i) // 2, j)
        if newline != -1:
            j = newline + 1
        chunks.append(text[i:j])
        i = j
    return chunks


def too_long_notice(what: str) -> str:
    """HTML reply for a result that cannot be sent in one Telegram message."""
    return (
        "❌ <b>Output too long.</b>\n"
        f"The {what} result would not fit in a single Telegram message. "
        "Please use shorter input."
    )
