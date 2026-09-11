# Relay — a personal web reader

**For the Render setup, start with [RENDER_SETUP.md](RENDER_SETUP.md).** It explains the private GitHub upload, Render deployment, login, and Chromebook test. Once deployed, the home PC and router are not involved. `render.yaml` selects a free Python web service with HTTPS supplied by Render.

Render mode reads `PORT` and `RENDER_EXTERNAL_URL`, requires a password of at least 16 characters, and refuses debug or unauthenticated operation. `/healthz` is a public process-health probe; the reader and `/status` require authentication. Canonical HTTPS base URLs and resource policies work behind Render's TLS terminator without trusting arbitrary forwarded headers. Individual resources are capped at 4 MB with two simultaneous upstream fetches on hosted instances. The interface does not send periodic keep-alive requests.

The included `scripts/package_render.py` creates `dist/Relay-Render.zip` and a clean upload folder from an explicit allowlist; no `.venv`, `.env`, or unrelated local files are included. The hosted service has not been deployed merely by preparing these files.

Validation: 20 automated backend checks cover the original reader plus hosted authentication, health checks, port selection, and HTTPS rewriting. `python tests/render_smoke.py` starts a temporary real server in Render mode, checks authenticated access, fetches `https://example.com`, and shuts it down. This local smoke check passed; actual Render deployment and Chromebook access still need the account setup and device test in the guide.

The sections below describe the alternative local/home-PC setup. **Skip home-router forwarding when using Render.**

A Flask application that fetches public web pages on its server, rewrites their links and resources, and displays them in a dark, responsive reader. All interface scripts, styles, and fonts are served by the app. Your existing `OmniSearch.html` is preserved separately in the original workspace.

## Install and run

Python 3.8+ is supported by the dependency constraints; a currently supported Python release is recommended. The implementation is validated with Python 3.13. Dependencies are installed in `.venv` in this checkout.

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

