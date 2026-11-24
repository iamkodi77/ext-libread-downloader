"""Filename sanitation, media URL helpers and console progress utilities."""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from typing import Optional
from urllib.parse import urlsplit

ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EXT_PATTERN = re.compile(r"^[A-Za-z0-9]{1,6}$")

WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_filename(name: str, max_len: int = 120, fallback: str = "untitled") -> str:
    """Make a string safe to use as a file or folder name on any OS."""
    cleaned = unicodedata.normalize("NFKC", str(name))
    cleaned = ILLEGAL_CHARS.sub("_", cleaned)
    cleaned = cleaned.strip(" .")
    if cleaned.upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > max_len:
        stem, ext = os.path.splitext(cleaned)
        cleaned = stem[: max_len - len(ext)].rstrip(" .") + ext
    return cleaned


def _path_extension(path: str) -> Optional[str]:
    name = path.rsplit("/", 1)[-1]
    if "." in name:
        ext = name.rsplit(".", 1)[1]
        if EXT_PATTERN.fullmatch(ext):
            return "." + ext.lower()
    return None


def media_extension(media_url: str, fallback: str = ".jpg") -> str:
    """Guess the file extension from a media URL's path (e.g. ``cover.webp``)."""
    try:
        path = urlsplit(media_url).path
    except ValueError:
        return fallback
    return _path_extension(path) or fallback


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def progress_bar(width: int = 40):
    """Return a callback that redraws an inline progress bar in the console."""

    def render(done: int, total: int, note: str = "") -> None:
        if total > 0:
            filled = int(width * done / total)
            bar = "#" * filled + "-" * (width - filled)
            percent = 100.0 * done / total
            sys.stdout.write(f"\r  [{bar}] {done}/{total} ({percent:5.1f}%) {note}")
        else:
            sys.stdout.write(f"\r  [{done} bytes] {note}")
        sys.stdout.flush()

    return render
