import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from libread.chapter import LockedChapterError
from libread.downloader import download_chapter
from libread.epub import build_epub
from libread.parser import ChapterInfo, Series, fetch_series, parse_series_page, series_page_url
from libread_dl import extract_slug, resolve_selection


class FakeHttpClient:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


class CliSelectionTests(unittest.TestCase):
    def test_extract_slug_accepts_supported_inputs(self):
        self.assertEqual(extract_slug("starting-with-an-sss-rank-216486"), "starting-with-an-sss-rank-216486")
        self.assertEqual(
            extract_slug("https://libread.com/libread/my-series-42/3"),
            "my-series-42",
        )
        self.assertEqual(extract_slug("/libread/my-series-42"), "my-series-42")

    def test_resolve_selection_is_one_based_and_inclusive(self):
        self.assertEqual(resolve_selection("all", 4), [0, 1, 2, 3])
        self.assertEqual(resolve_selection("2", 4), [1])
        self.assertEqual(resolve_selection("2 - 4", 4), [1, 2, 3])
        self.assertIsNone(resolve_selection("4-2", 4))
        self.assertIsNone(resolve_selection("5", 4))
        self.assertIsNone(resolve_selection("", 4))


class DownloadBehaviorTests(unittest.TestCase):
    def test_locked_chapter_is_reported_to_the_calling_front_end(self):
        series = Series(slug="series", title="Series", cover_url=None, total_chapters=1)
        chapter = ChapterInfo(101, "Chapter 1", "https://libread.com/chapter-101", False, 1)
        with tempfile.TemporaryDirectory() as output:
            with patch("libread.downloader.fetch_chapter_content", side_effect=LockedChapterError("locked")):
                with self.assertRaises(LockedChapterError):
                    download_chapter(
                        object(), chapter, output, series, 1, 1, 1,
                        delay=0, notify=lambda *args, **kwargs: None,
                    )


class SeriesParserTests(unittest.TestCase):
    def test_parse_series_page_extracts_metadata_and_chapters(self):
        html = """
        <html><head>
          <meta property="og:image" content="/uploads/cover.jpg">
          <meta property="og:novel:author" content="Writer One">
        </head><body>
          <h1 class="tit">A Test Series</h1>
          <ul id="idData">
            <li><a href="/libread/test-series/chapter-101" title="Chapter 1: Start">Read chapter 1</a></li>
            <li><a href="/libread/test-series/chapter-102">Chapter 2</a></li>
          </ul>
        </body></html>
        """
        series = parse_series_page(html, "test-series")
        self.assertEqual(series.title, "A Test Series")
        self.assertEqual(series.author, "Writer One")
        self.assertEqual(series.cover_url, "https://libread.com/uploads/cover.jpg")
        self.assertEqual([chapter.chapter_id for chapter in series.chapters], [101, 102])
        self.assertEqual(series.chapters[0].title, "Chapter 1: Start")
        self.assertFalse(series.chapters[0].is_locked)

    def test_fetch_series_stops_after_short_page(self):
        page_url = series_page_url("test-series")
        html = """
        <h1 class="tit">Test</h1>
        <ul id="idData">
          <li><a href="/libread/test-series/chapter-1">One</a></li>
          <li><a href="/libread/test-series/chapter-2">Two</a></li>
        </ul>
        """
        client = FakeHttpClient({page_url: html})
        series = fetch_series("test-series", client)
        self.assertEqual(len(series.chapters), 2)
        self.assertEqual([chapter.sort_order for chapter in series.chapters], [1, 2])
        self.assertEqual(client.urls, [page_url])


class EpubTests(unittest.TestCase):
    def test_build_epub_writes_mimetype_and_chapter_heading(self):
        with tempfile.TemporaryDirectory() as output:
            series_dir = os.path.join(output, "Test Series")
            chapter_dir = os.path.join(series_dir, "Chapter 001")
            os.makedirs(chapter_dir)
            with open(os.path.join(chapter_dir, "chapter.html"), "w", encoding="utf-8") as chapter:
                chapter.write("<p>Once upon a time.</p>")

            epub_path = build_epub(
                [(1, "The Beginning")],
                series_dir,
                "Test Series",
                "test-series",
                author="Test Author",
            )
            with zipfile.ZipFile(epub_path) as archive:
                names = archive.namelist()
                self.assertEqual(names[0], "mimetype")
                self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
                chapter_xhtml = archive.read("OEBPS/text/chapter001.xhtml").decode("utf-8")
                self.assertIn('class="chapter-title"', chapter_xhtml)
                self.assertIn("The Beginning", chapter_xhtml)
                self.assertIn("Once upon a time.", chapter_xhtml)


if __name__ == "__main__":
    unittest.main()
