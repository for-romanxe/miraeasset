#!/usr/bin/env python3
"""성능 점검 — 콜드스타트(인덱스 구축)와 문항당 응답 지연을 측정한다.

평가자는 서버에 연속으로 GET을 날린다. 여기서 재는 것은 LLM 호출을 제외한
파이프라인 자체(라우팅→검색→계산→검증) 지연이다. HCX 연동 후 실제 응답
시간은 여기 수치 + HCX 생성 시간(수 초)이 된다.

사용: python eval/perf.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVALSET = Path(__file__).resolve().parent / "evalset.jsonl"


def main():
    # 콜드스타트: import + 인덱스 lazy 구축(첫 질의)까지
    t0 = time.perf_counter()
    from agent import pipeline
    t_import = time.perf_counter() - t0

    t0 = time.perf_counter()
    pipeline.answer("warmup", "연금저축 세액공제 한도가 얼마인가요?")
    t_first = time.perf_counter() - t0

    items = [json.loads(l) for l in EVALSET.read_text(encoding="utf-8").splitlines() if l]
    lat = []
    t_all = time.perf_counter()
    for it in items:
        t0 = time.perf_counter()
        pipeline.answer(it["id"], it["question"])
        lat.append((time.perf_counter() - t0) * 1000)
    t_all = time.perf_counter() - t_all

    lat.sort()
    p = lambda q: lat[int(len(lat) * q)]  # noqa: E731
    print(f"콜드스타트: import {t_import * 1000:.0f}ms + 첫 질의(인덱스 구축) {t_first * 1000:.0f}ms")
    print(f"본측정: {len(lat)}문항 {t_all:.1f}s ({len(lat) / t_all:.1f}문항/s)")
    print(f"지연(ms): p50 {p(0.5):.1f} / p90 {p(0.9):.1f} / p99 {p(0.99):.1f} / max {lat[-1]:.1f}")
    print(f"평균 {statistics.mean(lat):.1f}ms")
    print("\n주의: LLM 호출 제외 수치. HCX 연동 후 문항당 +2~10초 예상 (maxTokens에 좌우)")


if __name__ == "__main__":
    main()
