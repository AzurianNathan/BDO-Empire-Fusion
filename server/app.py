"""
Fused BDO worker-empire app backend.

Serves the Workerman UI when it's built; otherwise serves a self-contained
fallback control panel. Either way it exposes:

  GET  /api/health
  GET  /api/prices/{lang}/{region}            raw market prices (used by the map)
  GET  /api/effective-prices/{region}?tax=..  solver-ready effective prices
  POST /api/optimize                          -> {"job_id"}
  GET  /api/optimize/{job_id}                 -> status / result
  POST /api/optimize/{job_id}/stop
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
from collections import deque
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, field_validator

from bdo_empire.solver_highspy import SolverController
from pipeline import run_optimization

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
DATA_DIR = STATIC_DIR / "data" / "manual"
DEFAULT_TAX = 0.65  # Workerman's default selectedTax
LAST_PRICE_SOURCE = ""   # which upstream URL last served prices
_LAST_FETCH: dict[str, Any] = {}   # {"count": N, "at": epoch} from the last successful fetch_prices()

REGION_MAP = {
    "NA": "na", "EU": "eu", "SEA": "sea", "MENA": "mena", "KR": "kr",
    "RU": "ru", "JP": "jp", "TH": "th", "TW": "tw", "SA": "sa",
    "CONSOLE_EU": "console_eu", "CONSOLE_NA": "console_na", "CONSOLE_ASIA": "console_asia",
}

app = FastAPI(title="bdo-empire-fused")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# StaticFiles serves everything raw with no compression by default. The map's
# own JS bundle and several of its data/*.json files (loc.json,
# all_lodging_storage.json) are multiple MB each and load on every page hit -
# gzip cuts that by ~70-80% for basically free.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def _cache_hashed_assets(request, call_next):
    """StaticFiles sends ETag/Last-Modified but no Cache-Control, so every
    repeat visit revalidates instead of loading from disk cache. /assets/* is
    Vite's build output - each filename is content-hashed
    (index.<hash>.js), so any real change gets a new URL. That makes it safe
    to cache for a year; /data/* and index.html are NOT hash-versioned (they
    can change without a URL change, e.g. re-running build.py), so they're
    deliberately left alone here.
    """
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# --- data files ---------------------------------------------------------------

def _load_json(name: str) -> Any:
    path = DATA_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _market_item_ids() -> list[int]:
    """Ids to price: worker outputs + crafted-price components."""
    ids: set[int] = set()
    try:
        pz = _load_json("plantzone_uniques.json")
        ids.update(int(x) for x in (pz if isinstance(pz, list) else pz.keys()))
    except FileNotFoundError:
        pass
    try:
        calc = _load_json("calculated_prices.json")
        for derived, comps in calc.items():
            ids.add(int(derived))
            ids.update(int(c) for c in comps.keys())
    except FileNotFoundError:
        pass
    ids.add(9492)  # worker feed
    return sorted(ids)


def compute_effective_prices(
    api_prices: dict[str, float],
    vendor_prices: dict[str, float],
    calculated_prices: dict[str, dict[str, float]],
    tax: float,
    keep_items: Optional[dict[str, bool]] = None,
    custom_prices: Optional[dict[str, float]] = None,
) -> dict[str, float]:
    """Port of Workerman's market `prices` getter (string keys throughout)."""
    keep_items = keep_items or {}
    custom_prices = custom_prices or {}
    ret: dict[str, float] = {}
    for k, v in custom_prices.items():
        if v != "":
            ret[str(k)] = v
    for k, v in api_prices.items():
        ret.setdefault(str(k), v)
    for k, v in vendor_prices.items():
        ret.setdefault(str(k), v)
    for k in list(ret.keys()):
        if keep_items.get(k):
            continue
        if k in vendor_prices:
            continue
        ret[k] *= tax
    for k, comps in calculated_prices.items():
        if custom_prices.get(k, "") != "":
            continue
        ret[k] = sum(ret.get(str(c), 0) * qty for c, qty in comps.items())
    return ret


# --- price endpoints ----------------------------------------------------------

def _row_price(row: dict) -> Optional[int]:
    """Current market price from an item row, tolerant of field naming."""
    for field in ("basePrice", "pricePerOne", "lastSoldPrice"):
        v = row.get(field)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


_NAME_CACHE: dict[str, dict[str, str]] = {}


def item_names(lang: str = "en") -> dict[str, str]:
    """Item id -> display name, from Workerman's loc.json."""
    if lang in _NAME_CACHE:
        return _NAME_CACHE[lang]
    try:
        loc = json.loads((STATIC_DIR / "data" / "loc.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    names = loc.get(lang, loc.get("en", {})).get("item", {})
    _NAME_CACHE[lang] = names
    return names


async def _fetch_custom(url_template: str, api_key: str, region: str, lang: str,
                        ids: list[int]) -> dict[str, int]:
    """Fetch from a user-supplied endpoint.

    url_template may contain {region}, {lang} and {ids} placeholders. The api_key,
    if given, is sent as both `Authorization: Bearer <key>` and `x-api-key`.
    The response is parsed leniently: any list of objects (or {"data": [...]}) with
    an id-ish field and a price-ish field is accepted.
    """
    headers = {"User-Agent": "bdo-empire-fused/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    out: dict[str, int] = {}
    id_fields = ("id", "item_id", "itemId", "mainKey", "main_key", "key")
    price_fields = ("basePrice", "price", "pricePerOne", "lastSoldPrice", "unitPrice")
    async with httpx.AsyncClient(timeout=40, headers=headers) as client:
        for i in range(0, len(ids), 500):
            chunk = ",".join(str(x) for x in ids[i : i + 500])
            url = (url_template.replace("{region}", region).replace("{lang}", lang)
                   .replace("{ids}", chunk))
            r = await client.get(url)
            r.raise_for_status()
            body = r.json()
            rows = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                iid = next((row[f] for f in id_fields if f in row), None)
                price = next((row[f] for f in price_fields if f in row), None)
                if iid is None or price is None:
                    continue
                try:
                    out[str(int(iid))] = int(price)
                except (TypeError, ValueError):
                    continue
    return out


def _rows_of(body) -> list:
    rows = body.get("data", body) if isinstance(body, dict) else body
    if isinstance(rows, dict):
        rows = [rows]
    return [r for r in (rows or []) if isinstance(r, dict)]


ID_FIELDS = ("id", "mainKey", "main_key", "item_id", "itemId", "key")


def _row_id(row: dict):
    for f in ID_FIELDS:
        if f in row:
            try:
                return str(int(row[f]))
            except (TypeError, ValueError):
                pass
    return None


def _collect(rows, into: dict[str, int]) -> None:
    for row in rows:
        # base enhancement level only (sid/subKey absent => treat as base)
        sid = row.get("sid", row.get("subKey", 0))
        if str(sid) != "0":
            continue
        iid = _row_id(row)
        if iid is None:
            continue
        price = _row_price(row)
        if price is not None:
            into[iid] = price


# --- api.blackdesertmarket.com -------------------------------------------------
# A live wrapper over the OFFICIAL PA web market API
# (https://eu-trade.naeu.playblackdesert.com/Home). Endpoint shapes taken from the
# maintained `bdomarket` client: GET /item/{id}?region=..&language=..
BDM_BASE = "https://api.blackdesertmarket.com"
BDM_CONCURRENCY = 5        # deliberately gentle: this is a community-run service
BDM_RETRIES = 3
PRICE_CACHE_TTL = 600      # seconds; avoids re-hammering on every page/reload

_PRICE_CACHE: dict[tuple, tuple[float, dict]] = {}


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict):
    """GET with backoff on rate limiting / transient server errors."""
    delay = 0.5
    for _ in range(BDM_RETRIES):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return None                      # 404 etc: item genuinely absent
        except Exception:  # noqa: BLE001
            await asyncio.sleep(delay)
            delay *= 2
    return None


async def fetch_bdm(region: str, lang: str, ids: list[int]) -> dict[str, int]:
    """Fetch from api.blackdesertmarket.com, which fronts the official market.

    Requests are per item, so this is kept deliberately polite: low concurrency,
    backoff on 429/5xx, and a short-lived cache so opening a page or reloading
    prices does not re-issue hundreds of requests.
    """
    global LAST_PRICE_SOURCE
    reg = REGION_MAP.get(region.upper(), region.lower())
    wanted = [str(i) for i in ids]
    key = ("bdm", reg, lang)
    now = time.time()

    cached = _PRICE_CACHE.get(key)
    if cached and (now - cached[0]) < PRICE_CACHE_TTL:
        have = cached[1]
        if all(w in have for w in wanted):
            LAST_PRICE_SOURCE = (f"blackdesertmarket ({len(wanted)}/{len(wanted)}) "
                                 f"cached {int(now - cached[0])}s ago")
            return {w: have[w] for w in wanted}

    out: dict[str, int] = {}
    failed: list[str] = []
    sem = asyncio.Semaphore(BDM_CONCURRENCY)
    headers = {"User-Agent": "bdo-empire-fused/1.0", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        async def one(iid: str):
            async with sem:
                r = await _get_with_retry(client, f"{BDM_BASE}/item/{iid}",
                                          {"region": reg, "language": lang})
                if r is None:
                    failed.append(iid)
                    return
                try:
                    rows = _rows_of(r.json())
                except Exception:  # noqa: BLE001
                    failed.append(iid)
                    return
                got: dict[str, int] = {}
                _collect(rows, got)
                if not got:                  # single-item responses may omit the id
                    for row in rows:
                        price = _row_price(row)
                        if price is not None:
                            got[iid] = price
                            break
                if got:
                    out.update(got)
                else:
                    failed.append(iid)

        await asyncio.gather(*(one(i) for i in wanted))

    if out:
        merged = dict(cached[1]) if cached else {}
        merged.update(out)
        _PRICE_CACHE[key] = (now, merged)
        short = len(wanted) - len(out)
        LAST_PRICE_SOURCE = (f"blackdesertmarket ({len(out)}/{len(wanted)})"
                             + (f" - {short} unpriced, valued at 0: {', '.join(failed[:8])}"
                                + ("..." if len(failed) > 8 else "") if short else ""))
    return out


# --- bdolytics.com --------------------------------------------------------------
# An undocumented internal endpoint bdolytics.com's own frontend calls (found by
# inspecting its network traffic; there is no published API). A single request
# returns the ENTIRE market catalog (thousands of items, all enhancement levels),
# so pricing our ~250 ids costs one call instead of one-per-item. No API key,
# CORS is wide open (access-control-allow-origin: *), and it's fronted by
# Cloudflare's CDN cache rather than a bot-challenge, so plain server-side
# requests get a normal 200 - unlike Garmoth's market API, which sits behind a
# Cloudflare JS challenge that blocks non-browser clients and was ruled out for
# that reason. Verified against known item ids/prices on 2026-07-29.
BDOLYTICS_BASE = "https://bdolytics.com/api/trpc/market.getMarket"
BDOLYTICS_REGION_MAP = {
    "NA": "NA", "EU": "EU", "SEA": "ASIA", "MENA": "MENA", "KR": "KR",
    "RU": "RU", "JP": "JP", "TH": "ASIA", "TW": "TW", "SA": "SA",
    "CONSOLE_EU": "CEU", "CONSOLE_NA": "CNA", "CONSOLE_ASIA": "CAS",
}
BDOLYTICS_CACHE_TTL = 600

_BDOLYTICS_CACHE: dict[str, tuple[float, dict]] = {}


async def fetch_bdolytics(region: str, lang: str, ids: list[int]) -> dict[str, int]:
    """Fetch the whole market catalog from bdolytics.com and pick out our ids.

    One request regardless of how many ids are wanted, since the endpoint
    returns everything; cached so repeated calls in a session cost nothing.
    """
    global LAST_PRICE_SOURCE
    reg = BDOLYTICS_REGION_MAP.get(region.upper(), region.upper())
    now = time.time()

    cached = _BDOLYTICS_CACHE.get(reg)
    if cached and (now - cached[0]) < BDOLYTICS_CACHE_TTL:
        catalog = cached[1]
    else:
        params = {"input": json.dumps({"language": "en", "region": reg})}
        headers = {"User-Agent": "bdo-empire-fused/1.0", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(BDOLYTICS_BASE, params=params)
            r.raise_for_status()
            body = r.json()
        rows = body.get("result", {}).get("data", [])
        catalog = {str(row["itemId"]): row["price"] for row in rows
                  if "itemId" in row and "price" in row}
        if catalog:
            _BDOLYTICS_CACHE[reg] = (now, catalog)

    wanted = [str(i) for i in ids]
    out = {w: catalog[w] for w in wanted if w in catalog}
    if out:
        missing = len(wanted) - len(out)
        LAST_PRICE_SOURCE = (f"bdolytics ({len(out)}/{len(wanted)})"
                             + (f" - {missing} unpriced, valued at 0" if missing else ""))
    return out


class PriceRequest(BaseModel):
    region: str = "EU"
    lang: str = "en"
    tax: float = DEFAULT_TAX
    keepItems: dict[str, bool] = {}
    customPrices: dict[str, float] = {}
    provider: str = "auto"           # auto | bdm | custom
    customUrl: str = ""              # for provider="custom"
    apiKey: str = ""


async def _build_prices(req: PriceRequest) -> dict[str, Any]:
    try:
        vendor = _load_json("vendor_prices.json")
        calculated = _load_json("calculated_prices.json")
    except FileNotFoundError as exc:
        raise HTTPException(500, f"Missing data file: {exc}. Run build.py to fetch game data.") from exc
    ids = _market_item_ids()
    try:
        base = await fetch_prices(req.provider, req.region, req.lang, ids,
                                  req.customUrl, req.apiKey)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Upstream market API error: {exc}") from exc
    if not base:
        raise HTTPException(502, "Price source returned no usable rows (check endpoint/fields).")

    eff = compute_effective_prices(base, vendor, calculated, req.tax,
                                   keep_items=req.keepItems, custom_prices=req.customPrices)
    names = item_names(req.lang)
    rows = []
    for k in sorted(eff.keys(), key=lambda x: names.get(x, "zzz")):
        rows.append({
            "id": k,
            "name": names.get(k, f"Item {k}"),
            "market": base.get(k),
            "vendor": k in vendor,
            "custom": req.customPrices.get(k, ""),
            "keep": bool(req.keepItems.get(k)),
            "effective": round(eff[k], 2),
        })
    return {"effectivePrices": eff, "rows": rows, "count": len(eff),
            "tax": req.tax, "region": req.region,
            "source": LAST_PRICE_SOURCE or ("custom: " + req.customUrl if req.provider == "custom" else "")}


@app.post("/api/effective-prices")
async def effective_prices_post(req: PriceRequest) -> dict[str, Any]:
    return await _build_prices(req)


@app.get("/api/effective-prices/{region}")
async def effective_prices(region: str, lang: str = "en", tax: float = DEFAULT_TAX) -> dict[str, Any]:
    return await _build_prices(PriceRequest(region=region, lang=lang, tax=tax))


# --- optimizer jobs -----------------------------------------------------------

class OptimizeRequest(BaseModel):
    """Optimizer inputs.

    Deliberately tolerant about numbers. Workerman computes crafted prices as
    `ret[component] * qty`; if any component is unpriced that becomes NaN, which
    JSON.stringify serialises as `null`. Under a strict `dict[str, float]` a single
    such entry rejected the entire request with a 422 and the solve never ran. Bad
    entries are now dropped and counted instead, and the count is reported.
    """
    budget: int
    effectivePrices: dict[str, Any] = {}
    farmingWorkerSilverPerDay: Any = 0.0
    droppedPrices: int = 0
    modifiers: Optional[dict] = None
    baseEmpire: Optional[dict] = None
    lodging: Optional[dict] = None
    forcedTaken: Optional[list[int]] = None
    solverOverrides: Optional[dict] = None

    @field_validator("effectivePrices", mode="before")
    @classmethod
    def _clean_prices(cls, v):
        if not isinstance(v, dict):
            return {}
        out: dict[str, float] = {}
        for k, val in v.items():
            try:
                f = float(val)
            except (TypeError, ValueError):
                continue                      # null / NaN / non-numeric
            if math.isfinite(f):
                out[str(k)] = f
        return out

    @field_validator("farmingWorkerSilverPerDay", mode="before")
    @classmethod
    def _clean_farming(cls, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return f if math.isfinite(f) else 0.0

    def dropped(self, raw_count: int) -> int:
        return max(0, raw_count - len(self.effectivePrices))


# --- progress capture ---------------------------------------------------------
# The solver prints its stages ("Generating node values...", data sync, HiGHS
# summary) to the server console. Route them to the running job so the panel can
# show progress instead of an opaque "Solving..." for the length of a solve.
_THREAD_JOB: dict[int, "deque[str]"] = {}


class _Tee:
    """Mirror a stream to the console and to the calling thread's job buffer."""
    def __init__(self, real):
        self._real = real

    def write(self, text):
        try:
            self._real.write(text)
        except Exception:  # noqa: BLE001
            pass
        buf = _THREAD_JOB.get(threading.get_ident())
        if buf is not None:
            for line in text.splitlines():
                if line.strip():
                    buf.append(line.rstrip())

    def flush(self):
        try:
            self._real.flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self):
        return False


sys.stdout = _Tee(sys.stdout)
sys.stderr = _Tee(sys.stderr)

# loguru (used by bdo-empire) binds to the original stderr at import, so it needs
# its own sink to be captured.
try:
    from loguru import logger as _loguru_logger

    def _loguru_sink(message):
        buf = _THREAD_JOB.get(threading.get_ident())
        if buf is not None:
            text = str(message).strip()
            if text:
                buf.append(text)

    _loguru_logger.add(_loguru_sink, format="{message}", level="INFO")
except Exception:  # noqa: BLE001
    pass


class _Job:
    def __init__(self) -> None:
        self.status = "running"
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.controller = SolverController()
        self.lines: "deque[str]" = deque(maxlen=400)


_JOBS: dict[str, _Job] = {}
_LOCK = threading.Lock()


def _run_job(job_id: str, req: OptimizeRequest) -> None:
    job = _JOBS[job_id]
    _THREAD_JOB[threading.get_ident()] = job.lines
    try:
        if req.droppedPrices:
            job.lines.append(
                f"WARNING: {req.droppedPrices} price(s) were not numbers (unpriced "
                f"items produce NaN in Workerman's crafted-price maths). Those items "
                f"are valued at 0 by the solver."
            )
        job.lines.append(f"Optimizing with {len(req.effectivePrices)} priced items, "
                         f"budget {req.budget} CP.")
        job.result = run_optimization(
            budget=req.budget,
            effective_prices=req.effectivePrices,
            farming_worker_silver_per_day=req.farmingWorkerSilverPerDay,
            modifiers=req.modifiers,
            base_empire=req.baseEmpire,
            lodging=req.lodging,
            forced_taken=req.forcedTaken,
            solver_overrides=req.solverOverrides,
            controller=job.controller,
        )
        job.status = "stopped" if job.status == "stopping" else "done"
    except Exception:  # noqa: BLE001
        job.error = traceback.format_exc()
        job.status = "error"
    finally:
        _THREAD_JOB.pop(threading.get_ident(), None)


@app.post("/api/optimize")
async def optimize(req: OptimizeRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = _Job()
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/optimize/{job_id}")
async def optimize_status(job_id: str, since: int = 0) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    lines = list(job.lines)
    payload: dict[str, Any] = {"status": job.status,
                               "lines": lines[since:], "cursor": len(lines)}
    if job.status in ("done", "stopped") and job.result is not None:
        payload["result"] = job.result
    if job.status == "error":
        payload["error"] = job.error
    return payload


@app.post("/api/optimize/{job_id}/stop")
async def optimize_stop(job_id: str) -> dict[str, str]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    job.status = "stopping"
    job.controller.stop()
    return {"status": "stopping"}


PROVIDERS = {
    "bdolytics": ("bdolytics.com (undocumented, full-catalog)", fetch_bdolytics),
    "bdm": ("blackdesertmarket (wraps official PA)", fetch_bdm),
}
# Tried in this order when provider="auto".
#   arsha.io           - removed: reachable, but only serves items already warm in
#                         its own 30-min cache; a fresh lookup for an ordinary
#                         material gets "blocked by Imperva" from PA's own WAF.
#                         Verified 2026-07-29: 4/4 base-level material ids failed.
#   official PA        - removed deliberately: querying Pearl Abyss' own trade
#                         endpoint hundreds of times per refresh is the kind of
#                         traffic that gets an IP or account flagged. Not worth
#                         the risk for price data.
#   garmoth.com         - not usable: its market API is real and current but sits
#                         behind a Cloudflare JS challenge, so plain server-side
#                         requests get a 403. Bypassing that is bot-detection
#                         evasion, which this project won't do.
#   blackdesertmarket   - was the sole source, but died: unreachable (connection
#                         refused/timeout) as of 2026-07-29 from multiple
#                         independent networks. Kept in PROVIDERS for manual
#                         selection/testing but dropped from the auto chain so a
#                         dead TCP connection can't stall a refresh for an hour.
# That leaves bdolytics.com: undocumented, but a single request returns the
# whole catalog, is CDN-cached rather than bot-gated, and checked out clean.
PROVIDER_ORDER = ["bdolytics"]

# Well-known, always-listed items used to compare sources side by side.
async def fetch_prices(provider: str, region: str, lang: str, ids: list[int],
                       custom_url: str = "", api_key: str = "") -> dict[str, int]:
    """Resolve prices via a named provider, a custom endpoint, or the auto chain."""
    global _LAST_FETCH
    if provider == "custom":
        if not custom_url:
            raise HTTPException(400, "Custom provider selected but no endpoint URL given.")
        got = await _fetch_custom(custom_url, api_key, region, lang, ids)
        _LAST_FETCH = {"count": len(got), "at": time.time()}
        return got
    if provider in PROVIDERS:
        got = await PROVIDERS[provider][1](region, lang, ids)
        _LAST_FETCH = {"count": len(got), "at": time.time()}
        return got
    attempts = []
    for key in PROVIDER_ORDER:
        try:
            got = await PROVIDERS[key][1](region, lang, ids)
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{key}: {type(exc).__name__}")
            continue
        if got:
            _LAST_FETCH = {"count": len(got), "at": time.time()}
            return got
        attempts.append(f"{key}: no data")
    raise HTTPException(502, "No price source returned data. Tried -> " + " | ".join(attempts))


COMPARE_IDS = [4001, 5205, 9492]   # Iron Ore, Fruit of Nature, Grilled Bird Meat


async def compare_price_sources(region: str, lang: str) -> list[dict]:
    """Fetch the same few items from every provider so stale data is obvious."""
    names = item_names(lang)
    results = []
    for key in PROVIDERS:
        label, fn = PROVIDERS[key]
        try:
            got = await fn(region, lang, list(COMPARE_IDS))
            results.append({
                "provider": key, "label": label, "ok": bool(got),
                "prices": {names.get(str(i), str(i)): got.get(str(i)) for i in COMPARE_IDS},
                "detail": f"{len(got)}/{len(COMPARE_IDS)} priced" if got else "no data",
            })
        except Exception as exc:  # noqa: BLE001
            results.append({"provider": key, "label": label, "ok": False,
                            "prices": {}, "detail": f"{type(exc).__name__}: {str(exc)[:80]}"})
    return results


@app.get("/api/prices/{lang}/{region}")
async def prices(lang: str, region: str) -> dict[str, Any]:
    """Raw market prices for the Workerman map's own price store.

    Shaped like bdolytics.com's own /api/trpc/market.getMarket response
    ({"result": {"data": [{"itemId": ..., "price": ...}]}}) because upstream
    Workerman's market.js now parses that shape directly (it switched to
    calling bdolytics itself). Matching it here means the patch that redirects
    market.js to this endpoint only needs to change the URL, not the parsing.
    """
    ids = _market_item_ids()
    if not ids:
        raise HTTPException(500, "No item id set; is server/static/data present?")
    base = await fetch_prices("auto", region, lang, ids)
    return {"result": {"data": [{"itemId": int(k), "price": v} for k, v in base.items()]},
            "source": LAST_PRICE_SOURCE}


@app.get("/api/compare-sources/{region}")
async def compare_sources(region: str, lang: str = "en") -> dict[str, Any]:
    return {"region": region, "results": await compare_price_sources(region, lang)}


@app.get("/api/price-status")
async def price_status() -> dict[str, Any]:
    """Coverage of the most recent price fetch.

    The access log only shows that /api/prices returned 200; it cannot show that
    (say) 2 of 248 items came back unpriced. An unpriced item is valued at 0 by the
    solver, so the shortfall is reported here and shown in the UI.
    """
    expected = len(_market_item_ids())
    return {
        "source": LAST_PRICE_SOURCE or "no prices fetched yet",
        "expected": expected,
        "cachedItems": _LAST_FETCH.get("count", 0),
        "cacheAgeSeconds": int(time.time() - _LAST_FETCH["at"]) if _LAST_FETCH else None,
    }


@app.exception_handler(RequestValidationError)
async def _validation_handler(request, exc: RequestValidationError):
    """Log which fields failed so a 422 is never a mystery in the access log."""
    fields = [{"field": ".".join(str(x) for x in e.get("loc", [])), "problem": e.get("msg")}
              for e in exc.errors()]
    print(f"422 on {request.url.path}: " +
          "; ".join(f"{f['field']} -> {f['problem']}" for f in fields[:8]))
    return JSONResponse(status_code=422,
                        content={"detail": "Request validation failed", "fields": fields})


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# --- UI serving (defined after /api so those win) -----------------------------

if (STATIC_DIR / "index.html").exists():
    # full Workerman map build present
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    if (STATIC_DIR / "data").exists():
        app.mount("/data", StaticFiles(directory=str(STATIC_DIR / "data")), name="data")

    @app.get("/")
    async def fallback() -> FileResponse:
        return FileResponse(str(HERE / "fallback.html"))
