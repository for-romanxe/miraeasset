"""규칙 라우터와 HyperCLOVA X 라우터의 평가셋 분류를 비교한다."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.llm import get_llm
from agent.pipeline.router import build_hcx_router_prompt, route, route_from_hcx


EVALSET = ROOT / "eval" / "evalset.jsonl"
COMPARE_FIELDS = (
    "categories", "is_recommendation", "filled_slots", "missing_slots",
    "needs_clarification", "assumptions", "out_of_scope", "unsafe",
)


def _load_dotenv() -> None:
    """외부 의존성 없이 로컬 .env를 읽되 기존 환경변수를 덮어쓰지 않는다."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _signature(result) -> dict:
    data = asdict(result)
    return {field: data[field] for field in COMPARE_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=2.0,
                        help="HCX 호출 사이 대기 시간(초, 기본 2.0)")
    parser.add_argument("--limit", type=int, default=0,
                        help="앞 N문항만 비교(0이면 전체)")
    parser.add_argument("--output", type=Path,
                        help="상세 JSON 결과 저장 경로")
    args = parser.parse_args()

    _load_dotenv()
    llm = get_llm()
    if llm.name == "mock":
        parser.error("CLOVASTUDIO_API_KEY가 필요합니다")

    cases = [json.loads(line) for line in EVALSET.read_text(encoding="utf-8").splitlines()]
    if args.limit:
        cases = cases[:args.limit]

    rows = []
    for index, case in enumerate(cases, 1):
        question = case["question"]
        rule_result = route(question)
        raw = llm.generate(build_hcx_router_prompt(question), max_tokens=256)
        hcx_result = route_from_hcx(raw, question)
        matched = hcx_result.source == "hcx" and _signature(rule_result) == _signature(hcx_result)
        rows.append({
            "id": case["id"],
            "question": question,
            "matched": matched,
            "hcx_parse_success": hcx_result.source == "hcx",
            "rule": _signature(rule_result),
            "hcx": _signature(hcx_result),
        })
        print(f"[{index:3}/{len(cases)}] {case['id']}: "
              f"{'일치' if matched else '불일치'}", flush=True)
        if index < len(cases) and args.interval > 0:
            time.sleep(args.interval)

    parse_successes = sum(row["hcx_parse_success"] for row in rows)
    matches = sum(row["matched"] for row in rows)
    print(f"\nHCX 파싱 성공: {parse_successes}/{len(rows)}")
    print(f"라우팅 일치: {matches}/{len(rows)} ({matches / len(rows):.1%})")
    print("불일치 문항: " + ", ".join(row["id"] for row in rows if not row["matched"]))

    if args.output:
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"상세 결과: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
