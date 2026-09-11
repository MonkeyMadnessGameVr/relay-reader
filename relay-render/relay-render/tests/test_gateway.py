"""Deterministic regression checks; no third-party network requests are made."""
import base64
import os
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import app as gateway


class GatewayTests(unittest.TestCase):
    def setUp(self):
        gateway.app.config.update(TESTING=True, AUTH_KEY="", ALLOW_UNAUTHENTICATED_REMOTE=False,
                                  HOSTED_MODE=False, PUBLIC_BASE_URL="", DEBUG=False)
        gateway.search_cache.clear()
        gateway.rate_windows.clear()
        self.client = gateway.app.test_client()

    def test_interface_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/status").json["status"], "online")
        self.assertIn("timestamp", self.client.get("/status").json)

    def test_public_urls_and_unsafe_urls(self):
        self.assertEqual(gateway.validate_url("https://example.com"), "https://example.com/")
        for url in ("file:///etc/passwd", "javascript:alert(1)", "http://127.0.0.1", "http://10.0.0.1", "http://169.254.169.254/", "http://[::1]", "http://[::ffff:127.0.0.1]", "http://user:pass@example.com", "https://example.com:8443", "https://local.local", "https://example.com\\@localhost", "https://example.com/\n"):
            with self.subTest(url=url), self.assertRaises(gateway.GatewayError):
                gateway.validate_url(url)

    def test_remote_requires_key_and_header_auth(self):
        self.assertEqual(self.client.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.5"}).status_code, 403)
        gateway.app.config["AUTH_KEY"] = "test-key"
        self.assertEqual(self.client.get("/status").status_code, 401)
        self.assertEqual(self.client.get("/status", headers={"X-Gateway-Key": "test-key"}).status_code, 200)
        auth = base64.b64encode(b"home:test-key").decode()
        self.assertEqual(self.client.get("/", headers={"Authorization": "Basic " + auth}).status_code, 200)

    def test_preflight_and_cors(self):
        response = self.client.options("/search", headers={"Origin": "https://client.example"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_dns_pinning_and_mixed_private_answers(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch("app.socket.getaddrinfo", return_value=public), patch("app.create_connection") as connect:
            gateway.PublicHTTPSConnection("example.com", 443)._new_conn()
            self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 443))
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch("app.socket.getaddrinfo", return_value=public + private), patch("app.create_connection") as connect:
            with self.assertRaises(gateway.GatewayError):
                gateway.PublicHTTPSConnection("example.com", 443)._new_conn()
            connect.assert_not_called()

    def test_redirect_to_private_ip_is_blocked(self):
        response = MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/private"})
        response.__enter__.return_value = response
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        with patch("app.requests.Session", return_value=session):
            with self.assertRaises(gateway.GatewayError):
                gateway.fetch_url("https://example.com")
            self.assertEqual(session.get.call_count, 1)

    def test_size_limit_and_timeout(self):
        response = MagicMock(status_code=200, headers={"Content-Type": "text/html"})
        response.__enter__.return_value = response
        response.iter_content.return_value = [b"12345"]
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        with patch("app.requests.Session", return_value=session), patch("app.config.MAX_RESPONSE_BYTES", 4):
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.fetch_url("https://example.com")
            self.assertEqual(caught.exception.status, 413)
        with patch("app.requests.Session", return_value=session):
            session.get.side_effect = gateway.requests.Timeout()
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.fetch_url("https://example.com")
            self.assertEqual(caught.exception.status, 504)

    def test_rewrite_and_script_isolation(self):
        html = '''<html><head><base href="https://cdn.example.org/docs/"><meta http-equiv="refresh" content="0;url=https://evil.example"><style>p{background:url('../a.png')}</style></head><body onload="evil()"><script>window.parent.evil()</script><iframe src="https://evil.example"></iframe><a href="next?a=1&b=2" target="_top" ping="https://evil.example">Next</a><img src="image.png" srcset="small.png 1x, big.png 2x"><form method="get" action="/find"><input name="q"></form><p style="background:url(/bg.png)">Hello</p></body></html>'''
        with patch("app.fetch_url", return_value=(html.encode(), "text/html", "https://example.com/start", "utf-8")):
            response = self.client.get("/proxy?url=https://example.com")
        soup = BeautifulSoup(response.data, "html.parser")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(soup.find_all("script")), 1)
        self.assertEqual(soup.script["src"], "/static/js/bridge.js")
        self.assertIn("sandbox allow-scripts", response.headers["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", response.headers["Content-Security-Policy"])
        self.assertIsNone(soup.iframe)
        self.assertFalse(soup.body.has_attr("onload"))
        self.assertIsNone(soup.find("meta", attrs={"http-equiv": True}))
        target = parse_qs(urlsplit(soup.a["href"]).query)["url"][0]
        self.assertEqual(target, "https://cdn.example.org/docs/next?a=1&b=2")
        self.assertIn("/proxy?", soup.img["srcset"])
        self.assertEqual(soup.form["data-gateway-action"], "https://cdn.example.org/find")

    def test_resource_types_and_css(self):
        with patch("app.fetch_url", return_value=(b"PNG", "image/png", "https://example.com/a.png", None)):
            response = self.client.get("/proxy?url=https://example.com/a.png")
            self.assertEqual(response.data, b"PNG")
            self.assertEqual(response.mimetype, "image/png")
        css = '@import "theme.css"; a{background:url(../i.png)}'
        rewritten = gateway.rewrite_css(css, "https://example.com/css/main.css")
        self.assertEqual(rewritten.count("/proxy?"), 2)
        with patch("app.fetch_url", return_value=(b"evil()", "application/javascript", "https://example.com/a.js", None)):
            self.assertEqual(self.client.get("/proxy?url=https://example.com/a.js").status_code, 415)

    def test_svg_active_content_removed(self):
        svg = b'<svg><script>evil()</script><foreignObject>HTML</foreignObject><image href="https://evil.example/a" onload="evil()"/><path d="M0 0"/></svg>'
        with patch("app.fetch_url", return_value=(svg, "image/svg+xml", "https://example.com/a.svg", None)):
            response = self.client.get("/proxy?url=https://example.com/a.svg")
        self.assertNotIn(b"evil", response.data)
        self.assertIn("sandbox", response.headers["Content-Security-Policy"])

    def test_search_parsing_cache_and_expiration(self):
        html = b'<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Example title</a><div class="result__snippet">A helpful snippet</div></div>'
        with patch("app.fetch_url", return_value=(html, "text/html", "https://duckduckgo.com", None)) as fetch:
            first = self.client.get("/search?q=test")
            second = self.client.get("/search?q=test")
            self.assertEqual(first.json, second.json)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(first.json[0]["url"], "https://example.com/a")
            self.assertTrue(first.json[0]["favicon"].startswith("/proxy?"))
            gateway.search_cache["test"] = (time.monotonic() - 301, [])
            self.client.get("/search?q=test")
            self.assertEqual(fetch.call_count, 2)

    def test_search_challenge_empty_and_invalid(self):
        with self.assertRaises(gateway.GatewayError) as caught:
            gateway.parse_search(b'<form id="challenge-form"></form>')
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(gateway.parse_search(b'<div class="no-results">Nothing</div>'), [])
        self.assertEqual(self.client.get("/search?q=").status_code, 400)

    def test_proxy_error_is_readable_and_escaped(self):
        with patch("app.fetch_url", side_effect=gateway.GatewayError("Blocked <script>bad</script>", 502)):
            response = self.client.get("/proxy?url=https://example.com")
        self.assertEqual(response.status_code, 502)
        self.assertIn(b"&lt;script&gt;", response.data)
        self.assertIn(b"data-error=", response.data)

    def test_rate_limit(self):
        with patch("app.config.RATE_LIMIT_PER_MINUTE", 1):
            self.client.get("/search?q=")
            response = self.client.get("/search?q=")
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "60")

    def test_render_health_is_public_but_content_requires_auth(self):
        gateway.app.config.update(HOSTED_MODE=True, AUTH_KEY="test-only-password-12345",
                                  PUBLIC_BASE_URL="https://relay-test.onrender.com")
        self.assertEqual(self.client.get("/healthz").json, {"status": "ok"})
        for path in ("/", "/status", "/search?q=test", "/proxy?url=https://example.com", "/static/js/app.js"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        response = self.client.get("/", headers={"X-Gateway-Key": "test-only-password-12345"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hosted on Render", response.data)
        self.assertIn("max-age=", response.headers["Strict-Transport-Security"])

    def test_render_https_base_and_csp_ignore_forwarded_headers(self):
        gateway.app.config.update(HOSTED_MODE=True, AUTH_KEY="test-only-password-12345",
                                  PUBLIC_BASE_URL="https://relay-test.onrender.com")
        html = b'<html><head><title>Example</title></head><body><img src="/image.png"><a href="/next">Next</a></body></html>'
        with patch("app.fetch_url", return_value=(html, "text/html", "https://example.com", None)):
            response = self.client.get("/proxy?url=https://example.com", base_url="http://internal-render-host",
                                       headers={"X-Gateway-Key": "test-only-password-12345",
                                                "X-Forwarded-Proto": "http", "X-Forwarded-Host": "evil.example"})
        soup = BeautifulSoup(response.data, "html.parser")
        self.assertEqual(soup.base["href"], "https://relay-test.onrender.com/")
        csp = response.headers["Content-Security-Policy"]
        self.assertIn("img-src https://relay-test.onrender.com", csp)
        self.assertNotIn("http://", csp)
        self.assertNotIn("evil.example", csp)
        self.assertEqual(soup.script["src"], "/static/js/bridge.js")

    def test_hosted_mode_never_allows_missing_key(self):
        gateway.app.config.update(HOSTED_MODE=True, ALLOW_UNAUTHENTICATED_REMOTE=True)
        self.assertEqual(self.client.get("/").status_code, 503)

    def test_hosted_startup_rejects_insecure_settings(self):
        settings = dict(gateway.app.config, HOSTED_MODE=True, AUTH_KEY="test-only-password-12345",
                        PUBLIC_BASE_URL="https://relay-test.onrender.com")
        gateway.config.validate_runtime_settings(settings)
        for override in ({"AUTH_KEY": ""}, {"AUTH_KEY": "short"}, {"PUBLIC_BASE_URL": ""},
                         {"DEBUG": True}, {"ALLOW_UNAUTHENTICATED_REMOTE": True}):
            with self.subTest(override=override), self.assertRaises(RuntimeError):
                gateway.config.validate_runtime_settings(dict(settings, **override))

    def test_public_origin_must_be_safe_https(self):
        for origin in ("http://relay.onrender.com", "https://user:pass@example.com", "https://example.com/path",
                       "https://example.com?secret=value", "https://example.com/#fragment", "https://example.com\n", "https://example.com;script-src"):
            with self.subTest(origin=origin), self.assertRaises(RuntimeError):
                gateway.config.validate_runtime_settings(dict(gateway.app.config, PUBLIC_BASE_URL=origin))

    def test_render_environment_selects_port_origin_and_limits(self):
        environment = dict(os.environ, RENDER="true", PORT="12345", HOME_PORT="5000",
                           RENDER_EXTERNAL_URL="https://relay-test.onrender.com", PUBLIC_BASE_URL="https://relay-test.onrender.com")
        result = subprocess.run([sys.executable, "-c", "import config; print(config.HOME_PORT, config.HOSTED_MODE, config.PUBLIC_BASE_URL, config.MAX_RESPONSE_BYTES, config.MAX_CONCURRENT_FETCHES)"],
                                env=environment, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "12345 True https://relay-test.onrender.com 4194304 2")


if __name__ == "__main__":
    unittest.main()
