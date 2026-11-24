"""High-level download logic for the series cover and individual chapters."""

from __future__ import annotations

import os
import time
from typing import Optional

from bs4 import BeautifulSoup

from .chapter import fetch_chapter_content
from .network import HttpClient
from .parser import ChapterInfo, Series
from . import utils


class DownloadCancelled(Exception):
    """Raised when the user stops an in-flight download."""


def _console_notify(event: str, **payload) -> None:
    if event == "log":
        print(payload.get("text", ""))
    elif event == "chapter":
        print()
    elif event == "image":
        progress = utils.progress_bar()
        progress(
            payload.get("done_bytes", 0),
            payload.get("total_bytes", 0),
            payload.get("name", ""),
        )


def series_directory(output_root: str, series: Series) -> str:
    folder = os.path.join(output_root, utils.sanitize_filename(series.title))
    os.makedirs(folder, exist_ok=True)
    return folder


def download_cover(
    client: HttpClient,
    series: Series,
    output_root: str,
    notify=None,
) -> Optional[str]:
    """Download the series cover into the series folder."""
    if notify is None:
        notify = _console_notify
    if not series.cover_url:
        notify("log", text="  - no cover image found, skipping")
        return None
    folder = series_directory(output_root, series)
    extension = utils.media_extension(series.cover_url)
    destination = os.path.join(folder, f"cover{extension}")
    notify("log", text=f"[cover] {series.cover_url}")
    client.download(series.cover_url, destination)
    notify("log", text=f"  -> {os.path.relpath(destination, output_root)}")
    return destination


def _save_text_artifacts(chapter_dir: str, html: str) -> None:
    html_dest = os.path.join(chapter_dir, "chapter.html")
    with open(html_dest, "w", encoding="utf-8") as handle:
        handle.write(html)
    text = _html_to_text(html)
    text_dest = os.path.join(chapter_dir, "chapter.txt")
    with open(text_dest, "w", encoding="utf-8") as handle:
        handle.write(text)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for para in soup.find_all(["p", "h1", "h2", "h3", "h4", "div"]):
        para.append("\n")
    lines = [line.strip() for line in soup.get_text().splitlines()]
    return "\n".join(line for line in lines if line)


def download_chapter(
    client: HttpClient,
    chapter: ChapterInfo,
    output_root: str,
    series: Series,
    list_index: int,
    position: int,
    total: int,
    delay: float = 0.3,
    notify=None,
    cancel_event: Optional[object] = None,
) -> None:
    """Download one chapter: page images when present, otherwise its text content."""
    if notify is None:
        notify = _console_notify

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled()

    if delay:
        time.sleep(delay)
    check_cancelled()

    folder = series_directory(output_root, series)
    chapter_dir = os.path.join(folder, f"Chapter {list_index:03d}")
    os.makedirs(chapter_dir, exist_ok=True)

    content = fetch_chapter_content(client, chapter)

    label = f"[{position}/{total}] Chapter {list_index:03d} - {chapter.title}"
    if content.images:
        notify("log", text=f"{label} ({len(content.images)} embedded images)")
        notify("chapter", index=list_index, title=chapter.title, total_images=len(content.images))
        _save_text_artifacts(chapter_dir, content.html)
        for page_index, image_url in enumerate(content.images, start=1):
            check_cancelled()
            extension = utils.media_extension(image_url)
            destination = os.path.join(chapter_dir, f"page_{page_index:03d}{extension}")

            def progress(done: int, size: int) -> None:
                check_cancelled()
                notify(
                    "image",
                    index=list_index,
                    page=page_index,
                    total=len(content.images),
                    done_bytes=done,
                    total_bytes=size,
                    name=os.path.basename(destination),
                )

            client.download(image_url, destination, progress=progress)
            notify("image", index=list_index, page=page_index, total=len(content.images),
                   done_bytes=0, total_bytes=0, name=os.path.basename(destination))
        notify("log", text=f"  -> {os.path.relpath(chapter_dir, output_root)}/ ({len(content.images)} images)")
    else:
        notify("log", text=f"{label} (text chapter)")
        notify("chapter", index=list_index, title=chapter.title, total_images=0)
        _save_text_artifacts(chapter_dir, content.html)
        size = sum(os.path.getsize(os.path.join(chapter_dir, f)) for f in os.listdir(chapter_dir))
        notify("log", text=f"  -> {os.path.relpath(chapter_dir, output_root)}/ ({utils.format_size(size)})")
