import json
import time
from pathlib import Path

import requests as http_requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Train Seat Map")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

IRCTC_BASE = "https://www.irctc.co.in"

BROWSER_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
}

API_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "user-agent": BROWSER_HEADERS["user-agent"],
    "origin": IRCTC_BASE,
    "referer": f"{IRCTC_BASE}/online-charts/",
    "sec-ch-ua": BROWSER_HEADERS["sec-ch-ua"],
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# ── Shared session with auto cookie fetching ────────────────────────────

session = http_requests.Session()
session.headers.update(BROWSER_HEADERS)
_session_ready = False


def ensure_session():
    """Visit IRCTC pages once to collect session cookies."""
    global _session_ready
    if _session_ready and session.cookies:
        return

    # Hit the online-charts page to pick up cookies
    pages = [
        f"{IRCTC_BASE}/online-charts/",
        f"{IRCTC_BASE}/eticketing/",
    ]
    for url in pages:
        try:
            session.get(url, timeout=15, allow_redirects=True)
        except http_requests.RequestException:
            pass

    _session_ready = True


def get_cookie_status() -> dict:
    """Return current cookie info for debugging."""
    return {
        "count": len(session.cookies),
        "names": list(session.cookies.keys()),
        "ready": _session_ready,
    }


# ── Cache ───────────────────────────────────────────────────────────────
# Train schedule: stable data, cache for 24h
# Train composition: changes once (chart prep), cache for 1h
# Coach composition: stable after chart prep, cache for 1h

_cache: dict[str, tuple[float, dict]] = {}  # key → (expire_time, data)

CACHE_TTL = {
    "schedule": 24 * 3600,   # 24 hours
    "composition": 3600,     # 1 hour
    "coach": 3600,           # 1 hour
}


def cache_get(key: str) -> dict | None:
    """Return cached data if present and not expired."""
    entry = _cache.get(key)
    if entry is None:
        return None
    expire_time, data = entry
    if time.time() > expire_time:
        del _cache[key]
        return None
    return data


def cache_set(key: str, data: dict, ttl_type: str) -> None:
    """Store data in cache with appropriate TTL."""
    ttl = CACHE_TTL.get(ttl_type, 3600)
    _cache[key] = (time.time() + ttl, data)


def _make_cache_key(prefix: str, params: dict) -> str:
    """Create a stable cache key from prefix + sorted params."""
    sorted_items = sorted(params.items())
    return f"{prefix}:{json.dumps(sorted_items)}"


# ── Routes ──────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/cookie-status")
async def cookie_status():
    """Check current session cookie state."""
    return get_cookie_status()


@app.post("/api/refresh-cookies")
async def refresh_cookies():
    """Force re-fetch cookies from IRCTC."""
    global _session_ready
    session.cookies.clear()
    _session_ready = False
    ensure_session()
    status = get_cookie_status()
    if status["count"] == 0:
        return JSONResponse(
            {"error": "Could not fetch cookies from IRCTC. Site may be blocking requests.", **status},
            status_code=502,
        )
    return {"message": f"Fetched {status['count']} cookies", **status}


@app.get("/api/train-schedule/{train_no}")
async def train_schedule(train_no: str):
    """Proxy: fetch train schedule/route from IRCTC."""
    cache_key = f"schedule:{train_no}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["_cached"] = True
        return cached

    ensure_session()

    url = f"{IRCTC_BASE}/eticketing/protected/mapps1/trnscheduleenquiry/{train_no}"
    headers = {**API_HEADERS, "bmirak": "webbm", "greq": str(int(time.time() * 1000))}
    headers.pop("content-type", None)

    try:
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Only cache successful responses (has station list)
        if not data.get("errorMessage") and not data.get("error"):
            cache_set(cache_key, data, "schedule")
        return data
    except http_requests.RequestException as e:
        return JSONResponse({"error": str(e), "cookies": get_cookie_status()}, status_code=502)


@app.post("/api/train-composition")
async def train_composition(request: Request):
    """Proxy: fetch all coaches for a train."""
    body = await request.json()
    cache_key = _make_cache_key("composition", body)
    cached = cache_get(cache_key)
    if cached is not None:
        cached["_cached"] = True
        return cached

    ensure_session()

    url = f"{IRCTC_BASE}/online-charts/api/trainComposition"

    try:
        resp = session.post(url, json=body, headers=API_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("errorMessage") and not data.get("error"):
            cache_set(cache_key, data, "composition")
        return data
    except http_requests.RequestException as e:
        return JSONResponse({"error": str(e), "cookies": get_cookie_status()}, status_code=502)


@app.post("/api/coach-composition")
async def coach_composition(request: Request):
    """Proxy: fetch seat-level data for a specific coach."""
    body = await request.json()
    cache_key = _make_cache_key("coach", body)
    cached = cache_get(cache_key)
    if cached is not None:
        cached["_cached"] = True
        return cached

    ensure_session()

    url = f"{IRCTC_BASE}/online-charts/api/coachComposition"

    try:
        resp = session.post(url, json=body, headers=API_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("errorMessage") and not data.get("error"):
            cache_set(cache_key, data, "coach")
        return data
    except http_requests.RequestException as e:
        return JSONResponse({"error": str(e), "cookies": get_cookie_status()}, status_code=502)


@app.get("/api/cache-stats")
async def cache_stats():
    """Show cache stats for debugging."""
    now = time.time()
    entries = []
    for key, (expire_time, _) in _cache.items():
        remaining = max(0, int(expire_time - now))
        entries.append({"key": key, "ttl_remaining": remaining})
    return {"count": len(_cache), "entries": entries}


@app.post("/api/clear-cache")
async def clear_cache():
    """Clear all cached data."""
    count = len(_cache)
    _cache.clear()
    return {"message": f"Cleared {count} cached entries"}
