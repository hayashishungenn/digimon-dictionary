#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/benchmark_api.py --base-url http://127.0.0.1:8020/api
# 3. Or make executable and run:
#      chmod +x scripts/benchmark_api.py && ./scripts/benchmark_api.py
# ──────────────────

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True)
class Endpoint:
    name: str
    path: str
    expected_status: tuple[int, ...] = (200,)


ENDPOINTS = (
    Endpoint("meta", "/meta"),
    Endpoint("list", "/digimon?limit=60&offset=0"),
    Endpoint("search_hit", "/search?q=Agumon&limit=30"),
    Endpoint("search_empty", "/search?q=NoSuchMon&limit=30"),
    Endpoint("detail", "/digimon/agumon"),
    Endpoint("evolution_depth_1", "/digimon/agumon/evolution?depth=1"),
    Endpoint("evolution_depth_2", "/digimon/agumon/evolution?depth=2"),
    Endpoint("evolution_depth_3", "/digimon/agumon/evolution?depth=3"),
    Endpoint("group", "/groups/Royal%20Knights"),
    Endpoint("review", "/review?status=open&limit=20&offset=0"),
    Endpoint("unknown_slug", "/digimon/does-not-exist", (404,)),
)


def fetch(base_url: str, path: str) -> tuple[int, int, JsonValue | None]:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            status = response.status
    except HTTPError as error:
        body = error.read()
        status = error.code
    except URLError as error:
        raise RuntimeError(f"cannot reach {base_url}: {error.reason}") from error

    try:
        payload: JsonValue | None = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    return status, len(body), payload


def percentile(values: list[float], percentage: float) -> float:
    index = max(0, math.ceil(len(values) * percentage / 100) - 1)
    return sorted(values)[index]


def timed_fetch(base_url: str, endpoint: Endpoint) -> tuple[float, int, int, JsonValue | None]:
    start = time.perf_counter()
    status, size, payload = fetch(base_url, endpoint.path)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if status not in endpoint.expected_status:
        expected = ", ".join(str(value) for value in endpoint.expected_status)
        raise RuntimeError(f"{endpoint.name} returned {status}; expected {expected}")
    return elapsed_ms, status, size, payload


def payload_markers(payload: JsonValue | None) -> dict[str, JsonValue]:
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload[key]
        for key in ("count", "total", "node_count", "edge_count", "truncated")
        if key in payload
    }


def benchmark_endpoint(base_url: str, endpoint: Endpoint, warmup: int, iterations: int) -> dict[str, JsonValue]:
    cold_ms, cold_status, cold_bytes, cold_payload = timed_fetch(base_url, endpoint)
    for _ in range(warmup):
        timed_fetch(base_url, endpoint)
    hot_values: list[float] = []
    hot_status = cold_status
    hot_bytes = cold_bytes
    hot_payload = cold_payload
    for _ in range(iterations):
        elapsed_ms, hot_status, hot_bytes, hot_payload = timed_fetch(base_url, endpoint)
        hot_values.append(elapsed_ms)
    return {
        "endpoint": endpoint.name,
        "cold_ms": round(cold_ms, 2),
        "hot_p50_ms": round(percentile(hot_values, 50), 2),
        "hot_p95_ms": round(percentile(hot_values, 95), 2),
        "hot_max_ms": round(max(hot_values), 2),
        "status": hot_status,
        "response_bytes": hot_bytes,
        "markers": payload_markers(hot_payload),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local DigiDex API endpoints")
    parser.add_argument("--base-url", default="http://127.0.0.1:8020/api")
    parser.add_argument("--warmup", type=int, default=3, help="warmup requests per endpoint")
    parser.add_argument("--iterations", type=int, default=20, help="measured requests per endpoint")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()
    if args.warmup < 0 or args.iterations < 2:
        parser.error("--warmup must be >= 0 and --iterations must be >= 2")

    results = [
        benchmark_endpoint(args.base_url, endpoint, args.warmup, args.iterations)
        for endpoint in ENDPOINTS
    ]
    report = {
        "base_url": args.base_url,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "results": results,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"base_url={args.base_url} warmup={args.warmup} iterations={args.iterations}")
    print("endpoint                 cold_ms  hot_p50  hot_p95  hot_max  status  bytes  markers")
    for result in results:
        markers = json.dumps(result["markers"], ensure_ascii=False, separators=(",", ":"))
        print(
            f"{result['endpoint']:<24} {result['cold_ms']:>7} {result['hot_p50_ms']:>8} "
            f"{result['hot_p95_ms']:>8} {result['hot_max_ms']:>8} {result['status']:>7} "
            f"{result['response_bytes']:>6}  {markers}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
