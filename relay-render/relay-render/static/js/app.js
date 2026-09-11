/* Same-origin, framework-free UI. Bookmark storage has an in-memory fallback. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const frame = $("content-frame");
  const state = {history: [], index: -1, url: "", title: "", viewing: false, navigation: 0, frameError: false, timer: null, searchController: null, bookmarks: [], storage: true};
  const storageKey = "relay.bookmarks.v1";
  const proxyUrl = (url) => `/proxy?${new URLSearchParams({url})}`;

  function normalizeUrl(raw) {
    let text = String(raw).trim();
    if (!/^[a-z][a-z\d+.-]*:/i.test(text)) text = `https://${text}`;
    const url = new URL(text);
    if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password || url.port || /[\s\\]/.test(text)) {
      throw new Error("Enter a valid HTTP or HTTPS website address without credentials or a custom port.");
    }
    // Normalize common YouTube links. Playback still depends on the site's scripts.
    if (["www.youtube.com", "youtube.com", "m.youtube.com"].includes(url.hostname) && url.pathname === "/watch") {
      const id = url.searchParams.get("v");
      if (id && /^[\w-]{11}$/.test(id)) return `https://www.youtube.com/embed/${id}`;
    }
    if (url.hostname === "youtu.be" && /^[\w-]{11}$/.test(url.pathname.slice(1))) return `https://www.youtube.com/embed/${url.pathname.slice(1)}`;
    return url.href;
  }
  function notice(message) { $("notice").textContent = message; $("notice").hidden = !message; }
  function updateNavigation() {
    $("back").disabled = state.index <= 0;
    $("forward").disabled = state.index >= state.history.length - 1;
    $("refresh").disabled = !state.viewing;
    $("star").disabled = !state.viewing;
    const saved = state.bookmarks.some((b) => b.url === state.url);
    $("star").textContent = saved ? "★" : "☆";
    $("star").classList.toggle("saved", saved);
    $("star").setAttribute("aria-label", saved ? "Remove current bookmark" : "Bookmark current page");
    $("star").setAttribute("aria-pressed", String(saved));
  }
  function hideLoading() { clearTimeout(state.timer); $("loading-overlay").hidden = true; }
  function showViewerError(message, title = "Unable to load page") {
    hideLoading(); $("viewer-error-title").textContent = title; $("viewer-error-message").textContent = message; $("viewer-error").hidden = false;
  }
  function closeImage() { if ($("lightbox").open) $("lightbox").close(); }

  function openPage(raw, addHistory = true) {
    let url;
    try { url = normalizeUrl(raw); } catch (error) { notice(error.message); return false; }
    if (state.searchController) { state.searchController.abort(); state.searchController = null; }
    $("search-progress").hidden = true;
    notice(""); closeImage(); hideLoading();
    state.url = url; state.title = new URL(url).hostname; state.viewing = true; state.navigation++; state.frameError = false;
    if (addHistory) { state.history = state.history.slice(0, state.index + 1); state.history.push(url); state.index = state.history.length - 1; }
    $("address").value = url; $("page-title").textContent = state.title;
    $("search-view").hidden = true; $("viewer").hidden = false; $("viewer-error").hidden = true;
    $("wikipedia-notice").hidden = !/\.m\.wikipedia\.org$/.test(new URL(url).hostname);
    setBookmarksPanel(false); updateNavigation();
    if (/\.(?:jpe?g|png|gif|webp|avif)$/i.test(new URL(url).pathname)) {
      frame.src = "about:blank";
      const filename = new URL(url).pathname.split("/").pop();
      try { $("image-title").textContent = decodeURIComponent(filename); } catch (_) { $("image-title").textContent = filename; }
      $("image-status").textContent = "Loading image…";
      $("lightbox-image").hidden = true;
      $("lightbox-image").src = proxyUrl(url);
      if (typeof $("lightbox").showModal === "function") $("lightbox").showModal();
      else { $("lightbox").setAttribute("open", ""); }
      state.timer = setTimeout(() => { $("image-status").textContent = "Connection slow or blocked. Close this image and try Refresh."; }, 10000);
    } else {
      $("loading-overlay").hidden = false;
      frame.src = `${proxyUrl(url)}&navigation=${state.navigation}`;
      state.timer = setTimeout(() => showViewerError("The gateway or destination has not responded yet. This message will clear if the page arrives.", "Connection slow or blocked"), 10000);
    }
    if (new URL(url).hostname === "www.youtube.com" && new URL(url).pathname.startsWith("/embed/")) {
      notice("Converted to a YouTube embed URL. This HTML reader cannot run the scripts needed for video playback.");
    }
    return true;
  }
  function showHome() {
    state.viewing = false; hideLoading(); closeImage(); frame.src = "about:blank";
    $("viewer").hidden = true; $("search-view").hidden = false; $("address").value = "";
    notice(""); updateNavigation(); $("query").focus();
  }
  $("address-form").addEventListener("submit", (event) => { event.preventDefault(); openPage($("address").value); });
  $("home").addEventListener("click", showHome);
  $("back").addEventListener("click", () => { if (state.index > 0) openPage(state.history[--state.index], false); });
  $("forward").addEventListener("click", () => { if (state.index < state.history.length - 1) openPage(state.history[++state.index], false); });
  $("refresh").addEventListener("click", () => { if (state.viewing) openPage(state.url, false); });
  $("retry").addEventListener("click", () => openPage(state.url, false));
  $("desktop-wikipedia").addEventListener("click", () => { const url = new URL(state.url); url.hostname = url.hostname.replace(".m.wikipedia.org", ".wikipedia.org"); openPage(url.href); });

  // An opaque sandbox reports origin "null"; source identity is the boundary.
  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow || !state.viewing || !event.data || event.data.gateway !== true || event.data.navigation !== String(state.navigation)) return;
    const data = event.data;
    if (data.type === "navigate" && typeof data.url === "string") openPage(data.url);
    if (data.type === "notice" && typeof data.message === "string") notice(data.message);
    if (data.type === "error") { state.frameError = true; showViewerError(data.message || "The destination could not be loaded."); }
    if (data.type === "ready" && data.url) {
      try { state.url = normalizeUrl(data.url); } catch (_) { return; }
      state.history[state.index] = state.url; state.title = data.title || new URL(state.url).hostname;
      $("address").value = state.url; $("page-title").textContent = state.title;
      $("wikipedia-notice").hidden = !/\.m\.wikipedia\.org$/.test(new URL(state.url).hostname);
      hideLoading(); $("viewer-error").hidden = true; updateNavigation();
    }
  });
  frame.addEventListener("error", () => showViewerError("The content frame was blocked or could not load."));
  // Plain text/images have no bridge. The load event also supports restricted browsers.
  frame.addEventListener("load", () => {
    if (state.viewing && frame.getAttribute("src") !== "about:blank") { hideLoading(); if (!state.frameError) $("viewer-error").hidden = true; }
  });

  async function runSearch(query) {
    query = String(query).trim();
    if (!query || query.length > 500) throw new Error("Enter a search between 1 and 500 characters.");
    if (state.searchController) state.searchController.abort();
    const controller = new AbortController(); state.searchController = controller;
    showHome(); $("query").value = query;
    $("search-view").classList.add("has-results"); $("results").replaceChildren();
    $("results-heading").hidden = true; $("search-progress").hidden = false;
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(`/search?${new URLSearchParams({q: query})}`, {signal: controller.signal});
      if (response.status === 401) throw new Error("Gateway authentication expired. Reload this page and enter your gateway key.");
      const results = await response.json();
      if (!response.ok) throw new Error(results.error || "Search is unavailable. Try again later.");
      if (!Array.isArray(results)) throw new Error("The search service returned an invalid response.");
      $("results-heading").textContent = results.length ? `${results.length} RESULTS` : "NO RESULTS · TRY ANOTHER SEARCH";
      $("results-heading").hidden = false;
      results.forEach((result) => {
        // textContent prevents search result HTML from becoming executable markup.
        const card = document.createElement("button"); card.className = "result-card"; card.type = "button";
        const icon = document.createElement("span"); icon.className = "result-icon";
        const img = document.createElement("img"); img.alt = ""; img.loading = "lazy";
        img.src = result.favicon; img.addEventListener("error", () => { icon.textContent = "◎"; }, {once: true}); icon.append(img);
        const copy = document.createElement("span"); copy.className = "result-copy";
        const title = document.createElement("h2"); title.textContent = result.title;
        const url = document.createElement("div"); url.className = "result-url"; url.textContent = result.url;
        const snippet = document.createElement("p"); snippet.textContent = result.snippet;
        const arrow = document.createElement("span"); arrow.className = "result-arrow"; arrow.textContent = "↗";
        copy.append(title, url, snippet); card.append(icon, copy, arrow);
        card.addEventListener("click", () => openPage(result.url)); $("results").append(card);
      });
      return {count: results.length, query};
    } catch (error) {
      if (state.searchController === controller) notice(error.name === "AbortError" ? "Search timed out. Try again or open a URL directly." : error.message);
      throw error;
    } finally {
      clearTimeout(timeout);
      if (state.searchController === controller) { $("search-progress").hidden = true; state.searchController = null; }
    }
  }
  $("search-form").addEventListener("submit", (event) => { event.preventDefault(); runSearch($("query").value).catch(() => {}); });

  function validBookmarks(value) {
    const list = Array.isArray(value) ? value : value && value.bookmarks;
    if (!Array.isArray(list) || list.length > 500) throw new Error("Use a JSON array with up to 500 bookmarks.");
    const unique = new Map();
    list.forEach((item) => {
      if (!item || typeof item.url !== "string" || typeof item.title !== "string" || item.title.length > 500 || item.url.length > 8192) throw new Error("Each bookmark needs a valid title and URL.");
      const url = normalizeUrl(item.url); unique.set(url, {url, title: item.title || new URL(url).hostname});
    });
    return [...unique.values()];
  }
  function saveBookmarks() {
    try { localStorage.setItem(storageKey, JSON.stringify(state.bookmarks)); }
    catch (_) { state.storage = false; }
    renderBookmarks(); updateNavigation();
  }
  function renderBookmarks() {
    $("storage-note").textContent = state.storage ? "Saved in this browser." : "Browser storage is unavailable. Export to keep bookmarks after closing this page.";
    $("bookmark-list").replaceChildren(); $("saved-pages").replaceChildren();
    if (!state.bookmarks.length) {
      const empty = document.createElement("p"); empty.className = "small-note"; empty.textContent = "No bookmarks yet. Open a page and select the star in the address bar."; $("bookmark-list").append(empty);
      const tile = document.createElement("div"); tile.className = "saved-empty";
      const icon = document.createElement("span"); icon.textContent = "☆";
      const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = "Keep a good page close.";
      copy.append(title, document.createTextNode("Select the star in the address bar to save it here.")); tile.append(icon, copy); $("saved-pages").append(tile);
    }
    state.bookmarks.forEach((bookmark, index) => {
      const row = document.createElement("div"); row.className = "bookmark-row";
      const open = document.createElement("button"); open.className = "bookmark-open";
      const title = document.createElement("strong"); title.textContent = bookmark.title;
      const url = document.createElement("small"); url.textContent = bookmark.url; open.append(title, url); open.addEventListener("click", () => openPage(bookmark.url));
      const remove = document.createElement("button"); remove.className = "icon-button"; remove.textContent = "×"; remove.setAttribute("aria-label", `Remove ${bookmark.title}`);
      remove.addEventListener("click", (event) => { event.stopPropagation(); state.bookmarks = state.bookmarks.filter((b) => b.url !== bookmark.url); saveBookmarks(); });
      row.append(open, remove); $("bookmark-list").append(row);
      if (index < 6) {
        const card = document.createElement("button"); card.className = "saved-card";
        const initial = document.createElement("span"); initial.className = "site-initial"; initial.textContent = new URL(bookmark.url).hostname.replace(/^www\./, "")[0].toUpperCase();
        const text = document.createElement("span"); text.append(title.cloneNode(true), url.cloneNode(true)); card.append(initial, text); card.addEventListener("click", () => openPage(bookmark.url)); $("saved-pages").append(card);
      }
    });
  }
  function setBookmarksPanel(open) {
    $("bookmarks-panel").hidden = !open; $("bookmarks-toggle").setAttribute("aria-expanded", String(open));
    if (open) $("bookmarks-close").focus();
  }
  $("bookmarks-toggle").addEventListener("click", () => setBookmarksPanel($("bookmarks-panel").hidden));
  $("bookmarks-close").addEventListener("click", () => { setBookmarksPanel(false); $("bookmarks-toggle").focus(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setBookmarksPanel(false); });
  document.addEventListener("click", (event) => { if (!$("bookmarks-panel").contains(event.target) && !$("bookmarks-toggle").contains(event.target)) setBookmarksPanel(false); });
  $("star").addEventListener("click", () => {
    if (!state.viewing) return;
    if (state.bookmarks.some((b) => b.url === state.url)) state.bookmarks = state.bookmarks.filter((b) => b.url !== state.url);
    else if (state.bookmarks.length < 500) state.bookmarks.push({url: state.url, title: state.title});
    else { notice("The bookmark limit is 500. Export or remove some pages first."); return; }
    saveBookmarks();
  });
  $("export-bookmarks").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(state.bookmarks, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = "relay-bookmarks.json"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("import-bookmarks").addEventListener("click", () => $("import-file").click());
  $("import-file").addEventListener("change", async (event) => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 1024 * 1024) throw new Error("Bookmark files must be smaller than 1 MB.");
      const imported = validBookmarks(JSON.parse(await file.text()));
      const merged = [...new Map([...state.bookmarks, ...imported].map((b) => [b.url, b])).values()];
      if (merged.length > 500) throw new Error("The combined collection exceeds 500 bookmarks.");
      state.bookmarks = merged; saveBookmarks(); notice(`Imported ${imported.length} bookmarks. Existing pages were merged.`);
    } catch (error) { notice(`Import failed: ${error.message}`); }
    finally { event.target.value = ""; }
  });
  $("close-lightbox").addEventListener("click", closeImage);
  $("lightbox").addEventListener("close", () => { if (!$("lightbox").open && state.viewing && /\.(?:jpe?g|png|gif|webp|avif)$/i.test(new URL(state.url).pathname)) showHome(); });
  $("lightbox-image").addEventListener("load", () => { clearTimeout(state.timer); $("image-status").textContent = ""; $("lightbox-image").hidden = false; });
  $("lightbox-image").addEventListener("error", () => { clearTimeout(state.timer); $("image-status").textContent = "This image could not be loaded through the gateway."; });
  try { state.bookmarks = validBookmarks(JSON.parse(localStorage.getItem(storageKey) || "[]")); localStorage.setItem("relay.storage-test", "1"); localStorage.removeItem("relay.storage-test"); }
  catch (_) { state.storage = false; }
  renderBookmarks(); updateNavigation();
  let lastHealthCheck = 0;
  async function checkHealth() {
    if (document.hidden || Date.now() - lastHealthCheck < 30000) return;
    lastHealthCheck = Date.now();
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 8000);
    try { const response = await fetch("/status", {signal: controller.signal}); if (!response.ok) throw new Error(); const data = await response.json(); if (data.status !== "online") throw new Error(); $("health").textContent = "Gateway online"; $("health").classList.add("online"); }
    catch (_) { $("health").textContent = "Gateway unreachable"; $("health").classList.remove("online"); }
    finally { clearTimeout(timer); }
  }
  // Check on return to the page; no periodic requests that keep free hosting awake.
  checkHealth(); window.addEventListener("focus", checkHealth);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkHealth(); });
  // Optional browser-native agent integration; ordinary browsers simply skip it.
  if (document.modelContext && document.modelContext.registerTool) {
    try { Promise.resolve(document.modelContext.registerTool({name: "search_web", title: "Search through Relay", description: "Search the web through the gateway and display the results.", inputSchema: {type: "object", properties: {query: {type: "string", minLength: 1, maxLength: 500}}, required: ["query"], additionalProperties: false}, annotations: {readOnlyHint: true, untrustedContentHint: true}, execute: async (input) => { if (!input || typeof input.query !== "string") throw new Error("A query is required."); return runSearch(input.query); }})).catch(() => {}); } catch (_) { /* Experimental API unavailable. */ }
  }
})();
