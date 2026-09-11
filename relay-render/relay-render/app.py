"""A bounded, read-only web content gateway. Run with `python app.py`.

Fetched documents are untrusted: scripts are removed and documents run in an
opaque-origin sandbox. Only our small navigation bridge can execute. This is an
HTML reader, not a full remote browser or a login/video tunneling service.
"""
import ipaddress
import re
import secrets
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict, deque
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request, redirect
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection

import config

app = Flask(__name__)
app.config.from_object(config)
config.validate_runtime_settings(app.config)
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024
fetch_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_FETCHES)
cache_lock = threading.Lock()
search_cache = OrderedDict()
rate_lock = threading.Lock()
rate_windows = OrderedDict()
EMBED_COOKIE = "__Host-relay_embed"
EMBED_SESSION_SECONDS = 3600


def frame_ancestors():
    # Google Sites may nest its URL embed in a Google-owned wrapper. Ancestor
    # policy applies to EVERY parent, including the reader's nested content frame.
    if app.config["GOOGLE_SITES_EMBED"]:
        # Google Sites custom-code embeds can add a gstatic loader and a
        # site-specific googleusercontent wrapper between the published Site
        # and Relay. CSP checks every ancestor, so permit those Google origins.
        return "'self' https://*.google.com https://*.googleusercontent.com https://www.gstatic.com"
    return "'self'"


def embed_serializer():
    return URLSafeTimedSerializer(app.config["AUTH_KEY"], salt="relay-embed-session-v1")


def embed_csrf_serializer():
    return URLSafeTimedSerializer(app.config["AUTH_KEY"], salt="relay-embed-form-v1")


def embed_csrf_token(action):
    return embed_csrf_serializer().dumps({"action": action})


def valid_embed_csrf(action):
    try:
        value = embed_csrf_serializer().loads(request.form.get("csrf_token", ""), max_age=600)
        return value == {"action": action}
    except (BadSignature, SignatureExpired):
        return False


def embed_authenticated():
    if not app.config["GOOGLE_SITES_EMBED"] or not app.config["AUTH_KEY"]:
        return False
    try:
        return embed_serializer().loads(request.cookies.get(EMBED_COOKIE, ""),
                                        max_age=EMBED_SESSION_SECONDS) == {"reader": True}
    except (BadSignature, SignatureExpired):
        return False


