const SUPPORTED_SITE_HOST = /(^|\.)(?:libread|freewebnovel)\.com$/i;

function seriesPageFromTab(tabUrl) {
  if (!tabUrl) return "";
  try {
    const url = new URL(tabUrl);
    if (url.protocol !== "https:" || !SUPPORTED_SITE_HOST.test(url.hostname)) return "";
    if (!/^\/libread\/[^/]+(?:\/|$)/i.test(url.pathname)) return "";
    return url.href;
  } catch {
    return "";
  }
}

chrome.action.onClicked.addListener((tab) => {
  const seriesUrl = seriesPageFromTab(tab?.url);
  const target = new URL(chrome.runtime.getURL("app.html"));
  if (seriesUrl) target.searchParams.set("url", seriesUrl);
  chrome.tabs.create({ url: target.toString() });
});
