"""Build a dependency-free EPUB 3 file from downloaded chapter content.

Only the Python standard library is used (zipfile, tempfile, hand-written
XML). Text chapters are converted from their stored chapter.html; chapters
with embedded images become an image-based ebook.
"""

from __future__ import annotations

import html as html_mod
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from . import utils
from .chapter import resolve_media_url
from .network import HttpClient

IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

TEXT_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "strong", "em",
    "b", "i", "u", "sub", "sup", "small", "ul", "ol", "li", "blockquote",
    "a", "span", "div", "table", "tr", "td", "th", "thead", "tbody", "figure",
}
VOID_TAGS = {"br", "hr", "img"}


def _xml_escape(text: str) -> str:
    return html_mod.escape(text, quote=True)


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _starts_with_title_heading(content_html: str, title: str) -> bool:
    """True when the content already opens with a heading matching ``title``."""
    if not content_html or not title.strip():
        return False
    soup = BeautifulSoup(content_html, "html.parser")
    heading = soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if heading is None:
        return False
    if _normalize_text(heading.get_text()) != _normalize_text(title):
        return False
    # Only treat as already titled when no visible text precedes the heading.
    for previous in heading.find_all_previous(string=True):
        if previous.strip():
            return False
    return True


class EpubBuilder:
    """Assembles chapters and a cover into an EPUB package."""

    def __init__(self, title: str, author: str = "", slug: str = "", language: str = "en", client: Optional[HttpClient] = None):
        self.title = title
        self.author = author or "Unknown"
        self.slug = slug or "libread"
        self.language = language
        self.client = client or HttpClient(retries=1)
        self.tmp = tempfile.mkdtemp(prefix="libread_epub_")
        self.text_dir = os.path.join(self.tmp, "OEBPS", "text")
        self.image_dir = os.path.join(self.tmp, "OEBPS", "images")
        os.makedirs(self.text_dir, exist_ok=True)
        os.makedirs(self.image_dir, exist_ok=True)
        os.makedirs(os.path.join(self.image_dir, "pages"), exist_ok=True)
        self.chapters: list[tuple[str, str]] = []  # (href, title)
        self.image_items: list[tuple[str, str]] = []  # (href, media_type)
        self.cover_href: Optional[str] = None
        self.cover_mime: Optional[str] = None
        self._inline_counter = 0

    # -- cover --------------------------------------------------------------

    def set_cover(self, local_path: Optional[str]) -> None:
        if not local_path or not os.path.exists(local_path):
            return
        extension = os.path.splitext(local_path)[1].lower() or ".jpg"
        destination = os.path.join(self.image_dir, f"cover{extension}")
        shutil.copyfile(local_path, destination)
        self.cover_href = f"images/cover{extension}"
        self.cover_mime = IMAGE_MIME.get(extension, "image/jpeg")

    # -- chapters -----------------------------------------------------------

    def add_text_chapter(self, index: int, title: str, content_html: str) -> None:
        body = self._render_text_body(content_html)
        if title.strip() and not _starts_with_title_heading(content_html, title):
            body = f"{self._chapter_heading(title)}\n{body}"
        document = self._document(title, body)
        filename = f"chapter{index:03d}.xhtml"
        with open(os.path.join(self.text_dir, filename), "w", encoding="utf-8") as handle:
            handle.write(document)
        self.chapters.append((f"text/{filename}", title))

    def add_image_chapter(self, index: int, title: str, page_files: Iterable[str]) -> None:
        lines = []
        if title.strip():
            lines.append(self._chapter_heading(title))
        for position, page_file in enumerate(page_files, start=1):
            extension = os.path.splitext(page_file)[1].lower() or ".jpg"
            filename = f"pages/c{index:03d}_p{position:03d}{extension}"
            shutil.copyfile(page_file, os.path.join(self.image_dir, filename))
            self.image_items.append((f"images/{filename}", IMAGE_MIME.get(extension, "image/jpeg")))
            lines.append(
                f'<div class="manga-page"><img src="../images/{filename}" alt="Page {position}"/></div>'
            )
        document = self._document(title, "".join(lines))
        filename = f"chapter{index:03d}.xhtml"
        with open(os.path.join(self.text_dir, filename), "w", encoding="utf-8") as handle:
            handle.write(document)
        self.chapters.append((f"text/{filename}", title))

    def _document(self, title: str, body: str) -> str:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{self.language}" lang="{self.language}">\n'
            "<head>\n"
            f"<title>{_xml_escape(title)}</title>\n"
            '<link rel="stylesheet" type="text/css" href="../styles.css"/>\n'
            "</head>\n"
            f"<body>\n{body}\n</body>\n</html>\n"
        )

    @staticmethod
    def _chapter_heading(title: str) -> str:
        """Bold, oversized chapter title shown at the top of the chapter's first page."""
        return f'<h1 class="chapter-title">{_xml_escape(title)}</h1>'

    def _render_text_body(self, content_html: str) -> str:
        soup = BeautifulSoup(content_html, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        container = soup.body if soup.body else soup
        lines: list[str] = []
        for child in container.children:
            self._serialize(child, lines)
        return "\n".join(lines)

    def _serialize(self, node, lines: list[str]) -> None:
        if isinstance(node, str) or getattr(node, "name", None) is None:
            lines.append(html_mod.escape(str(node), quote=False))
            return
        name = node.name
        if name == "img":
            src = node.get("src") or node.get("data-src")
            if not src:
                return
            href = self._embed_image(resolve_media_url(src))
            if not href:
                return
            alt = _xml_escape(node.get("alt") or "")
            lines.append(f'<img src="{href}" alt="{alt}"/>')
            return
        if name not in TEXT_TAGS:
            for child in node.children:
                self._serialize(child, lines)
            return
        attributes = ""
        if name == "a" and node.get("href"):
            href = node["href"]
            if href.startswith(("http://", "https://")):
                attributes = f' href="{_xml_escape(href)}"'
        if name == "p":
            attributes = ' class="para"'
        elif name in ("h1", "h2", "h3", "h4"):
            attributes = ' class="chapter-title"'
        if name in VOID_TAGS:
            lines.append(f"<{name}{attributes}/>")
            return
        lines.append(f"<{name}{attributes}>")
        for child in node.children:
            self._serialize(child, lines)
        lines.append(f"</{name}>")

    def _embed_image(self, src: str) -> Optional[str]:
        self._inline_counter += 1
        extension = utils.media_extension(src)
        filename = f"inline_{self._inline_counter:04d}{extension}"
        destination = os.path.join(self.image_dir, filename)
        try:
            self.client.download(src, destination)
        except Exception:
            if os.path.exists(destination):
                os.remove(destination)
            return None
        self.image_items.append((f"images/{filename}", IMAGE_MIME.get(extension, "image/jpeg")))
        return f"../images/{filename}"

    # -- packaging ----------------------------------------------------------

    def build(self, output_path: str) -> str:
        try:
            self._write_cover_page()
            self._write_content_opf()
            self._write_nav()
            self._write_styles()
            self._write_container()
            self._write_mimetype()
            self._zip(output_path)
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)
        return output_path

    def _cover_exists(self) -> bool:
        return self.cover_href is not None and os.path.exists(
            os.path.join(self.tmp, "OEBPS", *self.cover_href.split("/"))
        )

    def _write_cover_page(self) -> None:
        if not self._cover_exists():
            return
        cover_xhtml = self._document(
            self.title,
            f'<div class="cover-page"><img src="{self.cover_href}" alt="Cover"/></div>',
        )
        with open(os.path.join(self.tmp, "OEBPS", "cover.xhtml"), "w", encoding="utf-8") as handle:
            handle.write(cover_xhtml)

    def _write_content_opf(self) -> None:
        identifier = f"urn:uuid:{uuid.uuid4()}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        today = time.strftime("%Y-%m-%d", time.gmtime())
        manifest = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="css" href="styles.css" media-type="text/css"/>',
        ]
        spine = []
        if self._cover_exists():
            manifest.append(
                f'<item id="cover-image" href="{self.cover_href}" media-type="{self.cover_mime}" properties="cover-image"/>'
            )
            manifest.append('<item id="cover-page" href="cover.xhtml" media-type="application/xhtml+xml"/>')
            spine.append('<itemref idref="cover-page"/>')
        image_index = 0
        for href, media_type in self.image_items:
            image_index += 1
            manifest.append(f'<item id="img{image_index}" href="{href}" media-type="{media_type}"/>')
        for index, (href, title) in enumerate(self.chapters, start=1):
            manifest.append(
                f'<item id="ch{index:03d}" href="{href}" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="ch{index:03d}"/>')
        manifest_xml = "\n    ".join(manifest)
        spine_xml = "\n    ".join(spine)
        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{self.language}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{_xml_escape(identifier)}</dc:identifier>
    <dc:title>{_xml_escape(self.title)}</dc:title>
    <dc:creator>{_xml_escape(self.author)}</dc:creator>
    <dc:language>{self.language}</dc:language>
    <dc:date>{today}</dc:date>
    <meta property="dcterms:modified">{now}</meta>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
    {manifest_xml}
  </manifest>
  <spine>
    {spine_xml}
  </spine>
