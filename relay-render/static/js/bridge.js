/* The only script allowed inside a fetched page. Upstream scripts are removed. */
(() => {
  "use strict";
  const script = document.currentScript;
  const pageUrl = script.dataset.pageUrl;
  const tellParent = (payload) => window.parent.postMessage({gateway: true, navigation: script.dataset.navigation, ...payload}, "*");
  // No secrets are included in messages; the outer UI verifies event.source.
  tellParent({type: script.dataset.error ? "error" : "ready", url: pageUrl,
    title: document.title, message: script.dataset.error});
  document.addEventListener("click", (event) => {
    const anchor = event.target.closest("a[href], area[href]");
    if (!anchor) return;
    const href = anchor.getAttribute("href");
    if (!href || href.startsWith("#")) return;
    event.preventDefault();
    const destination = new URL(href, document.baseURI).searchParams.get("url");
    if (destination) tellParent({type: "navigate", url: destination});
  });
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    if (form.dataset.gatewayMethod !== "get") {
      tellParent({type: "notice", message: "This reader supports search forms only. Sign-ins and other submissions are unavailable."});
      return;
    }
    try {
      const target = new URL(form.dataset.gatewayAction);
      target.search = new URLSearchParams(new FormData(form)).toString();
      if (event.submitter && event.submitter.name) target.searchParams.append(event.submitter.name, event.submitter.value);
      tellParent({type: "navigate", url: target.href});
    } catch (_) { tellParent({type: "notice", message: "This form cannot be opened in the reader."}); }
  });
})();
