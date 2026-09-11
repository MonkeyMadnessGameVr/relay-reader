"""Local and Render settings. Secrets belong in environment variables only."""
import os
import re
from urllib.parse import urlsplit

HOSTED_MODE = os.environ.get("RENDER", "false").lower() == "true" or os.environ.get("HOSTED_MODE", "false").lower() == "true"
GOOGLE_SITES_EMBED = os.environ.get("GOOGLE_SITES_EMBED", "false").lower() == "true"
# Render supplies PORT; HOME_PORT remains the local-development fallback.
HOME_PORT = int(os.environ.get("PORT", os.environ.get("HOME_PORT", "5000")))
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0"
# If set, use any username and this key as the HTTP Basic password.
AUTH_KEY = os.environ.get("GATEWAY_AUTH_KEY", "")
# Without a key, only loopback clients are accepted unless explicitly enabled.
ALLOW_UNAUTHENTICATED_REMOTE = os.environ.get("ALLOW_UNAUTHENTICATED_REMOTE", "false").lower() == "true"
REQUEST_TIMEOUT = 15
MAX_RESPONSE_BYTES = (4 if HOSTED_MODE else 12) * 1024 * 1024
MAX_REDIRECTS = 5
CACHE_TTL = 300
CACHE_MAX_ENTRIES = 128
MAX_CONCURRENT_FETCHES = 2 if HOSTED_MODE else 8
RATE_LIMIT_PER_MINUTE = 240


def validate_runtime_settings(settings):
    """Stop a misconfigured hosted deployment before it can become an open proxy."""
    if settings.get("GOOGLE_SITES_EMBED") and (len(settings["AUTH_KEY"]) < 16 or not settings["PUBLIC_BASE_URL"]):
        raise RuntimeError("Google Sites embedding requires a password of at least 16 characters and a public HTTPS URL.")
    if settings["HOSTED_MODE"]:
        if len(settings["AUTH_KEY"]) < 16:
            raise RuntimeError("Set GATEWAY_AUTH_KEY to a new password of at least 16 characters in Render Environment settings.")
        if settings["DEBUG"] or settings["ALLOW_UNAUTHENTICATED_REMOTE"]:
            raise RuntimeError("Hosted mode requires DEBUG=false and ALLOW_UNAUTHENTICATED_REMOTE=false.")
        if not settings["PUBLIC_BASE_URL"]:
            raise RuntimeError("Hosted mode requires RENDER_EXTERNAL_URL or PUBLIC_BASE_URL with the public HTTPS origin.")
    origin = settings["PUBLIC_BASE_URL"]
    if origin:
        try:
            parts = urlsplit(origin)
            valid = (parts.scheme == "https" and parts.hostname
                     and re.fullmatch(r"[A-Za-z0-9.-]+", parts.hostname)
                     and parts.port in (None, 443) and parts.username is None
                     and parts.password is None and not parts.query and not parts.fragment
                     and parts.path in ("", "/") and not any(c.isspace() for c in origin))
        except ValueError:
            valid = False
        if not valid:
            raise RuntimeError("PUBLIC_BASE_URL must be an HTTPS origin such as https://your-service.onrender.com with no path or credentials.")