On macOS or Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open [the local gateway](http://127.0.0.1:5000). The default server is **Waitress**, listening on `0.0.0.0:5000`. Python 3.8 uses Cheroot because current Waitress requires Python 3.9+. Only Python 3.13 was available for runtime testing. `python app.py` uses Flask's development server only when `DEBUG=true`, and then binds to loopback with the interactive debugger disabled. Flask explicitly recommends a production WSGI server for deployment: [Flask deployment documentation](https://flask.palletsprojects.com/en/stable/deploying/).

## Remote access from a Chromebook

1. Stop the server with Ctrl+C. Choose a long, unique gateway key and set it in the same terminal before starting again:

   ```powershell
   $env:GATEWAY_AUTH_KEY = 'replace-with-a-long-random-key'
   .\.venv\Scripts\python.exe app.py
   ```

   On macOS/Linux: `export GATEWAY_AUTH_KEY='replace-with-a-long-random-key'`, then `python app.py`. Environment settings here last for that terminal session. The browser's HTTP Basic prompt accepts any username and the key as its password. API clients can instead send `X-Gateway-Key`. Never include the key in URLs or bookmarks.

2. Give the home PC a stable LAN address using your router's DHCP reservation setting. Allow inbound TCP 5000 to this Python process in the host firewall.
3. Configure the router to forward **external TCP 5000 → the home PC's internal IP, TCP 5000**.
4. From a different network, visit `http://your-public-ip:5000`. Substitute your actual public IP. The home PC must stay awake and the process must remain running.

**Public deployment requires HTTPS:** the requested HTTP address is useful for connectivity testing but transmits the key, URLs, and content without encryption. For ongoing remote use, place a TLS reverse proxy in front of Waitress with a certificate trusted by the Chromebook, and forward the TLS port to that proxy. Restrict direct access to port 5000 in that configuration. Keep the gateway key enabled even behind a reverse proxy; the application deliberately does not trust forwarded client-IP headers.

Router/firewall settings, TLS, a public IP, and Chromebook access cannot be configured or verified from this project alone. Carrier-grade NAT or double NAT may prevent inbound forwarding; ask your ISP about a reachable public address. A managed device/network can still block the gateway address, custom ports, iframes, or JavaScript. A home gateway cannot override those device policies.

Without a key, the app accepts only loopback clients. `ALLOW_UNAUTHENTICATED_REMOTE=true` explicitly permits unauthenticated remote access, but is intended only for a controlled network: forwarding that configuration publicly creates an open proxy.

## Features

- `/`: Jinja2 interface with address bar, back/forward stack, refresh, home, and status.
- `/proxy?url=https%3A%2F%2Fexample.com`: HTTP(S) fetching with a 15-second connect/read timeout, URL validation, checked redirects, and a custom Requests adapter. HTML links, stylesheet URLs, image sources, `srcset`, posters, and conventional CSS imports/URLs are rewritten through the gateway. The source page's base URL is respected before a gateway base tag is injected.
- `/search?q=example`: DuckDuckGo HTML result titles, URLs, snippets, and proxied favicon URLs as a JSON array. Results have a thread-safe five-minute cache, bounded to 128 queries. Challenges and provider-layout changes produce explicit errors rather than fabricated or silently empty results.
- `/status`: `{"status":"online","timestamp":"...+00:00"}`. With authentication enabled, this route also requires the key.
- Navigation inside fetched pages updates the address bar and the app's own history. GET search forms work through a small trusted bridge. Browser back/forward history is independent.
- YouTube watch and short links are normalized to embed URLs. **Playback is not supported** by this HTML reader because upstream JavaScript is stripped.
- Mobile Wikipedia pages offer a desktop URL. URLs ending in JPG/JPEG, PNG, GIF, WebP, or AVIF open in an image lightbox, including URLs with query strings.
- Bookmarks live on the client. Star to add/remove, open the dropdown to manage, and export/import JSON. Imports merge by URL. Storage failures use in-memory bookmarks; export before closing to retain them.

Bookmark interchange format (an object with a `bookmarks` array is also accepted):

```json
[
  {"title": "Example", "url": "https://example.com/"}
]
```

## Configuration

Edit `config.py` or set its documented environment overrides:

| Setting | Default | Meaning |
| --- | --- | --- |
| `HOME_PORT` | `5000` | Listening port |
| `DEBUG` | `false` | Loopback-only development mode |
| `GATEWAY_AUTH_KEY` | empty | HTTP Basic password / API key |
| `ALLOW_UNAUTHENTICATED_REMOTE` | `false` | Explicit opt-in for remote access without a key |
| `ALLOWED_ORIGINS` | `*` | CORS wildcard or comma-separated allowed origins |

The UI always uses same-origin requests. CORS does not enable cross-network reachability or override device restrictions, and wildcard CORS does not allow credentialed cross-origin browser access. There are no outbound browser CDN or Google Fonts requests.

## Security and practical limits

- Only public HTTP and HTTPS destinations on standard ports are accepted. Private, loopback, link-local, reserved, multicast, and common IPv6 transition addresses are blocked. DNS is checked at socket creation and the selected IP is pinned; every redirect is validated. This prevents access through the proxy to your router and local services.
- Outbound TLS certificate verification remains enabled. Environment proxies and `.netrc` are ignored; gateway credentials, incoming headers, and browser cookies are never forwarded to destination sites. [Requests transport adapters and timeouts](https://requests.readthedocs.io/en/stable/user/advanced/) describe the underlying client behavior.
- Fetched scripts, event handlers, nested frames, active embeds, refresh metadata, and inline SVG/MathML are removed. A nonce-authorized bridge is the only fetched-document script. The iframe and response CSP use an opaque-origin sandbox without `allow-same-origin`; content cannot access the parent DOM or bookmark storage. Resource CSP prevents unrewritten external loads.
- This is a **read-only HTML content gateway**, not a full browser, CONNECT proxy, VPN, or streaming relay. JavaScript apps, sign-ins, POST forms, DRM/video playback, nested embeds, downloads, and some CSS constructs are unsupported. Websites can reject server-side requests. The reader preserves ordinary HTML/CSS where possible; it cannot promise that every page renders identically.
- Responses are limited to 12 MB after decompression, eight simultaneous upstream fetches, five redirects, and 240 proxy/search requests per client per minute. Timeouts are socket timeouts; a 30-second elapsed check also runs during body reads. OS DNS resolution and an in-progress socket read can extend total elapsed time. The UI shows its slow-connection message after ten seconds and recovers if a response arrives.
- Cache/rate state is in process memory, appropriate to this single home-PC process. Restarting clears it. No remote activity or bookmarks are stored in a database.
- Basic authentication has no custom logout button; close the browser session to clear its remembered credentials. Use HTTPS whenever authentication travels over an untrusted network.

## Project layout and checks

```text
app.py                    Routes, fetching, rewriting, authentication, cache
config.py                 Environment-based settings
requirements.txt          Python dependencies, including production WSGI server
templates/index.html      Main Jinja2 template
templates/proxy_error.html Safe error document for the iframe
static/css/style.css      Responsive dark theme
static/js/app.js           Navigation, search, bookmarks, image viewer
static/js/bridge.js        Trusted iframe navigation bridge
static/favicon.svg        Local application icon
tests/test_gateway.py     Network-independent regression checks
```

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/js/app.js
node --check static/js/bridge.js
```

The optional feature-detected `search_web` WebMCP tool calls the same search flow as the visible form. No browser extension is required to use the app.
