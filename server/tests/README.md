# Server tests

Unit/integration tests for `server/app.py`: the effective-price math, the
bdolytics price provider and dispatcher (mocked HTTP, no real network calls),
and the optimize job lifecycle (real solver replaced by a fast fake).

```
cd server
.venv/Scripts/pip install -r requirements-dev.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/pytest                                # .venv/bin/pytest
```

These don't cover the frontend (Vue/Pinia) or the router - `tests/router_test.mjs`
at the repo root does that, against the real game graph.
