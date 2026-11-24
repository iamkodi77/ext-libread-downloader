#!/usr/bin/env python3
"""LibRead web novel downloader.

Downloads a series cover and its chapters from https://libread.com/.

Examples:
    python3 libread_dl.py https://libread.com/libread/starting-with-an-sss-rank-goddess-summon-216486
    python3 libread_dl.py https://libread.com/libread/starting-with-an-sss-rank-goddess-summon-216486 -r 1-5
    python3 libread_dl.py starting-with-an-sss-rank-goddess-summon-216486 --all -o downloads
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urlsplit

from libread.chapter import LockedChapterError
from libread.downloader import download_chapter, download_cover, series_directory
from libread.epub import build_epub
from libread.network import HttpClient
from libread.parser import Series, fetch_series

DEFAULT_OUTPUT = "downloads"
SERIES_PATH_RE = re.compile(r"/libread/([^/?#]+)")


def extract_slug(url_or_slug: str) -> str:
    candidate = url_or_slug.strip()
    if not candidate.startswith("http"):
        match = SERIES_PATH_RE.search(candidate)
        if match:
            return match.group(1)
        return candidate.rstrip("/").rsplit("/", 1)[-1]
    match = SERIES_PATH_RE.search(urlsplit(candidate).path)
    if match:
        return match.group(1)
    raise ValueError(f"could not parse a series slug from: {url_or_slug}")


def resolve_selection(text: str, count: int) -> list[int] | None:
    """Turn user input (all / N / A-B) into 0-based chapter indexes."""
    choice = text.strip().lower()
    if choice in ("all", "a", "*"):
        return list(range(count))
    if re.fullmatch(r"\d+", choice):
        index = int(choice)
        if 1 <= index <= count:
            return [index - 1]
    if re.fullmatch(r"\d+\s*-\s*\d+", choice):
        start, end = (int(part) for part in re.split(r"\s*-\s*", choice))
        if 1 <= start <= end <= count:
            return list(range(start - 1, end))
    return None


def prompt_selection(series: Series) -> list[int]:
    accessible = series.accessible
    print()
    print(f"Accessible chapters ({len(accessible)} of {series.total_chapters}):")
    for index, chapter in enumerate(accessible, start=1):
        print(f"  {index:>4}. {chapter.title}")
    while True:
        print()
        answer = input(
            "Download: [all] / [chapter number] / [range e.g. 1-5] > "
        ).strip()
        if not answer:
            continue
        selection = resolve_selection(answer, len(accessible))
        if selection is not None:
            return selection
        print(f"  ! invalid choice '{answer}' (expected all, a number, or A-B)")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="libread_dl.py",
        description="Download series covers and chapters from libread.com.",
    )
    parser.add_argument("url", help="series URL or slug, e.g. "
                                   "https://libread.com/libread/starting-with-an-sss-rank-goddess-summon-216486")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="output folder (default: downloads)")
    parser.add_argument("-a", "--all", action="store_true", help="download all accessible chapters")
    parser.add_argument("-c", "--chapter", type=int, metavar="N", help="download chapter number N only")
    parser.add_argument("-r", "--range", metavar="A-B", help="download chapters in the inclusive range A-B")
    parser.add_argument("-l", "--list", action="store_true", help="list chapters and exit")
    parser.add_argument("--no-cover", action="store_true", help="skip downloading the cover image")
    parser.add_argument("--no-epub", action="store_true", help="skip building an EPUB after download")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds to wait between chapters (default: 0.3)")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds (default: 30)")
    parser.add_argument("--retries", type=int, default=3, help="HTTP retries per request (default: 3)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        slug = extract_slug(args.url)
    except ValueError as exc:
        print(exc)
        return 2

    client = HttpClient(timeout=args.timeout, retries=args.retries)
    series = fetch_series(slug, client)
    print(
        f"{series.title} | {len(series.chapters)} chapters "
        f"({len(series.accessible)} accessible, {len(series.chapters) - len(series.accessible)} locked)"
    )

    if args.list:
        for index, chapter in enumerate(series.accessible, start=1):
            print(f"{index:>4}. {chapter.title}")
        return 0

    if args.chapter is not None and args.range is not None:
        print("  ! use either --chapter or --range, not both")
        return 2

    selection_text = None
    if args.all:
        selection_text = "all"
    elif args.chapter is not None:
        selection_text = str(args.chapter)
    elif args.range is not None:
        selection_text = args.range

    if selection_text is not None:
        selection = resolve_selection(selection_text, len(series.accessible))
        if selection is None:
            print(f"  ! invalid selection '{selection_text}'")
            return 2
    else:
        selection = prompt_selection(series)
    if not selection:
        print("  ! nothing selected")
        return 1

    accessible = series.accessible
    selected = [accessible[index] for index in selection]

    cover_path = None
    if not args.no_cover:
        print()
        print("[cover] downloading poster image ...")
        cover_path = download_cover(client, series, args.output)

    print()
    print(f"[download] fetching {len(selected)} chapter(s) into '{args.output}' ...")
    failures = 0
    done_chapters: list[tuple[int, str]] = []
    for position, chapter in enumerate(selected, start=1):
        list_index = accessible.index(chapter) + 1
        try:
            download_chapter(
                client,
                chapter,
                args.output,
                series,
                list_index=list_index,
                position=position,
                total=len(selected),
                delay=args.delay,
            )
            done_chapters.append((list_index, chapter.title))
        except LockedChapterError as exc:
            failures += 1
            print(f"[{position}/{len(selected)}] SKIP chapter {list_index}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"[{position}/{len(selected)}] ERROR chapter {list_index}: {exc}")
    print()
    print(f"[done] {len(selected) - failures} chapter(s) downloaded, {failures} failed")

    if not args.no_epub and done_chapters:
        print()
        print(f"[epub] building '{series.title}.epub' from {len(done_chapters)} chapter(s) ...")
        try:
            folder = series_directory(args.output, series)
            epub_path = build_epub(
                done_chapters,
                folder,
                series.title,
                series.slug,
                author=series.author,
                cover_path=cover_path,
            )
            print(f"  -> {os.path.relpath(epub_path, args.output)}")
        except Exception as exc:
            print(f"  ! EPUB build failed: {exc}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
