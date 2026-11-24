const SITE_ORIGIN = "https://libread.com";
const CHAPTERS_PER_PAGE = 40;
const MAX_SERIES_PAGES = 500;
const MAX_LOG_LINES = 300;
const LIBREAD_HOST = /(^|\.)libread\.com$/i;
const encoder = new TextEncoder();

const $ = (id) => document.getElementById(id);
const state = {
  series: null,
  selected: new Set(),
  coverAsset: null,
  coverPreviewUrl: null,
  jobController: null,
  activeDownloadIds: new Set(),
  jobRunning: false,
  jobLog: [],
  pendingHostPermission: null,
};

const ui = {
  form: $("series-form"),
  url: $("series-url"),
  loadButton: $("load-series"),
  notice: $("notice"),
  workspace: $("workspace"),
  title: $("series-title"),
  author: $("series-author"),
  cover: $("series-cover"),
  coverPlaceholder: $("cover-placeholder"),
  stats: $("series-stats"),
  chapterList: $("chapter-list"),
  chapterSearch: $("chapter-search"),
  selectionCount: $("selection-count"),
  downloadSummary: $("download-summary"),
  downloadButton: $("download-selected"),
  stopButton: $("stop-download"),
  range: $("chapter-range"),
  emptySearch: $("empty-search"),
  lockedNote: $("locked-note"),
  progressPanel: $("progress-panel"),
  jobStatus: $("job-status"),
  progressLabel: $("progress-label"),
  progressTrack: $("progress-track"),
  progressBar: $("progress-bar"),
  progressPercent: $("progress-percent"),
  progressCount: $("progress-count"),
  activityLog: $("activity-log"),
  grantMedia: $("grant-media-access"),
};

ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  void loadSeries();
});
$("select-all").addEventListener("click", () => setAllSelected(true));
$("clear-selection").addEventListener("click", () => setAllSelected(false));
$("apply-range").addEventListener("click", applyRange);
ui.range.addEventListener("keydown", (event) => {
  if (event.key === "Enter") applyRange();
});
ui.chapterSearch.addEventListener("input", renderChapterList);
ui.downloadButton.addEventListener("click", () => void startDownload());
ui.stopButton.addEventListener("click", () => void stopDownload());
$("output-folder").addEventListener("input", updateSelectionView);
$("change-series").addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
  ui.url.focus({ preventScroll: true });
});
$("open-downloads").addEventListener("click", () => {
  if (globalThis.chrome?.tabs?.create) {
    void chrome.tabs.create({ url: "chrome://downloads/" });
  } else {
    showNotice("Open your browser's Downloads page to find saved files.");
  }
});
ui.grantMedia.addEventListener("click", () => void grantPendingMediaPermission());

void initialize();

async function initialize() {
  const queryUrl = new URLSearchParams(window.location.search).get("url");
  if (globalThis.chrome?.storage?.local) {
    try {
      const saved = await chrome.storage.local.get([
        "lastUrl", "saveCover", "buildEpub", "delaySeconds", "timeoutSeconds", "retryCount", "outputFolder",
      ]);
      if (saved.saveCover === false) $("save-cover").checked = false;
      if (typeof saved.outputFolder === "string") $("output-folder").value = saved.outputFolder;
      if (saved.buildEpub === false) $("build-epub").checked = false;
      if (Number.isFinite(saved.delaySeconds)) $("delay-seconds").value = String(saved.delaySeconds);
      if (Number.isFinite(saved.timeoutSeconds)) $("timeout-seconds").value = String(saved.timeoutSeconds);
      if (Number.isFinite(saved.retryCount)) $("retry-count").value = String(saved.retryCount);
      ui.url.value = queryUrl || saved.lastUrl || "";
    } catch {
      ui.url.value = queryUrl || "";
    }
  } else {
    ui.url.value = queryUrl || "";
  }
  ["save-cover", "build-epub", "delay-seconds", "timeout-seconds", "retry-count", "output-folder"].forEach((id) => {
    $(id).addEventListener("change", saveSettings);
  });
  if (queryUrl) void loadSeries();
}

async function saveSettings() {
  if (!globalThis.chrome?.storage?.local) return;
  const settings = readSettings();
  try {
    await chrome.storage.local.set({
      lastUrl: ui.url.value.trim(),
      saveCover: $("save-cover").checked,
      buildEpub: $("build-epub").checked,
      delaySeconds: settings.delaySeconds,
      timeoutSeconds: settings.timeoutSeconds,
      retryCount: settings.retryCount,
      outputFolder: normalizeOutputFolder($("output-folder").value),
    });
  } catch {
    // Storage is a convenience; a failure shouldn't block a download.
  }
}

function readSettings() {
  const numberFrom = (id, fallback) => {
    const value = Number($(id).value);
    return Number.isFinite(value) ? value : fallback;
  };
  const delaySeconds = Math.min(60, Math.max(0, numberFrom("delay-seconds", 0.3)));
  const timeoutSeconds = Math.min(300, Math.max(1, numberFrom("timeout-seconds", 30)));
  const retryCount = Math.min(8, Math.max(1, Math.round(numberFrom("retry-count", 3))));
  $("delay-seconds").value = String(delaySeconds);
  $("timeout-seconds").value = String(timeoutSeconds);
  $("retry-count").value = String(retryCount);
  return { delaySeconds, timeoutSeconds, retryCount };
}

async function loadSeries() {
  if (state.jobRunning) {
    showNotice("Stop the current download before loading a different series.", "error");
    return;
  }
  const input = ui.url.value.trim();
  if (!input) {
    showNotice("Enter a LibRead series URL or slug first.", "error");
    ui.url.focus();
    return;
  }

  clearNotice();
  setLoadButtonBusy(true);
  ui.workspace.hidden = true;
  const settings = readSettings();
  try {
    const loaded = await fetchSeries(input, settings, (text) => showNotice(text));
    state.series = loaded;
    state.selected.clear();
    state.coverAsset = null;
    if (state.coverPreviewUrl) URL.revokeObjectURL(state.coverPreviewUrl);
    state.coverPreviewUrl = null;
    await saveSettings();
    renderSeries();
    ui.workspace.hidden = false;
    showNotice(`Loaded ${loaded.chapters.length} chapters from ${loaded.title}.`, "success");
    window.setTimeout(() => {
      if (ui.notice.dataset.kind === "success") clearNotice();
    }, 4200);
    void loadCoverPreview(loaded, settings);
  } catch (error) {
    if (isAbortError(error)) return;
    ui.workspace.hidden = !state.series;
    showNotice(`Couldn't load this series. ${error.message}`, "error");
  } finally {
    setLoadButtonBusy(false);
  }
}