</package>
"""
        with open(os.path.join(self.tmp, "OEBPS", "content.opf"), "w", encoding="utf-8") as handle:
            handle.write(opf)

    def _write_nav(self) -> None:
        items = []
        for href, title in self.chapters:
            items.append(f'    <li><a href="{href}">{_xml_escape(title)}</a></li>')
        nav = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{self.language}" lang="{self.language}">
<head>
  <title>{_xml_escape(self.title)}</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{chr(10).join(items)}
    </ol>
  </nav>
</body>
</html>
"""
        with open(os.path.join(self.tmp, "OEBPS", "nav.xhtml"), "w", encoding="utf-8") as handle:
            handle.write(nav)

    def _write_styles(self) -> None:
        css = """body {
  margin: 1em;
  font-family: Georgia, 'Times New Roman', serif;
  line-height: 1.65;
  font-size: 1em;
}
h1, h2, h3, h4 { font-family: Arial, Helvetica, sans-serif; line-height: 1.3; font-weight: bold; }
h1.chapter-title, h2.chapter-title, h3.chapter-title, h4.chapter-title {
  text-align: center;
  margin: 0.5em 0 1em;
  font-weight: bold;
}
h1.chapter-title { font-size: 1.8em; }
h2.chapter-title { font-size: 1.6em; }
h3.chapter-title { font-size: 1.4em; }
h4.chapter-title { font-size: 1.2em; }
p.para { margin: 0 0 0.8em; text-indent: 1.2em; }
img { max-width: 100%; height: auto; }
.manga-page { text-align: center; margin: 0; page-break-after: always; }
.cover-page { text-align: center; }
a { color: inherit; }
"""
        with open(os.path.join(self.tmp, "OEBPS", "styles.css"), "w", encoding="utf-8") as handle:
            handle.write(css)

    def _write_container(self) -> None:
        container_dir = os.path.join(self.tmp, "META-INF")
        os.makedirs(container_dir, exist_ok=True)
        container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
        with open(os.path.join(container_dir, "container.xml"), "w", encoding="utf-8") as handle:
            handle.write(container)

    def _write_mimetype(self) -> None:
        with open(os.path.join(self.tmp, "mimetype"), "w", encoding="utf-8") as handle:
            handle.write("application/epub+zip")

    def _zip(self, output_path: str) -> None:
        with zipfile.ZipFile(output_path, "w") as archive:
            archive.write(
                os.path.join(self.tmp, "mimetype"),
                arcname="mimetype",
                compress_type=zipfile.ZIP_STORED,
            )
            for root, _, files in os.walk(self.tmp):
                for filename in files:
                    if root == self.tmp and filename == "mimetype":
                        continue
                    full = os.path.join(root, filename)
                    arcname = os.path.relpath(full, self.tmp)
                    archive.write(full, arcname=arcname, compress_type=zipfile.ZIP_DEFLATED)


