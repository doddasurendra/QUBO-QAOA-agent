"""Uptime probe used by .github/workflows/uptime.yml (standard library only).

Polls <url> (normally https://<app>/api/health/deep) with retries so a single blip does not page anyone, then prints
a one-line JSON verdict and exits:  0 = up,  1 = down,  2 = degraded.

    python scripts/uptime_check.py https://qopt-quantum-c4da.fly.dev/api/health/deep
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

UP, DOWN, DEGRADED = 0, 1, 2


def probe(url: str, timeout: float = 20.0) -> Tuple[Optional[int], Optional[dict], Optional[str]]:
    """One request → (http status | None, parsed JSON body | None, error text | None)."""
    req = urllib.request.Request(url, headers={"User-Agent": "qopt-uptime-monitor/1.0", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    except Exception as e:  # noqa: BLE001 - DNS, TLS, timeouts, refused connections
        return None, None, f"{type(e).__name__}: {e}"
    try:
        return code, json.loads(raw.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError):
        return code, None, "response is not JSON"


def classify(code: Optional[int], body: Optional[dict], error: Optional[str]) -> Tuple[int, str]:
    if error and code is None:
        return DOWN, error
    if code != 200 or not isinstance(body, dict):
        status = body.get("status") if isinstance(body, dict) else None
        return DOWN, f"HTTP {code}" + (f", status={status}" if status else "") + (f" ({error})" if error else "")
    status = body.get("status")
    if status == "ok":
        return UP, "ok"
    bad = {k: v.get("status") for k, v in (body.get("checks") or {}).items()
           if isinstance(v, dict) and v.get("status") not in ("ok", "pending", "n/a")}
    if status == "degraded":
        return DEGRADED, "degraded: " + ", ".join(f"{k}={v}" for k, v in bad.items())
    return DOWN, f"unexpected status {status!r}"


def check(url: str, attempts: int = 3, delay: float = 20.0,
          prober: Callable[[str], tuple] = probe, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Retry while the site looks down; report the last observation. Degraded is not retried (it is stable)."""
    verdict, reason = DOWN, "no attempt"
    for i in range(attempts):
        verdict, reason = classify(*prober(url))
        if verdict != DOWN:
            break
        if i < attempts - 1:
            sleep(delay)
    return {"url": url, "verdict": {UP: "up", DOWN: "down", DEGRADED: "degraded"}[verdict],
            "code": verdict, "reason": reason, "attempts": i + 1,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(64)
    result = check(sys.argv[1])
    print(json.dumps(result))
    sys.exit(result["code"])
