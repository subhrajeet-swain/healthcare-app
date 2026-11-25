"""Phase 1 done-when check: the 5 sample PDFs, upload to explanation, under 30 s each.

Needs the Docker stack running (`docker compose up`) with GOOGLE_API_KEY in .env.
Signs in as the lab-alpha seed patient with the dev OTP read from the API logs.

    cd backend && uv run python ../scripts/live_check.py
"""

import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"
LAB, PHONE = "lab-alpha", "+919000000001"
LIMIT_S = 30
SAMPLES = Path(__file__).resolve().parents[2]  # personal/
FILES = [
    *sorted(SAMPLES.glob("*Drlogy*.pdf")),
    SAMPLES / "B080.pdf",
    SAMPLES / "Z005.pdf",
]
TERMINAL = {"ready", "needs_review", "failed"}


def sign_in(c: httpx.Client) -> None:
    assert c.post(f"/api/auth/{LAB}/otp", json={"phone": PHONE}).status_code == 202
    time.sleep(1)
    logs = subprocess.run(
        ["docker", "compose", "logs", "api"], capture_output=True, text=True
    ).stdout
    code = re.findall(r"OTP for \S+: (\d{6})", logs)[-1]
    assert c.post(f"/api/auth/{LAB}/verify", json={"phone": PHONE, "code": code}).status_code == 200
    c.post("/api/consents", json={"purpose": "core", "version": "2026-11-v1"})


def main() -> int:
    c = httpx.Client(base_url=API, timeout=30)
    sign_in(c)
    worst = 0.0
    failed = False
    for f in FILES:
        started = time.monotonic()
        upload = {"file": (f.name, f.read_bytes(), "application/pdf")}
        rid = c.post("/api/reports", files=upload).json()["id"]
        while True:
            d = c.get(f"/api/reports/{rid}").json()
            if d["status"] in TERMINAL or time.monotonic() - started > 120:
                break
            time.sleep(0.5)
        took = time.monotonic() - started
        worst = max(worst, took)
        ok = d["status"] in ("ready", "needs_review") and took < LIMIT_S
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {took:5.1f}s {d['status']:<13} {d['triage'] or '-':<6} "
              f"{len(d['results'])} results  {f.name[:50]}")
    print(f"slowest {worst:.1f}s (limit {LIMIT_S}s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
