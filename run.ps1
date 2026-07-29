Set-Location -Path (Join-Path $PSScriptRoot "server")
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Backend is not set up yet. First run:  python build.py"
  exit 1
}
Write-Host "Serving on http://127.0.0.1:8000  (Ctrl+C to stop)"
& $py -m uvicorn app:app --host 127.0.0.1 --port 8000
