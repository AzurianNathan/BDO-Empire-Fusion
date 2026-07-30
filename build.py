#!/usr/bin/env python3
"""
Cross-platform setup for the fused app (Windows / macOS / Linux).

  python build.py            # set up backend, then try to build the map UI
  python build.py --backend  # backend only (skip the frontend build)

The backend is set up FIRST and independently, so `run` works even if the
frontend build can't complete.
"""
import os
import subprocess
import sys
import shutil
import time
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WM = ROOT / "workermanjs"
SERVER = ROOT / "server"
IS_WIN = os.name == "nt"


MISSING_TOOL_HELP = {
    "git": "Get it from https://git-scm.com/download/win (default options are fine).",
    "npm": "Get Node.js (which includes npm) from https://nodejs.org/.",
}


def sh(cmd, cwd=None, shell=False):
    print(f"  $ {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}")
    try:
        subprocess.run(cmd, cwd=cwd, shell=shell, check=True)
    except FileNotFoundError:
        # subprocess.run raises this when the executable itself can't be
        # found (not when the command it runs fails) - i.e. the tool isn't
        # installed or isn't on PATH. Without this, that shows up as a raw
        # _winapi.CreateProcess traceback that gives no hint what's missing.
        exe = Path(cmd if isinstance(cmd, str) else cmd[0]).stem.lower()
        hint = MISSING_TOOL_HELP.get(exe, "Make sure it's installed and on your PATH.")
        raise SystemExit(f"\n  !! '{exe}' isn't installed, or isn't on PATH. {hint}\n") from None


def venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


def rmtree_retry(path: Path, attempts: int = 6, delay: float = 1.0) -> None:
    """shutil.rmtree with retries. On Windows, antivirus or the search
    indexer can transiently lock a directory right after a big npm build
    just wrote hundreds of files into it, which otherwise fails the whole
    build with a raw PermissionError for a lock that clears itself in a few
    seconds."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 1.5


def setup_backend():
    print(">> backend: creating venv + installing")
    env_dir = SERVER / ".venv"
    if not venv_python(env_dir).exists():
        venv.create(env_dir, with_pip=True)
    py = venv_python(env_dir)
    sh([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    sh([str(py), "-m", "pip", "install", "-r", str(SERVER / "requirements.txt")])
    print(">> backend ready.")


def setup_data():
    """Fetch just Workerman's data/ so /api/prices + /api/effective-prices work
    (and the fallback page is usable) even without building the map UI."""
    print(">> data: fetching Workerman game data")
    if not WM.exists():
        sh(["git", "clone", "--depth", "1", "https://github.com/shrddr/workermanjs.git", str(WM)])
    static_data = SERVER / "static" / "data"
    if not static_data.exists():
        shutil.copytree(WM / "data", static_data)
    print(">> data ready.")


def setup_frontend():
    print(">> frontend: clone + patch + build")
    if not WM.exists():
        sh(["git", "clone", "--depth", "1", "https://github.com/shrddr/workermanjs.git", str(WM)])
    sh([sys.executable, str(ROOT / "patches" / "apply_patches.py"), str(WM)])

    # apply_patches installs a pure-JS node router here when none exists, so the
    # map builds without any WASM toolchain. This is just a safety net.
    pkg = WM / "src" / "pkg" / "noderouter.js"
    if not pkg.exists():
        print(
            "\n  !! src/pkg/noderouter.js is missing, so the map cannot build.\n"
            "     patches/noderouter.js should have been installed there.\n"
            "     Skipping the map build; the backend + optimizer API still work.\n"
        )
        return False

    npm = "npm.cmd" if IS_WIN else "npm"
    sh([npm, "install", "--no-audit", "--no-fund"], cwd=WM)
    sh([npm, "run", "build"], cwd=WM)
    # game data the app fetches at runtime
    dist = WM / "dist"
    shutil.copytree(WM / "data", dist / "data", dirs_exist_ok=True)
    # publish into the server
    static = SERVER / "static"
    if static.exists():
        rmtree_retry(static)
    shutil.copytree(dist, static)
    print(">> frontend built and published to server/static.")
    return True


def main():
    backend_only = "--backend" in sys.argv
    setup_backend()
    setup_data()
    if not backend_only:
        try:
            setup_frontend()
        except subprocess.CalledProcessError as e:
            print(f"\n  !! frontend build step failed ({e}). Backend is still runnable.\n")
    print("\nDone. Start it with:  " + ("run.bat" if IS_WIN else "./run.sh"))


if __name__ == "__main__":
    main()
