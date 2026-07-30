"""Tests for fetch_bdolytics() and the fetch_prices() dispatcher, with the
outbound HTTP call replaced by an httpx.MockTransport - no real network
access, and the exact scenario that caused today's silent multi-hour hangs
(a dead source, a partial catalog) is reproducible on demand.
"""
import asyncio
import json

import httpx
import pytest

import app as app_module


def _install_transport(monkeypatch, handler):
    """Force every httpx.AsyncClient app.py constructs to route through a mock
    transport. fetch_bdolytics() builds its own client internally rather than
    accepting an injectable one, so this patches the httpx.AsyncClient
    constructor itself for the duration of the test."""
    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory)


def test_fetch_bdolytics_picks_out_requested_ids(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"result": {"data": [
            {"itemId": 100, "price": 500},
            {"itemId": 200, "price": 1000},
            {"itemId": 300, "price": 1500},
        ]}})
    _install_transport(monkeypatch, handler)

    out = asyncio.run(app_module.fetch_bdolytics("EU", "en", [100, 200, 999]))

    assert out == {"100": 500, "200": 1000}   # 999 absent, not zero-filled


def test_fetch_bdolytics_maps_region_to_bdolytics_enum(monkeypatch):
    seen = {}

    def handler(request):
        seen["region"] = json.loads(request.url.params["input"])["region"]
        return httpx.Response(200, json={"result": {"data": []}})
    _install_transport(monkeypatch, handler)

    # SEA isn't a valid bdolytics region enum value - it maps to ASIA
    # (confirmed against the real API's own error message during development).
    asyncio.run(app_module.fetch_bdolytics("SEA", "en", [1]))

    assert seen["region"] == "ASIA"


def test_fetch_bdolytics_caches_within_ttl(monkeypatch):
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        return httpx.Response(200, json={"result": {"data": [{"itemId": 1, "price": 10}]}})
    _install_transport(monkeypatch, handler)

    asyncio.run(app_module.fetch_bdolytics("EU", "en", [1]))
    asyncio.run(app_module.fetch_bdolytics("EU", "en", [1]))

    assert call_count["n"] == 1   # second call served from _BDOLYTICS_CACHE


def test_fetch_bdolytics_reports_source_and_shortfall(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"result": {"data": [{"itemId": 1, "price": 10}]}})
    _install_transport(monkeypatch, handler)

    asyncio.run(app_module.fetch_bdolytics("EU", "en", [1, 2]))

    assert app_module.LAST_PRICE_SOURCE == "bdolytics (1/2) - 1 unpriced, valued at 0"


def test_fetch_prices_named_provider_bypasses_auto_chain(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"result": {"data": [{"itemId": 1, "price": 99}]}})
    _install_transport(monkeypatch, handler)

    out = asyncio.run(app_module.fetch_prices("bdolytics", "EU", "en", [1]))

    assert out == {"1": 99}


def test_fetch_prices_auto_raises_when_no_source_has_data(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"result": {"data": []}})
    _install_transport(monkeypatch, handler)

    with pytest.raises(app_module.HTTPException):
        asyncio.run(app_module.fetch_prices("auto", "EU", "en", [1, 2]))


def test_fetch_prices_custom_requires_url():
    with pytest.raises(app_module.HTTPException):
        asyncio.run(app_module.fetch_prices("custom", "EU", "en", [1], custom_url=""))
