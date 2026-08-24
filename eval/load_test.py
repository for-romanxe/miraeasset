#!/usr/bin/env python3
"""실행 중인 평가 API에 연속·동시 요청을 보내는 경량 부하 점검 도구.

사용 예:
  python eval/load_test.py --base-url http://127.0.0.1:8000 --concurrency 1
  python eval/load_test.py --base-url http://127.0.0.1:8000 --concurrency 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

EVALSET = Path(__file__).resolve().parent / "evalset.jsonl"
SCHEMA = {"question_id", "question", "retrieved_context", "think_trace", "answer"}


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * quantile), len(ordered) - 1)]


def request_one(base_url: str, item: dict, timeout: float) -> tuple[int, float, bool]:
    started = time.perf_counter()
    response = requests.get(
        f"{base_url.rstrip('/')}/answer",
        params={"question_id": item["id"], "question": item["question"]},
        timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    schema_ok = False
    if response.status_code == 200:
        try:
            schema_ok = set(response.json()) == SCHEMA
        except requests.JSONDecodeError:
            pass
    return response.status_code, elapsed_ms, schema_ok


def run(base_url: str, concurrency: int, timeout: float) -> int:
    items = [json.loads(line) for line in EVALSET.read_text(encoding="utf-8").splitlines() if line]
    results: list[tuple[int, float, bool] | None] = [None] * len(items)
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(request_one, base_url, item, timeout): index
            for index, item in enumerate(items)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except requests.RequestException:
                results[index] = (0, timeout * 1000, False)

    elapsed = time.perf_counter() - started
    completed = [result for result in results if result is not None]
    latencies = [result[1] for result in completed]
    statuses = Counter(result[0] for result in completed)
    schema_failures = sum(not result[2] for result in completed)
    quarter = max(len(latencies) // 4, 1)
    first = statistics.mean(latencies[:quarter])
    last = statistics.mean(latencies[-quarter:])

    print(f"requests={len(completed)} concurrency={concurrency} total={elapsed:.3f}s")
    print(f"status_codes={dict(sorted(statuses.items()))} schema_failures={schema_failures}")
    print(
        "latency_ms="
        f"p50:{percentile(latencies, 0.50):.2f} "
        f"p90:{percentile(latencies, 0.90):.2f} "
        f"p99:{percentile(latencies, 0.99):.2f} "
        f"max:{max(latencies):.2f}"
    )
    print(f"trend_ms=first_quarter:{first:.2f} last_quarter:{last:.2f} ratio:{last / first:.3f}")
    return 0 if statuses == {200: len(completed)} and schema_failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    return run(args.base_url, args.concurrency, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