class GatewayError(Exception):
    """An expected error with a safe public message and HTTP status."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_url(raw):
    """Accept public HTTP(S) URLs on standard ports; never credentials or LAN IPs."""
    if not isinstance(raw, str) or not raw or len(raw) > 8192:
        raise GatewayError("Enter a valid HTTP or HTTPS URL.")
    if any(ord(c) < 33 for c in raw) or "\\" in raw:
        raise GatewayError("URLs cannot contain spaces, control characters, or backslashes.")
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError()
        if parts.username is not None or parts.password is not None:
            raise ValueError()
        port = parts.port
        if port is not None and port != (443 if parts.scheme.lower() == "https" else 80):
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise GatewayError("Private network addresses are not available through this gateway.", 403)
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            addr = None
        if addr is not None and not public_address(addr):
            raise GatewayError("Private network addresses are not available through this gateway.", 403)
        netloc = "[{}]".format(host) if ":" in host else host
        if port:
            netloc += ":{}".format(port)
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, parts.fragment))
    except (ValueError, UnicodeError):
        raise GatewayError("Use an HTTP or HTTPS URL on its standard port, without credentials.")


def public_address(addr):
    # Block IPv4-mapped IPv6 and transition networks as well as LAN/metadata IPs.
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return public_address(addr.ipv4_mapped)
        if addr.sixtofour or addr.teredo or addr in ipaddress.ip_network("64:ff9b::/96"):
            return False
    return addr.is_global and not addr.is_multicast


class PublicConnectionMixin:
    def _new_conn(self):
        """Resolve once, validate every address, then connect to that exact IP.

        Keeping the original connection hostname preserves TLS SNI, certificate
        verification and Host. Pinning the socket prevents DNS rebinding between
        a preliminary URL check and Requests' actual connection.
        """
        try:
            records = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(record[4][0] for record in records))
            if not addresses or any(not public_address(ipaddress.ip_address(ip)) for ip in addresses):
                raise GatewayError("The destination resolves to a private or reserved address.", 403)
            # A single attempt keeps connect-timeout behavior predictable.
            return create_connection((addresses[0], self.port), self.timeout,
                                     self.source_address, self.socket_options)
        except OSError as exc:
            raise NewConnectionError(self, "The public destination could not be reached.") from exc


class PublicHTTPConnection(PublicConnectionMixin, HTTPConnection):
    pass


class PublicHTTPSConnection(PublicConnectionMixin, HTTPSConnection):
    pass


class PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = PublicHTTPConnection


class PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = PublicHTTPSConnection


class PublicAdapter(HTTPAdapter):
    """Requests transport adapter with per-instance safe connection pools."""
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": PublicHTTPPool, "https": PublicHTTPSPool}


def fetch_url(raw):
    """Fetch bounded bytes, revalidate redirects, and never forward client cookies."""
    url = validate_url(raw)
    if not fetch_slots.acquire(blocking=False):
        raise GatewayError("The gateway is busy. Try again shortly.", 503)
    try:
        with requests.Session() as session:
            session.trust_env = False  # Ignore ambient proxies and .netrc credentials.
            session.mount("http://", PublicAdapter(max_retries=0))
            session.mount("https://", PublicAdapter(max_retries=0))
            started = time.monotonic()
            for hop in range(config.MAX_REDIRECTS + 1):
                session.cookies.clear()
                with session.get(url, headers={"User-Agent": config.USER_AGENT,
                                              "Accept": "*/*", "Accept-Encoding": "gzip, deflate"},
                                 timeout=config.REQUEST_TIMEOUT, allow_redirects=False, stream=True) as upstream:
                    if upstream.status_code in (301, 302, 303, 307, 308):
                        location = upstream.headers.get("Location")
                        if not location or hop == config.MAX_REDIRECTS:
                            raise GatewayError("The site redirected too many times or sent an invalid redirect.", 502)
                        url = validate_url(urljoin(url, location))
                        continue
                    if upstream.status_code >= 400:
                        raise GatewayError("The website returned HTTP {}. It may block automated access.".format(upstream.status_code), 502)
                    chunks, size = [], 0
                    for chunk in upstream.iter_content(65536):
                        size += len(chunk)
                        if size > config.MAX_RESPONSE_BYTES:
                            raise GatewayError("This resource exceeds the {} MB gateway limit.".format(config.MAX_RESPONSE_BYTES // (1024 * 1024)), 413)
                        if time.monotonic() - started > 30:
                            raise GatewayError("The website took too long to respond.", 504)
                        chunks.append(chunk)
                    return b"".join(chunks), upstream.headers.get("Content-Type", "application/octet-stream"), url, upstream.encoding
        raise GatewayError("The destination could not be fetched.", 502)
    except requests.Timeout:
        raise GatewayError("The website timed out. Try again.", 504)
    except requests.RequestException:
        raise GatewayError("Could not connect securely to the website. It may be offline or block this gateway.", 502)
    finally:
        fetch_slots.release()


@app.before_request
def protect_gateway():
    """Key protection and bounded per-client rate tracking; forwarded IPs are ignored."""
    if request.method == "OPTIONS":
        return Response(status=204)
    # Render cannot supply the reader password to its health checker. This route
    # exposes only process health and never fetches content or returns settings.
    if request.endpoint == "healthz":
        return None
    if app.config["GOOGLE_SITES_EMBED"] and request.endpoint in ("embed", "embed_login", "embed_logout", "static"):
        return None
    key = app.config["AUTH_KEY"]
    if app.config["HOSTED_MODE"] and not key:
        return jsonify(error="Gateway authentication is not configured."), 503
    if key:
        auth = request.authorization
        supplied = request.headers.get("X-Gateway-Key", "")
        if auth and auth.type == "basic":
            supplied = auth.password or ""
        if not secrets.compare_digest(supplied.encode(), key.encode()) and not embed_authenticated():
            if app.config["GOOGLE_SITES_EMBED"]:
                if request.endpoint == "index":
                    return redirect("/embed")
                return jsonify(error="Sign in to Relay again; the embedded session may have expired."), 401
            return Response("Gateway key required. Use any username and your gateway key as the password.",
                            status=401, headers={"WWW-Authenticate": 'Basic realm="Relay", charset="UTF-8"'})
    elif not app.config["ALLOW_UNAUTHENTICATED_REMOTE"]:
        try:
            local = ipaddress.ip_address(request.remote_addr or "").is_loopback
        except ValueError:
            local = False
        if not local:
            return jsonify(error="Set GATEWAY_AUTH_KEY on the home PC to enable remote access."), 403
    if request.endpoint in ("proxy", "search"):
        now, client = time.monotonic(), request.remote_addr
        with rate_lock:
            window = rate_windows.setdefault(client, deque())
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= config.RATE_LIMIT_PER_MINUTE:
                return jsonify(error="Too many requests. Wait a minute and retry."), 429, {"Retry-After": "60"}
            window.append(now)
            rate_windows.move_to_end(client)
            if len(rate_windows) > 1024:
                rate_windows.popitem(last=False)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    if app.config["HOSTED_MODE"]:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors " + frame_ancestors())
    origin = request.headers.get("Origin")
    allowed = app.config["ALLOWED_ORIGINS"]
    if allowed == "*":
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin in [item.strip() for item in allowed.split(",")]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.vary.add("Origin")
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "X-Gateway-Key, Authorization"
    # No Allow-Credentials with wildcard CORS. The UI uses same-origin requests.
    return response


def gateway_origin():
    """Render terminates TLS before Waitress receives HTTP. Use its configured
    public URL, never arbitrary client-supplied X-Forwarded-* headers, for CSP
    and document bases. Local mode continues using the incoming local origin.
    """
    return app.config["PUBLIC_BASE_URL"] or request.host_url.rstrip("/")


def embed_cookie(response, value, max_age):
    # Partitioned cookies work independently under each top-level site. Appending
    # the attribute also supports local Werkzeug releases predating its keyword.
    response.set_cookie(EMBED_COOKIE, value, max_age=max_age, secure=True,
                        httponly=True, samesite="None", path="/")
    response.headers["Set-Cookie"] += "; Partitioned"
    return response


@app.route("/embed")
def embed():
    if not app.config["GOOGLE_SITES_EMBED"]:
        return "Google Sites embedding is not enabled.", 404
    if embed_authenticated():
        return redirect("/")
    return render_template("embed_login.html", message="", standalone_url=gateway_origin(),
                           csrf_token=embed_csrf_token("login"))


@app.route("/embed/login", methods=["POST"])
def embed_login():
    if not app.config["GOOGLE_SITES_EMBED"]:
        return "Google Sites embedding is not enabled.", 404
    # Google Sites deliberately gives custom-code embeds an opaque origin, so
    # browsers send `Origin: null`. A signed one-use-purpose token protects the
    # form without depending on an origin header the embed cannot preserve.
    if not valid_embed_csrf("login"):
        return "This sign-in form expired. Reload the Google Sites page and try again.", 403
    now, client = time.monotonic(), ("embed-login", request.remote_addr)
    with rate_lock:
        window = rate_windows.setdefault(client, deque())
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= 10:
            return render_template("embed_login.html", message="Too many attempts. Wait a minute and try again.",
                                   standalone_url=gateway_origin(), csrf_token=embed_csrf_token("login")), 429
        window.append(now)
        rate_windows.move_to_end(client)
        if len(rate_windows) > 1024:
            rate_windows.popitem(last=False)
    supplied = request.form.get("password", "")
    key = app.config["AUTH_KEY"]
    if not key or not secrets.compare_digest(supplied.encode(), key.encode()):
        return render_template("embed_login.html", message="That password did not match. Try again.",
                               standalone_url=gateway_origin(), csrf_token=embed_csrf_token("login")), 401
    return embed_cookie(redirect("/", code=303), embed_serializer().dumps({"reader": True}), EMBED_SESSION_SECONDS)


@app.route("/embed/logout", methods=["POST"])
def embed_logout():
    if not app.config["GOOGLE_SITES_EMBED"]:
        return "Google Sites embedding is not enabled.", 404
    if not valid_embed_csrf("logout"):
        return "This sign-out form expired. Reload Relay and try again.", 403
    return embed_cookie(redirect("/embed", code=303), "", 0)


def proxy_link(raw, base):
    raw = str(raw).strip()
    if raw.startswith("#"):
        return raw
    try:
        return "/proxy?" + urlencode({"url": validate_url(urljoin(base, raw))})
    except GatewayError:
        return "#"


def rewrite_css(css, base):
    """Rewrite conventional CSS url() and quoted @import resources.

    Complex CSS escapes are intentionally not interpreted. CSP blocks any
    unreplaced off-origin resource instead of letting it bypass the gateway.
    """
    def replace_url(match):
        raw = match.group(2).strip()
        if raw.startswith(("data:image/", "data:font/", "#")):
            return match.group(0)
        return 'url("{}")'.format(proxy_link(raw, base))
    css = re.sub(r"url\(\s*(['\"]?)(.*?)\1\s*\)", replace_url, css, flags=re.I | re.S)
    return re.sub(r"(@import\s+)(['\"])(.*?)\2", lambda m: m.group(1) + '"' + proxy_link(m.group(3), base) + '"', css, flags=re.I)


def rewrite_html(content, final_url):
    """Remove active upstream content and rewrite document/resource references."""
    soup = BeautifulSoup(content, "html.parser")
    original_base = soup.find("base", href=True)
    base = urljoin(final_url, original_base["href"]) if original_base else final_url
    # All upstream scripts are removed, including frame-busting/window.parent checks.
    for tag in soup.select("script, base, iframe, frame, frameset, object, embed, portal, svg, math"):
        tag.decompose()
    for tag in soup.find_all("meta"):
        if tag.has_attr("http-equiv"):
            tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on") or attr.lower() in ("srcdoc", "nonce", "integrity", "crossorigin", "ping", "autofocus", "formaction", "formtarget", "background", "manifest"):
                del tag[attr]
        if tag.has_attr("target"):
            del tag["target"]
        if tag.has_attr("style"):
            tag["style"] = rewrite_css(tag["style"], base)
        for attr in ("href", "src", "poster", "data-src"):
            if tag.has_attr(attr):
                raw = str(tag[attr])
                if attr == "src" and raw.startswith("data:image/") and not raw.startswith("data:image/svg"):
                    continue
                tag[attr] = proxy_link(raw, base)
        if tag.has_attr("srcset"):
            # Data URLs contain commas; use the normal src fallback for those.
            raw = tag["srcset"]
            if "data:" in raw:
                del tag["srcset"]
            else:
                candidates = []
                for candidate in raw.split(","):
                    fields = candidate.strip().split()
                    if fields:
                        candidates.append(" ".join([proxy_link(fields[0], base)] + fields[1:]))
                tag["srcset"] = ", ".join(candidates)
        if tag.name == "link":
            if "stylesheet" not in tag.get("rel", []):
                tag.decompose()
                continue
        if tag.name == "style" and tag.string:
            tag.string.replace_with(rewrite_css(str(tag.string), base))
        if tag.name == "form":
            # Only read-only GET forms are supported by our trusted bridge.
            method = str(tag.get("method", "get")).lower()
            tag["data-gateway-method"] = method
            tag["data-gateway-action"] = urljoin(base, tag.get("action", final_url))
            tag["action"] = "#"
    if not soup.html:
        html = soup.new_tag("html")
        for node in list(soup.contents):
            html.append(node.extract())
        soup.append(html)
    if not soup.head:
        soup.html.insert(0, soup.new_tag("head"))
    # Relative fallbacks stay on the gateway. Rewritten URLs above are root-relative.
    gateway_base = soup.new_tag("base", href=gateway_origin() + "/")
    soup.head.insert(0, gateway_base)
    nonce = secrets.token_urlsafe(24)
    script = soup.new_tag("script", src="/static/js/bridge.js", nonce=nonce)
    script["data-page-url"] = final_url
    script["data-navigation"] = request.args.get("navigation", "")[:100]
    soup.html.append(script)
    return str(soup), nonce


def document_response(html, nonce, status=200):
    response = Response(html, status=status, content_type="text/html; charset=utf-8")
    # Explicit gateway origin works for resource loads from an opaque sandbox.
    origin = gateway_origin()
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'nonce-{}'; style-src {} 'unsafe-inline'; "
        "img-src {} data:; font-src {} data:; media-src {}; connect-src 'none'; "
        "base-uri {}; form-action 'none'; frame-ancestors {}; sandbox allow-scripts allow-forms"
    ).format(nonce, origin, origin, origin, origin, origin, frame_ancestors())
    return response


@app.route("/")
def index():
    embed_session = embed_authenticated()
    return render_template("index.html", auth_enabled=bool(app.config["AUTH_KEY"]),
                           hosted_mode=app.config["HOSTED_MODE"], embed_session=embed_session,
                           logout_csrf_token=embed_csrf_token("logout") if embed_session else "")


@app.route("/proxy")
def proxy():
    content, content_type, final_url, encoding = fetch_url(request.args.get("url", ""))
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in ("text/html", "application/xhtml+xml"):
        html, nonce = rewrite_html(content, final_url)
        return document_response(html, nonce)
    if mime == "text/css":
        return Response(rewrite_css(content.decode(encoding or "utf-8", errors="replace"), final_url), content_type="text/css; charset=utf-8")
    if mime == "image/svg+xml":
        # SVG as an image is useful, but its active features must also be removed.
        if re.search(br"<!\s*(?:DOCTYPE|ENTITY)", content, re.I):
            raise GatewayError("SVG documents with entity declarations are unsupported.", 415)
        try:
            svg = ET.fromstring(content)
        except ET.ParseError:
            raise GatewayError("The website returned an invalid SVG image.", 502)
        unsafe = {"script", "foreignobject", "animate", "set", "animatetransform", "animatemotion"}
        for parent in svg.iter():
            for child in list(parent):
                if child.tag.rsplit("}", 1)[-1].lower() in unsafe:
                    parent.remove(child)
            for attr, value in list(parent.attrib.items()):
                name = attr.rsplit("}", 1)[-1].lower()
                if name.startswith("on") or (name == "href" and not value.startswith("#")):
                    del parent.attrib[attr]
        response = Response(ET.tostring(svg, encoding="utf-8"), content_type="image/svg+xml")
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        return response
    if mime.startswith(("image/", "font/", "audio/", "video/")) or mime in ("application/font-woff", "application/vnd.ms-fontobject", "text/plain"):
        response = Response(content, content_type=content_type)
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
    raise GatewayError("This file type is not supported by the content viewer.", 415)


def parse_search(content):
    soup = BeautifulSoup(content, "html.parser")
    if soup.select_one("#challenge-form, .anomaly-modal") or "anomaly.js" in str(soup):
        raise GatewayError("DuckDuckGo is challenging searches from this server. Try later or open a URL directly.", 503)
    results = []
    for item in soup.select(".result"):
        anchor = item.select_one(".result__a")
        if not anchor or not anchor.get("href"):
            continue
        href = urljoin("https://duckduckgo.com", anchor["href"])
        parsed = urlsplit(href)
        if parsed.hostname in ("duckduckgo.com", "www.duckduckgo.com"):
            href = parse_qs(parsed.query).get("uddg", [href])[0]
        try:
            href = validate_url(href)
        except GatewayError:
            continue
        snippet = item.select_one(".result__snippet")
        results.append({"title": anchor.get_text(" ", strip=True), "url": href,
                        "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                        "favicon": proxy_link("/favicon.ico", href)})
        if len(results) == 20:
            break
    if not results and not soup.select_one(".no-results, .result--no-result"):
        raise GatewayError("Search returned an unexpected page. Try later or open a URL directly.", 502)
    return results


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query or len(query) > 500:
        raise GatewayError("Enter a search between 1 and 500 characters.")
    now = time.monotonic()
    with cache_lock:
        cached = search_cache.get(query)
        if cached and now - cached[0] < config.CACHE_TTL:
            search_cache.move_to_end(query)
            return jsonify(cached[1])
    content, _, _, _ = fetch_url("https://duckduckgo.com/html/?" + urlencode({"q": query}))
    results = parse_search(content)
    with cache_lock:
        search_cache[query] = (time.monotonic(), results)
        search_cache.move_to_end(query)
        while len(search_cache) > config.CACHE_MAX_ENTRIES:
            search_cache.popitem(last=False)
    return jsonify(results)


@app.route("/status")
def status():
    return jsonify(status="online", timestamp=datetime.now(timezone.utc).isoformat())


@app.route("/healthz")
def healthz():
    """Unauthenticated liveness probe for Render, independent of search providers."""
    return jsonify(status="ok")


@app.errorhandler(GatewayError)
def gateway_error(error):
    if request.endpoint == "proxy":
        nonce = secrets.token_urlsafe(24)
        html = render_template("proxy_error.html", message=str(error), nonce=nonce,
                               navigation=request.args.get("navigation", "")[:100])
        return document_response(html, nonce, error.status)
    return jsonify(error=str(error)), error.status


if __name__ == "__main__":
    if config.DEBUG:
        # Development is loopback only; never expose an interactive debugger.
        app.run(host="127.0.0.1", port=config.HOME_PORT, debug=True, use_debugger=False)
    else:
        print("Relay: {} (listening on 0.0.0.0:{})".format(
            config.PUBLIC_BASE_URL or "http://127.0.0.1:{}".format(config.HOME_PORT), config.HOME_PORT), flush=True)
        if sys.version_info < (3, 9):
            # Current Waitress requires 3.9; use a maintained WSGI alternative on 3.8.
            from cheroot.wsgi import Server
            Server(("0.0.0.0", config.HOME_PORT), app, numthreads=12, timeout=40).start()
        else:
            from waitress import serve
            serve(app, host="0.0.0.0", port=config.HOME_PORT, threads=12, channel_timeout=40)
