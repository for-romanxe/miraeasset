#!/usr/bin/env python3
"""평가 하네스 — evalset.jsonl을 파이프라인에 넣고 자동 채점한다.

Mock LLM 단계에서도 신뢰할 수 있는 결정적 항목만 채점한다:
  - docs      : 기대 문서 중 하나라도 retrieved_context에 인용됐는가 (any-hit)
  - isins     : 기대 펀드가 전부 인용됐는가 (all-hit)
  - clarify   : 역질문 분기가 일어났는가
  - trace_contains : think_trace에 기대 문자열(계산 결과 등)이 있는가

사용:
  python eval/run_eval.py            # 전체
  python eval/run_eval.py -v         # 실패 문항 상세
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import pipeline  # noqa: E402

EVALSET = Path(__file__).resolve().parent / "evalset.jsonl"


def check(item: dict, resp: dict) -> tuple[bool, list[str]]:
    exp = item["expect"]
    fails = []
    ctx, trace = resp["retrieved_context"], resp["think_trace"]

    if "docs" in exp and not any(f"{d}(" in ctx for d in exp["docs"]):
        fails.append(f"docs any-hit 실패 (기대: {exp['docs']})")
    for isin in exp.get("isins", []):
        if isin not in ctx:
            fails.append(f"isin 미인용: {isin}")
    if exp.get("clarify") and "[분기]" not in trace:
        fails.append("역질문 분기 없음")
    if not exp.get("clarify") and "[분기]" in trace:
        fails.append("불필요한 역질문 분기")
    for s in exp.get("trace_contains", []):
        if s not in trace:
            fails.append(f"trace에 없음: {s!r}")
    return not fails, fails


def main():
    verbose = "-v" in sys.argv
    items = [json.loads(l) for l in EVALSET.read_text(encoding="utf-8").splitlines() if l]
    by_type = defaultdict(lambda: [0, 0])
    failures = []
    for it in items:
        resp = pipeline.answer(it["id"], it["question"])
        ok, fails = check(it, resp)
        by_type[it["type"]][0] += ok
        by_type[it["type"]][1] += 1
        if not ok:
            failures.append((it, fails, resp))

    total_ok = sum(v[0] for v in by_type.values())
    print(f"== 총점 {total_ok}/{len(items)} ({total_ok / len(items):.0%})")
    for t, (ok, n) in sorted(by_type.items()):
        print(f"   {t:12s} {ok}/{n}")
    if failures:
        print(f"\n== 실패 {len(failures)}건")
        for it, fails, resp in failures:
            print(f" · {it['id']} [{it['type']}] {it['question'][:38]}")
            for f in fails:
                print(f"     - {f}")
            if verbose:
                print(f"     trace: {resp['think_trace'][:220]}")


if __name__ == "__main__":
    main()
