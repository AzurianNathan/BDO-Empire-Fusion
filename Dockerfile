# syntax=docker/dockerfile:1

# ---- builder: clones + patches + builds the Workerman map -------------------
# Needs git (clones workermanjs fresh - CLAUDE.md: never vendor it, it has no
# LICENSE file) and Node (only to build the map's JS bundle). Neither ends up
# in the final image.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . .
RUN python build.py

# ---- runtime: just the backend + the built map -------------------------------
# No Node, no git, no build tooling - only what's needed to serve the app.
FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /build/server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=builder /build/server/app.py ./app.py
COPY --from=builder /build/server/pipeline.py ./pipeline.py
COPY --from=builder /build/server/fallback.html ./fallback.html
COPY --from=builder /build/server/static ./static

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
