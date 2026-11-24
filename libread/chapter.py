"""Chapter content: fetch reader HTML and extract the article text / images."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .network import HttpClient
from .parser import SITE_BASE, ChapterInfo

_IMAGE_ATTRS = ("src", "data-src", "data-url")


class LockedChapterError(Exception):
    """Raised when a chapter requires payment, sign-in or is otherwise missing."""


@dataclass
class ChapterContent:
    html: str = ""
    images: list[str] = field(default_factory=list)

    @property
    def is_text(self) -> bool:
        return not self.images


def resolve_media_url(src: str) -> str:
    return urljoin(SITE_BASE, src)


def extract_images(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for img in soup.find_all("img"):
        src = None
        for attr in _IMAGE_ATTRS:
            if img.get(attr):
                src = img[attr]
                break
        if not src and img.get("srcset"):
            candidate = img["srcset"].split(",")[0].strip().split(" ")[0]
            src = candidate
        if not src or src.startswith("data:"):
            continue
        urls.append(resolve_media_url(src))
    return urls


def _clean_article(article) -> str:
    """Strip ads/scripts and return the readable inner HTML of the article."""
    for tag in article.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    for block in article.select("div.reader-ad-skip, div.fnw-media"):
        block.decompose()
    for element in article.find_all(True):
        if element.name == "div" and (element.get("id") or "").lower().startswith(
            ("pf-", "bg-ssp")
        ):
            if not element.get_text(strip=True) and not element.find("img"):
                element.decompose()
    return article.decode_contents()


def fetch_chapter_content(client: HttpClient, chapter: ChapterInfo) -> ChapterContent:
    """Fetch and parse a single chapter page from libread.com."""
    if not chapter.url:
        raise LockedChapterError(f"chapter {chapter.sort_order} has no link")
    html = client.get_text(chapter.url)
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("div#article")
    if article is None:
        raise LockedChapterError(f"chapter {chapter.sort_order} is locked or missing")
    content_html = _clean_article(article)
    return ChapterContent(html=content_html, images=extract_images(content_html))