function setLoadButtonBusy(busy) {
  ui.loadButton.disabled = busy || state.jobRunning;
  ui.loadButton.querySelector("span:first-child").textContent = busy ? "Loading…" : "Load series";
  ui.loadButton.querySelector(".button-arrow").textContent = busy ? "···" : "→";
}

function showNotice(message, kind = "info") {
  ui.notice.textContent = message;
  ui.notice.dataset.kind = kind;
  ui.notice.hidden = false;
}

function clearNotice() {
  ui.notice.hidden = true;
  ui.notice.textContent = "";
  delete ui.notice.dataset.kind;
  ui.grantMedia.hidden = true;
  state.pendingHostPermission = null;
}

function showHostPermission(error) {
  state.pendingHostPermission = { host: error.host, pattern: error.pattern };
  showNotice(`External media from ${error.host} needs your permission before it can be fetched for downloads or EPUBs.`, "error");
  ui.grantMedia.textContent = `Allow ${error.host}`;
  ui.grantMedia.hidden = false;
}

async function grantPendingMediaPermission() {
  const pending = state.pendingHostPermission;
  if (!pending) return;
  if (!globalThis.chrome?.permissions?.request) {
    showNotice("This permission can only be granted from the installed browser extension.", "error");
    return;
  }
  try {
    // This call is made directly from the button click so Chromium can present
    // its per-host optional permission prompt.
    const granted = await chrome.permissions.request({ origins: [pending.pattern] });
    if (!granted) {
      showNotice(`Access to ${pending.host} was not granted. You can still download other chapters.`, "error");
      return;
    }
    state.pendingHostPermission = null;
    ui.grantMedia.hidden = true;
    showNotice(`Access granted for ${pending.host}. Retry any chapter that was skipped.`, "success");
    if (state.series?.coverUrl && !state.coverAsset) void loadCoverPreview(state.series, readSettings());
  } catch (error) {
    showNotice(`Couldn't request access for ${pending.host}. ${error.message}`, "error");
  }
}

async function fetchSeries(input, settings, onStatus) {
  const slug = extractSlug(input);
  const chapters = [];
  const seenUrls = new Set();
  let firstPage = null;

  for (let page = 1; page <= MAX_SERIES_PAGES; page += 1) {
    onStatus?.(`Reading chapter list · page ${page}${page > 1 ? ` of up to ${MAX_SERIES_PAGES}` : ""}…`);
    const pageUrl = page === 1
      ? `${SITE_ORIGIN}/libread/${encodeURIComponent(slug)}`
      : `${SITE_ORIGIN}/libread/${encodeURIComponent(slug)}/${page}`;
    const html = await fetchText(pageUrl, settings);
    const parsed = parseSeriesPage(html, slug);
    if (!firstPage) firstPage = parsed;
    if (parsed.chapters.length === 0) break;

    let added = 0;
    for (const chapter of parsed.chapters) {
      if (seenUrls.has(chapter.url)) continue;
      seenUrls.add(chapter.url);
      chapters.push(chapter);
      added += 1;
    }
    if (parsed.chapters.length < CHAPTERS_PER_PAGE || added === 0) break;
  }

  if (!firstPage || chapters.length === 0) {
    throw new Error("No chapter links were found. Check the link, or the site may have changed its page layout.");
  }
  chapters.forEach((chapter, index) => {
    chapter.listIndex = index + 1;
    chapter.key = `${chapter.chapterId}:${index}:${chapter.url}`;
  });
  return { ...firstPage, slug, chapters };
}

