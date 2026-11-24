"""Series page parsing: cover image, chapter rows and pagination."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .network import HttpClient

SITE_BASE = "https://libread.com"
PER_PAGE = 40
MAX_PAGES = 500

CHAPTER_SELECTOR = "ul#idData li a[href*='/chapter-']"
CHAPTER_LINK_RE = re.compile(r"/chapter-(\d+)/?$")


@dataclass
class ChapterInfo:
    chapter_id: int
    title: str
    url: str
    is_locked: bool
    sort_order: int


@dataclass
class Series:
    slug: str
    title: str
    cover_url: Optional[str]
    total_chapters: int
    chapters: list[ChapterInfo] = field(default_factory=list)
    author: str = ""

    @property
    def accessible(self) -> list[ChapterInfo]:
        return [chapter for chapter in self.chapters if not chapter.is_locked]


def _title_from_soup(soup: BeautifulSoup, fallback: str) -> str:
    heading = soup.select_one("h1.tit")
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)
    meta = soup.select_one('meta[property="og:title"]')
    if meta and meta.get("content"):
        title = meta["content"].split("|", 1)[0].split(" - ", 1)[0].strip()
        if title:
            return title
    return fallback


def _cover_from_soup(soup: BeautifulSoup) -> Optional[str]:
    for selector in ('meta[property="og:image"]', 'meta[name="image"]'):
        meta = soup.select_one(selector)
        if meta and meta.get("content"):
            return urljoin(SITE_BASE, meta["content"].strip())
    img = soup.select_one("img[data-src]")
    if img and img.get("data-src"):
        return urljoin(SITE_BASE, img["data-src"].strip())
    return None


def _author_from_soup(soup: BeautifulSoup) -> str:
    meta = soup.select_one('meta[property="og:novel:author"]')
    if meta and meta.get("content"):
        return meta["content"].strip()
    return ""


def _parse_chapter_row(link) -> ChapterInfo:
    href = link.get("href") or ""
    match = CHAPTER_LINK_RE.search(href)
    chapter_id = int(match.group(1)) if match else 0
    title = link.get("title") or link.get_text(strip=True) or href
    return ChapterInfo(
        chapter_id=chapter_id,
        title=title,
        url=urljoin(SITE_BASE, href),
        is_locked=False,
        sort_order=0,
    )


def parse_series_page(html: str, slug: str) -> Series:
    soup = BeautifulSoup(html, "html.parser")
    title = _title_from_soup(soup, slug)
    cover_url = _cover_from_soup(soup)
    author = _author_from_soup(soup)
    chapters = [_parse_chapter_row(link) for link in soup.select(CHAPTER_SELECTOR)]
    return Series(
        slug=slug,
        title=title,
        cover_url=cover_url,
        total_chapters=0,
        chapters=chapters,
        author=author,
    )


def series_page_url(slug: str, page: int = 1) -> str:
    if page <= 1:
        return f"{SITE_BASE}/libread/{slug}"
    return f"{SITE_BASE}/libread/{slug}/{page}"


def fetch_series(slug: str, client: HttpClient) -> Series:
    """Fetch every chapter page of a series (the site paginates at 40/page)."""
    all_chapters: list[ChapterInfo] = []
    first: Optional[Series] = None
    for page in range(1, MAX_PAGES + 1):
        series = parse_series_page(client.get_text(series_page_url(slug, page)), slug)
        if first is None:
            first = series
        if not series.chapters:
            break
        all_chapters.extend(series.chapters)
        if len(series.chapters) < PER_PAGE:
            break
    if first is None or not all_chapters:
        raise RuntimeError(f"no chapter data found for series '{slug}'")
    for order, chapter in enumerate(all_chapters, start=1):
        chapter.sort_order = order
    first.chapters = all_chapters
    first.total_chapters = len(all_chapters)
    return first
