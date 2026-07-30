"""Shared fixtures for the server test suite.

Imports app.py directly rather than through a package, matching how it's
actually run (`server/` is the working directory, not a package).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture(autouse=True)
def _reset_module_state():
    """app.py caches prices/jobs/last-fetch info in module-level dicts, which
    would otherwise leak between tests (a price cached by one test would make
    a later test's "does it actually fetch" assertion silently pass for the
    wrong reason)."""
    app_module._PRICE_CACHE.clear()
    app_module._BDOLYTICS_CACHE.clear()
    app_module._JOBS.clear()
    app_module.LAST_PRICE_SOURCE = ""
    app_module._LAST_FETCH = {}
    yield
    app_module._PRICE_CACHE.clear()
    app_module._BDOLYTICS_CACHE.clear()
    app_module._JOBS.clear()
    app_module.LAST_PRICE_SOURCE = ""
    app_module._LAST_FETCH = {}


@pytest.fixture
def client():
    return TestClient(app_module.app)
