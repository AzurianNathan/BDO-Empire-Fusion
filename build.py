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
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WM = ROOT / "workermanjs"
SERVER = ROOT / "server"
IS_WIN = os.name == "nt"


def sh(cmd, cwd=None, shell=False):
    print(f"  $ {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}")
    subprocess.run(cmd, cwd=cwd, shell=shell, check=True)


def venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


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
        shutil.rmtree(static)
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