def build_epub(
    chapters: list[tuple[int, str]],
    series_dir: str,
    series_title: str,
    series_slug: str,
    author: str = "",
    cover_path: Optional[str] = None,
    client: Optional[HttpClient] = None,
) -> str:
    """Build an EPUB from downloaded chapters inside ``series_dir``.

    ``chapters`` is an ordered list of ``(list_index, title)`` pairs. Each
    chapter is read from ``series_dir/Chapter {index:03d}/`` (either
    ``chapter.html`` for text or ``page_*`` files for image chapters).
    """
    builder = EpubBuilder(series_title, author, series_slug, client=client)
    for index, title in chapters:
        chapter_dir = os.path.join(series_dir, f"Chapter {index:03d}")
        if not os.path.isdir(chapter_dir):
            continue
        pages = sorted(
            os.path.join(chapter_dir, name)
            for name in os.listdir(chapter_dir)
            if name.startswith("page_") and os.path.isfile(os.path.join(chapter_dir, name))
        )
        if pages:
            builder.add_image_chapter(index, title, pages)
            continue
        content_path = os.path.join(chapter_dir, "chapter.html")
        if os.path.exists(content_path):
            with open(content_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            if content.strip():
                builder.add_text_chapter(index, title, content)
    if not builder.chapters:
        shutil.rmtree(builder.tmp, ignore_errors=True)
        raise RuntimeError("no downloadable chapter content was found to build an EPUB")
    builder.set_cover(cover_path)
    output_path = os.path.join(series_dir, utils.sanitize_filename(series_title) + ".epub")
    return builder.build(output_path)
