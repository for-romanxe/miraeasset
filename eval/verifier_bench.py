#!/usr/bin/env python3
"""verifier 2단계 비용/효과 실측 — scope="numeric" vs scope="all" 비교 (#43).

#42의 SYSTEM_RULES 강화 이후에도 verifier 2단계가 필요한 이유: "문자열은 근거에
있지만 가리키는 대상이 틀린" 경우(1,500만원=수령 종합과세 기준을 납입 한도로
서술)는 1단계 문자열 대조로 원리상 못 잡는다. 이 스크립트는 그 케이스를 재현하는
표본과 tax-17(정당한 유도 산술 오탐 사례)을 포함해 두 scope의 탐지력·호출
시간·토큰 사용량을 비교한다.

CLOVASTUDIO_API_KEY 필요 (HCX 실호출). 계정 분당 요청 한도를 llm_judge.py와
공유하므로 그 스크립트가 도는 동안은 실행하지 말 것.

사용:
  python eval/verifier_bench.py           # 기본 표본
  python eval/verifier_bench.py -n 20     # evalset 앞 20문항 추가
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import llm, pipeline  # noqa: E402
from agent.pipeline import verifier  # noqa: E402

EVALSET = Path(__file__).resolve().parent / "evalset.jsonl"

# llm_judge.py와 같은 이유로 같은 페이스를 쓴다 — 계정 한도가 공유라 문항
# 사이를 띄우지 않으면 429가 난다 (실측: 15문항을 페이스 없이 돌리다 11번째에서
# 걸림, llm_judge.py --twice와 동시에 실행 중이었음).
PACE_SEC = 8.0
RATE_RELIEF_SEC = 65.0

# #43 이슈에 명시된 핵심 재현 케이스. 실제 문서 근거를 그대로 썼다 —
# 1,500만원(doc38, 수령 종합과세 기준)과 1,800만원(doc41·doc44, 납입 한도)이
# 같은 컨텍스트에 모두 등장할 때, "1,500만원까지 납입 가능"처럼 문자열은
# 근거에 있지만 대상이 틀린 문장을 2단계가 잡아내는지 본다.
CONFUSION_CASE = {
    "id": "bench-1500-1800",
    "context": [
        "[doc41(연금저축계좌, IRP 세액공제 안내) 본문]\n연금저축과 IRP는 합산해서 "
        "연1,800만원까지 입금이 가능하다. 세액공제 받을 수 있는 납입한도는 "
        "연금저축 600만원, IRP는 합산 900만원이다.",
        "[doc38(연금소득 종합과세 안내) 본문]\n사적연금소득을 1년에 1,500만원 "
        "초과 수령 시(전 금융기관 합산) 종합과세 되지만, 세액공제 안받은 돈과 "
        "퇴직금은 이 1,500만원 판단에 포함되지 않는다.",
    ],
    "calc_notes": [],
    "answer_ok": "연금저축과 IRP를 합쳐서 연 1,800만원까지 납입할 수 있습니다. "
                 "다만 수령할 때 연 1,500만원을 초과하면 종합과세 대상이 될 "
                 "수 있으니 유의하세요.",
    "answer_bad": "연금저축과 IRP 합쳐서 최대 1,500만원까지 납입 가능합니다.",
}


def _bench_one(judge_llm, case_id: str, answer: str, context: list, calc: list) -> dict:
    row = {"id": case_id}
    for scope in ("numeric", "all"):
        t0 = time.monotonic()
        for attempt in range(2):
            try:
                bad, trace = verifier.verify_claims_llm(answer, context, calc, scope=scope)
                break
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if attempt == 0 and status == 429:
                    print(f"    ({case_id}/{scope} 429 — {RATE_RELIEF_SEC:.0f}초 대기)")
                    time.sleep(RATE_RELIEF_SEC)
                    continue
                raise
        row[scope] = {"sec": round(time.monotonic() - t0, 2),
                      "flagged": len(bad), "trace": trace}
        time.sleep(PACE_SEC)
    return row


def main():
    n = 0
    if "-n" in sys.argv:
        n = int(sys.argv[sys.argv.index("-n") + 1])

    judge = llm.get_llm()
    if judge.name == "mock":
        print("CLOVASTUDIO_API_KEY 없음 — 실측 불가. .env 로드 후 다시 실행하세요.")
        return

    results = []

    print("== 대조 사례: '수령 기준 1,500만원'을 '납입 한도'로 잘못 쓴 문장 ==")
    ok = _bench_one(judge, "confusion-ok(정답)", CONFUSION_CASE["answer_ok"],
                    CONFUSION_CASE["context"], CONFUSION_CASE["calc_notes"])
    bad = _bench_one(judge, "confusion-bad(환각)", CONFUSION_CASE["answer_bad"],
                     CONFUSION_CASE["context"], CONFUSION_CASE["calc_notes"])
    results += [ok, bad]
    for row in (ok, bad):
        print(f"  {row['id']}")
        for scope in ("numeric", "all"):
            r = row[scope]
            print(f"    {scope:8s} {r['sec']}초 flagged={r['flagged']}  {r['trace']}")

    if n:
        print(f"\n== evalset 앞 {n}문항 ==")
        items = [json.loads(l) for l in EVALSET.read_text(encoding="utf-8").splitlines() if l][:n]
        for it in items:
            try:
                resp = pipeline.answer(it["id"], it["question"])
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    print(f"  {it['id']:12s} 429 — {RATE_RELIEF_SEC:.0f}초 대기 후 재시도")
                    time.sleep(RATE_RELIEF_SEC)
                    resp = pipeline.answer(it["id"], it["question"])
                else:
                    raise
            if not resp["retrieved_context"]:
                # 근거 없이 답하는 분기(거절·한계고지·역질문)는 실제 파이프라인에서
                # apply()를 아예 안 거친다 — pipeline/__init__.py가 verifier 호출
                # 전에 일찍 return한다. 여기서 억지로 검증하면 문장 전부가
                # "근거 없음"으로 미지지 처리돼 벤치마크 결과가 왜곡된다 (ref-5 실측:
                # all 5건 전부 이 이유로 오탐처럼 보였음 — 실제 버그 아님).
                print(f"  {it['id']:12s} 근거 없음(거절/한계고지/역질문) — 검증 대상 아님, 건너뜀")
                continue
            row = _bench_one(judge, it["id"], resp["answer"],
                             resp["retrieved_context"].split("\n\n---\n\n"), [])
            results.append(row)
            print(f"  {it['id']:12s} "
                 f"numeric={row['numeric']['sec']}s/{row['numeric']['flagged']}건  "
                 f"all={row['all']['sec']}s/{row['all']['flagged']}건")
            time.sleep(PACE_SEC)

    print("\n== 요약 ==")
    for scope in ("numeric", "all"):
        secs = [r[scope]["sec"] for r in results]
        flagged = sum(r[scope]["flagged"] for r in results)
        print(f"  {scope:8s} 평균 {sum(secs)/len(secs):.2f}초/건, 총 flagged {flagged}건")
    print("\n(확인: confusion-ok는 두 scope 모두 flagged=0, "
         "confusion-bad는 두 scope 모두 flagged>=1 이어야 2단계가 제 역할을 하는 것)")


if __name__ == "__main__":
    main()
