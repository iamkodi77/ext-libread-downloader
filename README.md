# LibRead Downloader

A LibRead chapter downloader with two front ends:

1. **Python CLI and local web GUI** — the downloader package and Python app are replicated from the [requested upstream branch](https://github.com/mrcloudworks-glitch/libread-downloader/tree/arena/380f34f2-libread-downloader).
2. **Standalone Chromium browser extension** — a browser-native interface that does not need the Python server or a separate backend.

## Browser extension (Chrome, Edge, Brave)

The extension includes the same practical download tools as the Python GUI: load paginated series listings, search and select individual chapters, select all or a chapter range, save the cover, download text and image-based chapters, build an EPUB, configure request delay/timeout/retries, view live progress and stop a running job.

### Install locally

1. Open `chrome://extensions` in Chrome, Edge, or Brave.
2. Turn on **Developer mode**.
3. Choose **Load unpacked** and select this repository's `browser-extension` folder.
4. Click the LibRead Downloader toolbar button. When you are on a LibRead series page, the extension fills in that page automatically; otherwise paste a series URL or enter its slug.

Downloads are saved in the browser's Downloads folder under `LibRead Downloader/<series>/` by default; the extension lets you choose another relative subfolder. Browser settings may ask you to allow multiple downloads the first time. Keep the extension tab open while a job runs. The extension uses the browser Downloads API and keeps its data local to the browser.

The extension has required access only to HTTPS pages and media on `libread.com` and its subdomains. If a cover or chapter image is hosted on another HTTPS domain, it asks you before requesting access to that specific host; it does not request blanket access to all sites. It does not send login cookies or bypass paid/locked access. If a chapter page has no reader article, it is reported as skipped. Only download material you are authorized to access.

## Python app

Python 3.8+ and the packages in `requirements.txt` are needed. The launch script creates a virtual environment and installs them on first run:

```bash
./run.sh gui                 # local browser GUI at http://127.0.0.1:8902
./run.sh "https://libread.com/libread/series-slug" --all
./run.sh "https://libread.com/libread/series-slug" --range 1-5 --output downloads
```

You can also set up and run it manually:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python libread_gui.py
python libread_dl.py --help
```

The Python GUI lets you load a series, pick chapters, omit the cover or EPUB, watch download progress, and cancel a job. The CLI supports interactive selection plus `--list`, `--all`, `--chapter N`, and `--range A-B`. Files are written under `downloads/` by default.

## Project layout

- `libread/` — Python parsing, HTTP, chapter, download, and EPUB code.
- `libread_dl.py` — command-line interface.
- `libread_gui.py` — local web GUI.
- `browser-extension/` — Manifest V3 Chromium extension; all of its UI and downloader logic runs inside the extension page.
- `tests/` — offline unit tests for selection, parsing, locked-chapter handling, and EPUB output.

Run the Python tests after installing the requirements:

```bash
python -m unittest discover -s tests -v
```