function extractSlug(input) {
  const raw = String(input || "").trim();
  if (!raw) throw new Error("A series URL or slug is required.");

  let slug = "";
  if (/^https?:\/\//i.test(raw)) {
    let parsed;
    try {
      parsed = new URL(raw);
    } catch {
      throw new Error("That URL is not valid.");
    }
    if (parsed.protocol !== "https:" || !isLibreadHost(parsed.hostname)) {
      throw new Error("Use an HTTPS URL from libread.com.");
    }
    const match = parsed.pathname.match(/\/libread\/([^/]+)/i);
    if (!match) throw new Error("The URL should point to a LibRead series page (/libread/series-slug).");
    slug = safeDecodeURIComponent(match[1]);
  } else {
    const pathMatch = raw.match(/(?:^|\/)libread\/([^/?#]+)/i);
    slug = pathMatch ? safeDecodeURIComponent(pathMatch[1]) : raw.split(/[/?#]/, 1)[0];
  }

  if (!slug || slug.includes("/") || slug === "." || slug === "..") {
    throw new Error("Couldn't identify a safe series slug from that input.");
  }
  return slug;
}

function safeDecodeURIComponent(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function parseSeriesPage(html, fallbackSlug) {
  const documentPage = new DOMParser().parseFromString(html, "text/html");
  const titleElement = documentPage.querySelector("h1.tit");
  const titleMeta = documentPage.querySelector('meta[property="og:title"]');
  const metaTitle = titleMeta?.getAttribute("content")?.split("|")[0]?.split(" - ")[0]?.trim();
  const title = titleElement?.textContent?.trim() || metaTitle || fallbackSlug;
  const author = documentPage.querySelector('meta[property="og:novel:author"]')?.getAttribute("content")?.trim() || "";
  const cover = findCoverUrl(documentPage);
  const chapterLinks = documentPage.querySelectorAll("ul#idData li a[href*='/chapter-']");
  const chapters = [];

  for (const link of chapterLinks) {
    const chapterUrl = normalizeSiteUrl(link.getAttribute("href"), SITE_ORIGIN);
    if (!chapterUrl) continue;
    const path = new URL(chapterUrl).pathname;
    const idMatch = path.match(/\/chapter-(\d+)\/?$/i);
    chapters.push({
      chapterId: idMatch ? Number(idMatch[1]) : 0,
      title: link.getAttribute("title")?.trim() || link.textContent?.trim() || chapterUrl,
      url: chapterUrl,
      locked: isMarkedLocked(link),
    });
  }
  return { title, author, coverUrl: cover, chapters };
}

function findCoverUrl(documentPage) {
  const meta = documentPage.querySelector('meta[property="og:image"], meta[name="image"]');
  const candidate = meta?.getAttribute("content")?.trim()
    || documentPage.querySelector("img[data-src]")?.getAttribute("data-src")?.trim();
  return candidate ? normalizeMediaUrl(candidate, SITE_ORIGIN) : null;
}

function normalizeSiteUrl(raw, baseUrl) {
  const url = normalizeMediaUrl(raw, baseUrl);
  if (!url) return null;
  return isLibreadHost(new URL(url).hostname) ? url : null;
}

function normalizeMediaUrl(raw, baseUrl) {
  if (!raw) return null;
  try {
    const url = new URL(raw, baseUrl);
    if (url.protocol === "http:" && isLibreadHost(url.hostname)) url.protocol = "https:";
    if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
    return url.href;
  } catch {
    return null;
  }
}

class HostPermissionRequiredError extends Error {
  constructor(url) {
    const parsed = new URL(url);
    super(`Permission is required to read external media from ${parsed.hostname}.`);
    this.name = "HostPermissionRequiredError";
    this.host = parsed.hostname;
    this.pattern = `${parsed.origin}/*`;
  }
}

function isLibreadHost(hostname) {
  return LIBREAD_HOST.test(String(hostname || ""));
}

function isMarkedLocked(link) {
  let node = link;
  for (let depth = 0; node && depth < 3; depth += 1, node = node.parentElement) {
    if (node.getAttribute?.("data-locked") === "true" || node.getAttribute?.("aria-disabled") === "true") return true;
    const classes = typeof node.className === "string" ? node.className : "";
    if (/(^|\s)(locked|is-locked|chapter-locked)(\s|$)/i.test(classes)) return true;
  }
  return false;
}

async function loadCoverPreview(series, settings) {
  if (!series.coverUrl) return null;
  try {
    const resource = await requestBytes(series.coverUrl, { ...settings, retryCount: 1 }, null);
    if (state.series !== series) return null;
    const extension = extensionForResource(series.coverUrl, resource.contentType);
    const contentType = resource.contentType || mimeFromExtension(extension);
    const blob = new Blob([resource.bytes], { type: contentType });
    state.coverAsset = { bytes: resource.bytes, contentType: blob.type, extension };
    state.coverPreviewUrl = URL.createObjectURL(blob);
    ui.cover.src = state.coverPreviewUrl;
    ui.cover.hidden = false;
    ui.coverPlaceholder.hidden = true;
    return state.coverAsset;
  } catch (error) {
    if (state.series === series && error instanceof HostPermissionRequiredError) showHostPermission(error);
    return null;
  }
}

function renderSeries() {
  const series = state.series;
  if (!series) return;
  ui.title.textContent = series.title;
  ui.author.textContent = series.author ? `by ${series.author}` : "";
  ui.author.hidden = !series.author;
  ui.cover.hidden = true;
  ui.cover.removeAttribute("src");
  ui.coverPlaceholder.hidden = false;
  ui.stats.replaceChildren();

  const accessibleCount = series.chapters.filter((chapter) => !chapter.locked).length;
  const lockedCount = series.chapters.length - accessibleCount;
  ui.stats.append(
    makeStat("Total", series.chapters.length),
    makeStat("Accessible", accessibleCount, "accessible"),
  );
  if (lockedCount > 0) ui.stats.append(makeStat("Locked", lockedCount, "locked"));

  ui.workspace.hidden = false;
  ui.chapterSearch.value = "";
  renderChapterList();
  updateSelectionView();
}

function makeStat(label, value, variant = "") {
  const pill = document.createElement("span");
  pill.className = `stat-pill${variant ? ` ${variant}` : ""}`;
  const name = document.createElement("span");
  name.textContent = label;
  const count = document.createElement("strong");
  count.textContent = String(value);
  pill.append(name, count);
  return pill;
}

function renderChapterList() {
  const series = state.series;
  if (!series) return;
  const query = ui.chapterSearch.value.trim().toLocaleLowerCase();
  const fragment = document.createDocumentFragment();
  let visible = 0;

  for (const chapter of series.chapters) {
    if (query && !chapter.title.toLocaleLowerCase().includes(query)) continue;
    visible += 1;
    const row = document.createElement("div");
    row.className = `chapter-row${chapter.locked ? " is-locked" : ""}${state.selected.has(chapter.key) ? " selected" : ""}`;
    row.setAttribute("role", "listitem");

    const number = document.createElement("span");
    number.className = "chapter-number";
    number.textContent = String(chapter.listIndex).padStart(3, "0");
    row.append(number);

    if (!chapter.locked) {
      const checkbox = document.createElement("input");
      checkbox.className = "chapter-check";
      checkbox.type = "checkbox";
      checkbox.checked = state.selected.has(chapter.key);
      checkbox.setAttribute("aria-label", `Select chapter ${chapter.listIndex}: ${chapter.title}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selected.add(chapter.key);
        else state.selected.delete(chapter.key);
        row.classList.toggle("selected", checkbox.checked);
        updateSelectionView();
      });
      row.append(checkbox);
    } else {
      const spacer = document.createElement("span");
      spacer.setAttribute("aria-hidden", "true");
      row.append(spacer);
    }

    const title = document.createElement("span");
    title.className = "chapter-title";
    title.textContent = chapter.title;
    title.title = chapter.title;
    row.append(title);
    if (chapter.locked) {
      const locked = document.createElement("span");
      locked.className = "chapter-lock";
      locked.textContent = "locked";
      row.append(locked);
    }
    fragment.append(row);
  }

  ui.chapterList.replaceChildren(fragment);
  ui.emptySearch.hidden = visible !== 0;
  const hasLocked = series.chapters.some((chapter) => chapter.locked);
  ui.lockedNote.hidden = !hasLocked;
}

function updateSelectionView() {
  const selectedCount = state.selected.size;
  const accessibleCount = state.series?.chapters.filter((chapter) => !chapter.locked).length || 0;
  ui.selectionCount.textContent = `${selectedCount} selected`;
  ui.downloadSummary.textContent = selectedCount
    ? `${selectedCount} chapter${selectedCount === 1 ? "" : "s"} selected · ${accessibleCount} accessible in this series.`
    : `Select one or more of the ${accessibleCount} accessible chapters to get started.`;
  ui.downloadButton.querySelector("span:first-child").textContent = selectedCount
    ? `Download ${selectedCount} chapter${selectedCount === 1 ? "" : "s"}`
    : "Download selected";
  ui.downloadButton.disabled = selectedCount === 0 || state.jobRunning;
  ui.loadButton.disabled = state.jobRunning;
  const rootLabel = $("download-root-label");
  if (rootLabel) rootLabel.textContent = state.series
    ? `${normalizeOutputFolder($("output-folder").value)} / ${sanitizeFilename(state.series.title)}`
    : "LibRead Downloader / series title";
}

function setAllSelected(checked) {
  if (!state.series) return;
  state.selected.clear();
  if (checked) {
    state.series.chapters.filter((chapter) => !chapter.locked).forEach((chapter) => state.selected.add(chapter.key));
  }
  renderChapterList();
  updateSelectionView();
}

function applyRange() {
  if (!state.series) return;
  const accessible = state.series.chapters.filter((chapter) => !chapter.locked);
  const indexes = resolveSelection(ui.range.value, accessible.length);
  if (indexes === null) {
    showNotice("Use a chapter number, a range like 1-12, or 'all'.", "error");
    return;
  }
  state.selected.clear();
  indexes.forEach((index) => state.selected.add(accessible[index].key));
  renderChapterList();
  updateSelectionView();
  clearNotice();
}

function resolveSelection(raw, count) {
  const value = String(raw || "").trim().toLocaleLowerCase();
  if (!value || count < 1) return null;
  if (["all", "a", "*"].includes(value)) return Array.from({ length: count }, (_, index) => index);
  if (/^\d+$/.test(value)) {
    const number = Number(value);
    return number >= 1 && number <= count ? [number - 1] : null;
  }
  const match = value.match(/^(\d+)\s*-\s*(\d+)$/);
  if (!match) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  if (start < 1 || end < start || end > count) return null;
  return Array.from({ length: end - start + 1 }, (_, index) => start - 1 + index);
}

async function startDownload() {
  if (!state.series || state.jobRunning) return;
  const selected = state.series.chapters.filter((chapter) => !chapter.locked && state.selected.has(chapter.key));
  if (selected.length === 0) {
    showNotice("Select at least one accessible chapter.", "error");
    return;
  }

  clearNotice();
  await saveSettings();
  const settings = readSettings();
  const saveCover = $("save-cover").checked && Boolean(state.series.coverUrl);
  const makeEpub = $("build-epub").checked;
  const chapterFolder = sanitizeFilename(state.series.title);
  const outputFolder = normalizeOutputFolder($("output-folder").value);
  const controller = new AbortController();
  state.jobController = controller;
  state.jobRunning = true;
  state.jobLog = [];
  state.activeDownloadIds.clear();
  ui.progressPanel.hidden = false;
  ui.activityLog.replaceChildren();
  ui.stopButton.hidden = false;
  ui.downloadButton.disabled = true;
  ui.loadButton.disabled = true;
  setJobStatus("running", "Running");
  ui.progressTrack.setAttribute("aria-valuenow", "0");

  const hasCoverTask = saveCover;
  const totalUnits = selected.length + (hasCoverTask ? 1 : 0) + (makeEpub ? 1 : 0);
  let completedUnits = 0;
  let completedChapters = 0;
  let failureCount = 0;
  let successCount = 0;
  const successfulChapters = [];
  let coverForEpub = null;

  const refreshProgress = (fraction, label) => {
    const percent = totalUnits > 0 ? ((completedUnits + Math.max(0, Math.min(1, fraction))) / totalUnits) * 100 : 0;
    setProgress(percent, label, completedChapters, selected.length);
  };

  try {
    logMessage(`Preparing ${selected.length} chapter${selected.length === 1 ? "" : "s"} from “${state.series.title}”.`);
    if (saveCover) {
      try {
        refreshProgress(0, "Saving series cover…");
        const asset = state.coverAsset || await requestBytes(state.series.coverUrl, settings, controller.signal);
        if (!asset) throw new Error("The cover image could not be read.");
        coverForEpub = normalizeAsset(asset, state.series.coverUrl);
        await saveBytesAsDownload(
          coverForEpub.bytes,
          coverForEpub.contentType,
          `${baseDownloadFolder(chapterFolder, outputFolder)}/cover${coverForEpub.extension}`,
          controller.signal,
        );
        logMessage("Series cover saved.", "success");
      } catch (error) {
        if (isAbortError(error, controller.signal)) throw error;
        if (error instanceof HostPermissionRequiredError) showHostPermission(error);
        failureCount += 1;
        logMessage(`Cover not saved: ${error.message}`, "warn");
      }
      completedUnits += 1;
      refreshProgress(0, "Cover step complete");
    } else if ($("save-cover").checked && !state.series.coverUrl) {
      logMessage("No cover image was found on the series page.", "warn");
    }

    for (let position = 0; position < selected.length; position += 1) {
      const chapter = selected[position];
      if (controller.signal.aborted) throw makeAbortError();
      const chapterNumber = chapter.listIndex;
      const prefix = `[${position + 1}/${selected.length}] Chapter ${String(chapterNumber).padStart(3, "0")}`;
      try {
        if (settings.delaySeconds > 0) {
          refreshProgress(0, `Waiting before ${prefix}…`);
          await sleep(settings.delaySeconds * 1000, controller.signal);
        }
        refreshProgress(0.03, `Fetching ${prefix} · ${chapter.title}`);
        const content = await fetchChapterContent(chapter, settings, controller.signal);
        const folder = `${baseDownloadFolder(chapterFolder, outputFolder)}/Chapter ${String(chapterNumber).padStart(3, "0")}`;
        await saveTextAsDownload(content.html, `${folder}/chapter.html`, controller.signal, "text/html;charset=utf-8");
        await saveTextAsDownload(content.text, `${folder}/chapter.txt`, controller.signal, "text/plain;charset=utf-8");

        const savedImages = [];
        for (let imageIndex = 0; imageIndex < content.imageUrls.length; imageIndex += 1) {
          const imageUrl = content.imageUrls[imageIndex];
          const imageResult = await requestBytes(imageUrl, settings, controller.signal, (loaded, total) => {
            const perImage = total > 0 ? loaded / total : 0.12;
            const fraction = 0.08 + 0.88 * ((imageIndex + perImage) / content.imageUrls.length);
            refreshProgress(fraction, `${prefix} · image ${imageIndex + 1}/${content.imageUrls.length}`);
          }, (message) => logMessage(message, "warn"));
          const asset = normalizeAsset(imageResult, imageUrl);
          const imageName = `page_${String(imageIndex + 1).padStart(3, "0")}${asset.extension}`;
          await saveBytesAsDownload(asset.bytes, asset.contentType, `${folder}/${imageName}`, controller.signal);
          savedImages.push({ ...asset, url: imageUrl, name: imageName });
        }

        const result = {
          listIndex: chapterNumber,
          title: chapter.title,
          html: content.html,
          text: content.text,
          images: savedImages,
        };
        successfulChapters.push(result);
        successCount += 1;
        logMessage(`${prefix} saved${savedImages.length ? ` · ${savedImages.length} image${savedImages.length === 1 ? "" : "s"}` : " · text"}.`, "success");
      } catch (error) {
        if (isAbortError(error, controller.signal)) throw error;
        if (error instanceof HostPermissionRequiredError) showHostPermission(error);
        failureCount += 1;
        logMessage(`${prefix} skipped: ${error.message}`, "error");
      }
      completedChapters += 1;
      completedUnits += 1;
      refreshProgress(0, `${completedChapters}/${selected.length} chapters processed`);
    }

    if (makeEpub) {
      if (successfulChapters.length > 0) {
        try {
          refreshProgress(0, "Building EPUB…");
          logMessage(`Building ${state.series.title}.epub from ${successfulChapters.length} chapter${successfulChapters.length === 1 ? "" : "s"}…`);
          const epub = buildEpub(successfulChapters, state.series, coverForEpub);
          await saveBlobAsDownload(epub, `${baseDownloadFolder(chapterFolder, outputFolder)}/${sanitizeFilename(state.series.title)}.epub`, controller.signal);
          logMessage("EPUB saved.", "success");
        } catch (error) {
          if (isAbortError(error, controller.signal)) throw error;
          failureCount += 1;
          logMessage(`EPUB could not be built: ${error.message}`, "error");
        }
      } else {
        logMessage("No chapters were available for an EPUB.", "warn");
      }
      completedUnits += 1;
    }

    if (controller.signal.aborted) throw makeAbortError();
    const finalMessage = failureCount > 0
      ? `Finished with ${successCount} chapter${successCount === 1 ? "" : "s"} saved and ${failureCount} issue${failureCount === 1 ? "" : "s"}.`
      : `Finished · ${successCount} chapter${successCount === 1 ? "" : "s"} saved.`;
    setProgress(100, finalMessage, completedChapters, selected.length);
    setJobStatus(failureCount > 0 ? "warning" : "done", failureCount > 0 ? "Finished with issues" : "Complete");
    logMessage(finalMessage, failureCount > 0 ? "warn" : "success");
    showNotice(finalMessage, failureCount > 0 ? "error" : "success");
  } catch (error) {
    if (isAbortError(error, controller.signal)) {
      setJobStatus("cancelled", "Stopped");
      setProgress(totalUnits > 0 ? (completedUnits / totalUnits) * 100 : 0, "Stopped by you", completedChapters, selected.length);
      logMessage("Download stopped. Files already saved remain in Downloads.", "warn");
      showNotice("Download stopped. Files already saved remain in your Downloads folder.");
    } else {
      setJobStatus("error", "Error");
      setProgress(totalUnits > 0 ? (completedUnits / totalUnits) * 100 : 0, error.message, completedChapters, selected.length);
      logMessage(`Download failed: ${error.message}`, "error");
      showNotice(`Download failed. ${error.message}`, "error");
    }
  } finally {
    state.jobRunning = false;
    state.jobController = null;
    ui.stopButton.hidden = true;
    updateSelectionView();
    setLoadButtonBusy(false);
  }
}

async function stopDownload() {
  const controller = state.jobController;
  if (!controller || controller.signal.aborted) return;
  controller.abort();
  const ids = Array.from(state.activeDownloadIds);
  await Promise.allSettled(ids.map((id) => chrome.downloads.cancel(id)));
}

function baseDownloadFolder(seriesName, outputFolder = normalizeOutputFolder($("output-folder").value)) {
  return `${outputFolder}/${seriesName}`;
}

function normalizeOutputFolder(raw) {
  const segments = String(raw || "")
    .split(/[\\/]+/)
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== "." && segment !== "..");
  return segments.length
    ? segments.map((segment) => sanitizeFilename(segment, 80)).join("/")
    : "LibRead Downloader";
}

async function fetchChapterContent(chapter, settings, signal) {
  const html = await fetchText(chapter.url, settings, signal);
  const parsed = parseChapterHtml(html);
  if (!parsed) {
    throw new Error("No reader article was found. The chapter may be locked, missing, or require site access.");
  }
  return parsed;
}

function parseChapterHtml(html) {
  const documentPage = new DOMParser().parseFromString(html, "text/html");
  const originalArticle = documentPage.querySelector("div#article");
  if (!originalArticle) return null;
  const article = originalArticle.cloneNode(true);

  article.querySelectorAll("script, style, noscript, iframe").forEach((element) => element.remove());
  article.querySelectorAll("div.reader-ad-skip, div.fnw-media").forEach((element) => element.remove());
  article.querySelectorAll("*").forEach((element) => {
    const id = (element.getAttribute("id") || "").toLocaleLowerCase();
    if ((id.startsWith("pf-") || id.startsWith("bg-ssp"))
      && !element.textContent.trim() && !element.querySelector("img")) {
      element.remove();
      return;
    }
    for (const attribute of Array.from(element.attributes)) {
      if (/^on/i.test(attribute.name)) element.removeAttribute(attribute.name);
      if (["href", "src", "xlink:href"].includes(attribute.name.toLocaleLowerCase())
        && /^\s*javascript:/i.test(attribute.value)) element.removeAttribute(attribute.name);
    }
  });

  const imageUrls = [];
  for (const image of article.querySelectorAll("img")) {
    let source = image.getAttribute("src") || image.getAttribute("data-src") || image.getAttribute("data-url");
    if (!source && image.getAttribute("srcset")) {
      source = image.getAttribute("srcset").split(",")[0].trim().split(/\s+/)[0];
    }
    if (!source || /^data:/i.test(source.trim())) continue;
    const imageUrl = normalizeMediaUrl(source.trim(), SITE_ORIGIN);
    if (imageUrl && !imageUrls.includes(imageUrl)) imageUrls.push(imageUrl);
  }

  const contentHtml = article.innerHTML;
  const textRoot = document.createElement("div");
  textRoot.innerHTML = contentHtml;
  textRoot.querySelectorAll("br").forEach((element) => element.replaceWith(document.createTextNode("\n")));
  textRoot.querySelectorAll("p, h1, h2, h3, h4, h5, h6, div, li, blockquote").forEach((element) => {
    element.append(document.createTextNode("\n"));
  });
  const text = textRoot.textContent
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
  return { html: contentHtml, text, imageUrls };
}

async function fetchText(url, settings, signal = null) {
  const resource = await requestBytes(url, settings, signal);
  const contentType = resource.contentType || "";
  const charset = contentType.match(/charset\s*=\s*["']?([^;"'\s]+)/i)?.[1];
  if (charset) {
    try {
      return new TextDecoder(charset).decode(resource.bytes);
    } catch {
      // Fall back to UTF-8 for unsupported or malformed charset labels.
    }
  }
  return new TextDecoder("utf-8").decode(resource.bytes);
}

async function requestBytes(url, settings, signal = null, onProgress = null, onRetry = null) {
  let remote;
  try {
    remote = new URL(url);
  } catch {
    throw new Error("The page returned an invalid resource URL.");
  }
  if (remote.protocol !== "https:" || remote.username || remote.password || remote.port) {
    throw new Error("Only secure HTTPS media URLs are supported.");
  }
  if (!isLibreadHost(remote.hostname)) {
    const pattern = `${remote.origin}/*`;
    let granted = false;
    if (globalThis.chrome?.permissions?.contains) {
      try {
        granted = await chrome.permissions.contains({ origins: [pattern] });
      } catch {
        granted = false;
      }
    }
    if (!granted) throw new HostPermissionRequiredError(remote.href);
  }

  const attempts = Math.max(1, Math.min(8, Number(settings.retryCount) || 3));
  const timeoutSeconds = Math.max(1, Math.min(300, Number(settings.timeoutSeconds) || 30));
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    if (signal?.aborted) throw makeAbortError();
    const controller = new AbortController();
    const abortFromJob = () => controller.abort();
    signal?.addEventListener("abort", abortFromJob, { once: true });
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutSeconds * 1000);

    try {
      const response = await fetch(remote.href, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        referrer: `${SITE_ORIGIN}/`,
        referrerPolicy: "strict-origin-when-cross-origin",
        headers: {
          Accept: "text/html,application/xhtml+xml,image/avif,image/webp,image/apng,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.9",
        },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`LibRead returned HTTP ${response.status}.`);

      const contentType = response.headers.get("content-type") || "";
      const total = Number(response.headers.get("content-length")) || 0;
      const chunks = [];
      let loaded = 0;
      if (response.body) {
        const reader = response.body.getReader();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value?.byteLength) {
            chunks.push(value);
            loaded += value.byteLength;
            onProgress?.(loaded, total);
          }
        }
      } else {
        const bytes = new Uint8Array(await response.arrayBuffer());
        chunks.push(bytes);
        loaded = bytes.byteLength;
        onProgress?.(loaded, total);
      }
      const bytes = new Uint8Array(loaded);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      onProgress?.(loaded, total || loaded);
      return { bytes, contentType, totalBytes: total || loaded };
    } catch (error) {
      if (signal?.aborted) throw makeAbortError();
      if (timedOut) {
        lastError = new Error(`Request timed out after ${timeoutSeconds} seconds.`);
      } else if (error instanceof TypeError && /failed to fetch|networkerror/i.test(error.message)) {
        lastError = new Error(`The browser couldn't reach ${remote.hostname}. Check the extension's site access for libread.com; LibRead may also be blocking extension requests. (${error.message})`);
      } else {
        lastError = error;
      }
      if (attempt < attempts) {
        onRetry?.(`Retry ${attempt}/${attempts - 1} · ${lastError.message}`);
        await sleep(350 * attempt, signal);
      }
    } finally {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener("abort", abortFromJob);
    }
  }
  throw new Error(`${lastError?.message || "Request failed."} (${attempts} attempt${attempts === 1 ? "" : "s"}).`);
}

async function saveTextAsDownload(text, filename, signal, mimeType) {
  await saveBlobAsDownload(new Blob([text], { type: mimeType }), filename, signal);
}

async function saveBytesAsDownload(bytes, contentType, filename, signal) {
  const blob = new Blob([bytes], { type: contentType || "application/octet-stream" });
  await saveBlobAsDownload(blob, filename, signal);
}

async function saveBlobAsDownload(blob, filename, signal) {
  if (signal?.aborted) throw makeAbortError();
  const objectUrl = URL.createObjectURL(blob);
  if (!globalThis.chrome?.downloads?.download) {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename.split("/").pop() || "download";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    return;
  }

  let downloadId = null;
  try {
    downloadId = await chrome.downloads.download({
      url: objectUrl,
      filename,
      conflictAction: "uniquify",
      saveAs: false,
    });
    state.activeDownloadIds.add(downloadId);
    if (signal?.aborted) {
      await chrome.downloads.cancel(downloadId).catch(() => {});
      throw makeAbortError();
    }
    await waitForDownload(downloadId, signal);
  } catch (error) {
    if (isAbortError(error, signal)) throw makeAbortError();
    throw new Error(`Browser download failed for ${filename.split("/").pop()}: ${error.message || error}`);
  } finally {
    if (downloadId !== null) state.activeDownloadIds.delete(downloadId);
    URL.revokeObjectURL(objectUrl);
  }
}

function waitForDownload(downloadId, signal) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      chrome.downloads.onChanged.removeListener(onChanged);
      signal?.removeEventListener("abort", onAbort);
    };
    const finish = (error = null) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error);
      else resolve();
    };
    const onChanged = (delta) => {
      if (delta.id !== downloadId) return;
      if (delta.state?.current === "complete") finish();
      else if (delta.state?.current === "interrupted") {
        finish(new Error(delta.error?.current || "The browser interrupted the download."));
      }
    };
    const onAbort = () => {
      void chrome.downloads.cancel(downloadId).catch(() => {});
      finish(makeAbortError());
    };

    chrome.downloads.onChanged.addListener(onChanged);
    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });
    chrome.downloads.search({ id: downloadId }).then((items) => {
      if (settled || !items?.length) return;
      if (items[0].state === "complete") finish();
      else if (items[0].state === "interrupted") finish(new Error(items[0].error || "The browser interrupted the download."));
    }).catch((error) => finish(new Error(error.message || "Could not check download status.")));
  });
}

function normalizeAsset(asset, url) {
  const extension = asset.extension || extensionForResource(url, asset.contentType);
  return {
    bytes: asset.bytes,
    contentType: asset.contentType || mimeFromExtension(extension),
    extension,
  };
}

function extensionFromUrl(url) {
  try {
    const pathname = new URL(url).pathname;
    const match = pathname.match(/\.([a-z0-9]{1,6})$/i);
    if (match) return `.${match[1].toLowerCase()}`;
  } catch {
    // Use the response type or a safe default for unusual URLs.
  }
  return "";
}

function extensionForResource(url, contentType = "") {
  const pathExtension = extensionFromUrl(url);
  if (pathExtension) return pathExtension;
  const mime = String(contentType).split(";")[0].trim().toLocaleLowerCase();
  const extensionByMime = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
  };
  return extensionByMime[mime] || ".jpg";
}

function mimeFromExtension(extension) {
  return ({
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
  })[extension] || "application/octet-stream";
}

function sanitizeFilename(name, maxLength = 115) {
  let safe = String(name || "untitled")
    .normalize("NFKC")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
    .replace(/[. ]+$/g, "")
    .trim();
  if (!safe) safe = "untitled";
  if (/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i.test(safe)) safe = `_${safe}`;
  return safe.slice(0, maxLength).replace(/[. ]+$/g, "") || "untitled";
}

function setJobStatus(stateName, label) {
  ui.jobStatus.dataset.state = stateName;
  ui.jobStatus.textContent = label;
}

function setProgress(percent, label, completedChapters, totalChapters) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  ui.progressBar.style.width = `${value}%`;
  ui.progressTrack.setAttribute("aria-valuenow", String(Math.round(value)));
  ui.progressPercent.textContent = `${Math.round(value)}%`;
  ui.progressLabel.textContent = label;
  ui.progressCount.textContent = `${completedChapters} / ${totalChapters} chapters`;
}

function logMessage(message, kind = "normal") {
  state.jobLog.push({ message: String(message), kind });
  if (state.jobLog.length > MAX_LOG_LINES) state.jobLog.shift();
  const item = document.createElement("li");
  item.dataset.kind = kind;
  item.textContent = String(message);
  ui.activityLog.append(item);
  while (ui.activityLog.children.length > MAX_LOG_LINES) ui.activityLog.firstElementChild.remove();
  ui.activityLog.scrollTop = ui.activityLog.scrollHeight;
}

function sleep(milliseconds, signal = null) {
  if (signal?.aborted) return Promise.reject(makeAbortError());
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(makeAbortError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function makeAbortError() {
  return new DOMException("The download was stopped.", "AbortError");
}

function isAbortError(error, signal = null) {
  return Boolean(signal?.aborted || error?.name === "AbortError");
}

function buildEpub(chapters, series, coverAsset = null) {
  const zip = new StoredZip();
  const bookFolder = "OEBPS";
  const cssPath = `${bookFolder}/styles.css`;
  const manifest = [
    '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
    `<item id="styles" href="styles.css" media-type="text/css"/>`,
  ];
  const spine = [];
  const navItems = [];
  zip.add("mimetype", "application/epub+zip");
  zip.add("META-INF/container.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>');
  zip.add(cssPath, "body{font-family:serif;line-height:1.65;margin:5%;color:#222}h1.chapter-title{text-align:center;font-size:1.65em;line-height:1.25;margin:0 0 2em;font-weight:700}.image-page{margin:0 0 1em;text-align:center;page-break-after:always}.image-page img{max-width:100%;max-height:100vh;object-fit:contain}.text-content img{max-width:100%;height:auto}");

  if (coverAsset?.bytes?.length) {
    const extension = coverAsset.extension || ".jpg";
    const filename = `images/cover${extension}`;
    zip.add(`${bookFolder}/${filename}`, coverAsset.bytes);
    manifest.push(`<item id="cover-image" href="${escapeXml(filename)}" media-type="${mimeFromExtension(extension)}" properties="cover-image"/>`);
    zip.add(`${bookFolder}/cover.xhtml`, `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title><meta charset="utf-8"/><link rel="stylesheet" type="text/css" href="styles.css"/></head><body><div class="cover"><img src="${escapeXml(filename)}" alt="${escapeXml(series.title)}" style="max-width:100%;max-height:95vh;display:block;margin:auto"/></div></body></html>`);
    manifest.push('<item id="cover-page" href="cover.xhtml" media-type="application/xhtml+xml"/>');
    spine.push('<itemref idref="cover-page" linear="no"/>');
  }

  for (let index = 0; index < chapters.length; index += 1) {
    const chapter = chapters[index];
    const number = String(index + 1).padStart(3, "0");
    const itemId = `chapter-${index + 1}`;
    const href = `${itemId}.xhtml`;
    let body = "";

    if (chapter.images?.length) {
      const imageMarkup = [];
      for (let pageIndex = 0; pageIndex < chapter.images.length; pageIndex += 1) {
        const image = chapter.images[pageIndex];
        const ext = image.extension || extensionFromUrl(image.url);
        const imageHref = `images/chapter-${number}-page-${String(pageIndex + 1).padStart(3, "0")}${ext}`;
        zip.add(`${bookFolder}/${imageHref}`, image.bytes);
        manifest.push(`<item id="image-${number}-${pageIndex + 1}" href="${escapeXml(imageHref)}" media-type="${mimeFromExtension(ext)}"/>`);
        imageMarkup.push(`<div class="image-page"><img src="${escapeXml(imageHref)}" alt="${escapeXml(`${chapter.title} page ${pageIndex + 1}`)}"/></div>`);
      }
      body = `<div class="image-chapter">${imageMarkup.join("")}</div>`;
    } else {
      body = `<div class="text-content">${serializeXhtmlFragment(chapter.html || "")}</div>`;
    }

    if (!startsWithTitleHeading(chapter.html || "", chapter.title)) {
      body = `<h1 class="chapter-title">${escapeXml(chapter.title)}</h1>${body}`;
    }
    const chapterDocument = `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>${escapeXml(chapter.title)}</title><meta charset="utf-8"/><link rel="stylesheet" type="text/css" href="styles.css"/></head><body>${body}</body></html>`;
    zip.add(`${bookFolder}/${href}`, chapterDocument);
    manifest.push(`<item id="${itemId}" href="${href}" media-type="application/xhtml+xml"/>`);
    spine.push(`<itemref idref="${itemId}"/>`);
    navItems.push(`<li><a href="${href}">${escapeXml(chapter.title)}</a></li>`);
  }

  const title = escapeXml(series.title || "LibRead book");
  const author = escapeXml(series.author || "Unknown");
  const identifier = globalThis.crypto?.randomUUID
    ? `urn:uuid:${crypto.randomUUID()}`
    : `urn:uuid:${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const modified = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const navigation = `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>${title}</title><meta charset="utf-8"/></head><body><nav epub:type="toc" id="toc"><h1>Contents</h1><ol>${navItems.join("")}</ol></nav></body></html>`;
  const packageDocument = `<?xml version="1.0" encoding="UTF-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="en"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">${escapeXml(identifier)}</dc:identifier><dc:title>${title}</dc:title><dc:language>en</dc:language><dc:creator>${author}</dc:creator><meta property="dcterms:modified">${modified}</meta></metadata><manifest>${manifest.join("")}</manifest><spine>${spine.join("")}</spine></package>`;
  zip.add(`${bookFolder}/nav.xhtml`, navigation);
  zip.add(`${bookFolder}/content.opf`, packageDocument);
  return zip.toBlob();
}

function startsWithTitleHeading(contentHtml, title) {
  if (!contentHtml || !String(title || "").trim()) return false;
  const page = new DOMParser().parseFromString(`<div id="epub-fragment">${contentHtml}</div>`, "text/html");
  const root = page.getElementById("epub-fragment");
  const heading = root?.querySelector("h1, h2, h3, h4, h5, h6");
  if (!heading || normalizeText(heading.textContent) !== normalizeText(title)) return false;
  const walker = page.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let textNode;
  while ((textNode = walker.nextNode())) {
    if (heading.contains(textNode)) break;
    if (textNode.textContent.trim()) return false;
  }
  return true;
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function serializeXhtmlFragment(contentHtml) {
  const page = new DOMParser().parseFromString(`<div id="epub-fragment">${contentHtml}</div>`, "text/html");
  const root = page.getElementById("epub-fragment");
  if (!root) return "";
  const allowed = new Set([
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "strong", "em", "b", "i",
    "u", "sub", "sup", "small", "ul", "ol", "li", "blockquote", "a", "span", "div",
    "table", "tr", "td", "th", "thead", "tbody", "figure",
  ]);
  return Array.from(root.childNodes).map((node) => serializeXhtmlNode(node, allowed)).join("");
}

function serializeXhtmlNode(node, allowed) {
  if (node.nodeType === Node.TEXT_NODE) return escapeXml(node.nodeValue || "");
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const tag = node.tagName.toLocaleLowerCase();
  const children = Array.from(node.childNodes).map((child) => serializeXhtmlNode(child, allowed)).join("");
  if (!allowed.has(tag)) return children;
  const attributes = [];
  if (tag === "a") {
    const href = node.getAttribute("href") || "";
    if (/^(https?:\/\/|mailto:|#)/i.test(href)) {
      attributes.push(` href="${escapeXml(href)}"`);
    }
  }
  if (["td", "th"].includes(tag)) {
    for (const name of ["colspan", "rowspan"]) {
      const value = node.getAttribute(name);
      if (/^\d{1,3}$/.test(value || "")) attributes.push(` ${name}="${value}"`);
    }
  }
  if (tag === "br" || tag === "hr") return `<${tag}${attributes.join("")}/>`;
  return `<${tag}${attributes.join("")}>${children}</${tag}>`;
}

function escapeXml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

class StoredZip {
  constructor() {
    this.localParts = [];
    this.centralParts = [];
    this.offset = 0;
    this.entries = 0;
  }

  add(name, content) {
    const nameBytes = encoder.encode(name);
    const bytes = content instanceof Uint8Array ? content : encoder.encode(String(content));
    const crc = crc32(bytes);
    const date = dosDate(new Date());
    const time = dosTime(new Date());
    const localHeader = concatBytes([
      u32(0x04034b50), u16(20), u16(0x0800), u16(0), u16(time), u16(date), u32(crc),
      u32(bytes.byteLength), u32(bytes.byteLength), u16(nameBytes.byteLength), u16(0),
      nameBytes,
    ]);
    this.localParts.push(localHeader, bytes);

    const centralHeader = concatBytes([
      u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0), u16(time), u16(date), u32(crc),
      u32(bytes.byteLength), u32(bytes.byteLength), u16(nameBytes.byteLength), u16(0), u16(0),
      u16(0), u16(0), u32(0), u32(this.offset), nameBytes,
    ]);
    this.centralParts.push(centralHeader);
    this.offset += localHeader.byteLength + bytes.byteLength;
    this.entries += 1;
  }

  toBlob() {
    const centralDirectory = concatBytes(this.centralParts);
    const end = concatBytes([
      u32(0x06054b50), u16(0), u16(0), u16(this.entries), u16(this.entries),
      u32(centralDirectory.byteLength), u32(this.offset), u16(0),
    ]);
    return new Blob([...this.localParts, centralDirectory, end], { type: "application/epub+zip" });
  }
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (let index = 0; index < bytes.length; index += 1) {
    crc = CRC_TABLE[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    table[index] = value >>> 0;
  }
  return table;
})();

function concatBytes(parts) {
  const length = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const output = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.byteLength;
  }
  return output;
}

function u16(number) {
  return Uint8Array.of(number & 0xff, (number >>> 8) & 0xff);
}

function u32(number) {
  return Uint8Array.of(number & 0xff, (number >>> 8) & 0xff, (number >>> 16) & 0xff, (number >>> 24) & 0xff);
}

function dosDate(date) {
  const year = Math.max(1980, date.getFullYear());
  return ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
}

function dosTime(date) {
  return (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
}
