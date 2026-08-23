#!/usr/bin/env python3
"""LLM 채점 하네스 — 답변의 '문장 품질'을 루브릭으로 자동 채점한다.

run_eval.py의 결정적 채점(문서 인용·수치·분기)이 못 보는 것을 본다:
질문에 실제로 답했는가, 근거 밖 주장을 하는가, 단정 추천 금지·출처 표기
규정을 지키는가. 심판도 HyperCLOVA X를 쓴다 (별도 모델 불필요).

CLOVASTUDIO_API_KEY가 없으면 드라이런: 채점 프롬프트가 제대로 조립되는지만
확인하고 종료한다 (키 수령 후 바로 실채점 가능한 상태 유지가 목적).

사용:
  python eval/llm_judge.py           # 전체 문항 채점 (키 필요)
  python eval/llm_judge.py -n 10     # 앞 10문항만
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import llm, pipeline  # noqa: E402

EVALSET = Path(__file__).resolve().parent / "evalset.jsonl"

# 각 축 0~2점. 합계 8점 만점.
#
# 프롬프트 설계 주의: 점수를 먼저 쓰게 하면 심판이 점수부터 찍고 총평을 사후에
# 지어낸다. 실제로 초기 버전에서 "8/8점 + 정확하지 않습니다" 같은 모순이 다수
# 나왔다. 그래서 (1) 결함을 먼저 나열하게 하고 (2) 그 결함에 점수를 묶는다.
JUDGE_PROMPT = """당신은 연금 상담 답변의 채점자입니다. 아래 [질문]에 대한 [답변]을
[근거자료]와 대조해 채점하세요.

작성 순서를 반드시 지키세요. 먼저 결함을 찾고, 찾은 결함에 따라 점수를 매깁니다.

1단계 — 축별로 결함을 찾습니다:
- grounding: 답변의 사실·수치 중 근거자료에서 확인되지 않는 것이 있는가.
- relevance: 질문이 실제로 물은 것에 답하지 않고 주변 정보만 나열하지 않았는가.
- compliance: 특정 상품을 단정적으로 추천했는가. 모르는 것을 아는 척했는가.
  (※ 출처 표기는 답변 맨 끝 "근거:" 줄로 이미 제공되므로 감점 사유가 아닙니다.)
- clarity: 연금을 모르는 고객이 이해하기 어려운 표현을 풀어쓰지 않았는가.

2단계 — 각 축을 채점합니다:
- 2점: 해당 축에서 발견한 결함이 없음
- 1점: 경미한 결함이 있음
- 0점: 답변을 신뢰할 수 없게 만드는 중대한 결함이 있음

중요: findings에 결함을 적은 축은 2점을 줄 수 없습니다. 결함이 없는 축은
반드시 문자열 "없음"만 적고 2점을 주세요. 총평이나 칭찬을 적지 마세요.
findings에 적은 내용과 점수가 어긋나면 채점 자체가 무효입니다.

반드시 아래 JSON 형식으로만 답하세요. findings를 먼저 쓰세요.
꺾쇠 부분은 당신이 직접 판단해 채우는 자리입니다. 그대로 옮겨 적지 마세요.
{{"findings": {{"grounding": "<이 축의 결함 또는 없음>", "relevance": "<이 축의 결함 또는 없음>", "compliance": "<이 축의 결함 또는 없음>", "clarity": "<이 축의 결함 또는 없음>"}}, "grounding": <0~2>, "relevance": <0~2>, "compliance": <0~2>, "clarity": <0~2>}}

[질문]
{question}

[근거자료]
{context}

[답변]
{answer}"""


def build_prompt(question: str, resp: dict) -> str:
    ctx = resp["retrieved_context"] or "(근거 없음 — 역질문/한계 고지/거절 응답)"
    return JUDGE_PROMPT.format(question=question, context=ctx[:4000],
                               answer=resp["answer"][:2000])


def parse_scores(raw: str) -> dict | None:
    """심판 응답에서 JSON을 뽑는다. 형식 위반이면 None (해당 문항 스킵 집계)."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    axes = ("grounding", "relevance", "compliance", "clarity")
    if not all(isinstance(d.get(a), int) and 0 <= d[a] <= 2 for a in axes):
        return None
    return d


AXES = ("grounding", "relevance", "compliance", "clarity")

# 심판 신뢰도는 findings 문장을 정규식으로 훑어 재려 했으나 실패했다.
# 심판이 "없음" 대신 "문제는 없었습니다" 같은 서술을 쓰기 때문에 결함 유무를
# 문장에서 판정할 수 없었고, 오탐이 80%를 넘었다. 대신 같은 문항을 두 번
# 채점시켜 점수가 재현되는지를 본다 (test-retest). 재현되지 않는 점수는
# 문장 분석과 무관하게 신뢰할 수 없다.


def score_gap(a: dict, b: dict) -> int:
    """같은 문항 두 번 채점 결과의 축별 점수 차 합계."""
    return sum(abs(a[x] - b[x]) for x in AXES)


def judge_one(judge, question: str, resp: dict) -> dict | None:
    return parse_scores(judge.generate(build_prompt(question, resp), max_tokens=256))


def main():
    n = None
    if "-n" in sys.argv:
        n = int(sys.argv[sys.argv.index("-n") + 1])
    items = [json.loads(l) for l in EVALSET.read_text(encoding="utf-8").splitlines() if l][:n]

    judge = llm.get_llm()
    if judge.name == "mock":
        # 드라이런: 프롬프트 조립만 검증
        it = items[0]
        resp = pipeline.answer(it["id"], it["question"])
        prompt = build_prompt(it["question"], resp)
        print("== 드라이런 (CLOVASTUDIO_API_KEY 없음) — 채점 프롬프트 샘플 ==\n")
        print(prompt[:1500])
        print(f"\n== 프롬프트 {len(prompt)}자 조립 OK. 키 설정 후 실채점 가능 ==")
        return

    twice = "--twice" in sys.argv  # 심판 신뢰도 측정 모드
    total, axes_sum, skipped, worst = 0, {}, 0, []
    gaps = []
    for it in items:
        resp = pipeline.answer(it["id"], it["question"])
        scores = judge_one(judge, it["question"], resp)
        if scores is None:
            skipped += 1
            continue
        s = sum(scores[a] for a in AXES)
        total += 1
        for a in AXES:
            axes_sum[a] = axes_sum.get(a, 0) + scores[a]
        findings = scores.get("findings", "")
        worst.append((s, it["id"], findings))

        gap_note = ""
        if twice:
            again = judge_one(judge, it["question"], resp)
            if again is not None:
                g = score_gap(scores, again)
                gaps.append((g, it["id"], s, sum(again[a] for a in AXES)))
                gap_note = f"  [재채점 {sum(again[a] for a in AXES)}/8, 차이 {g}]"
        print(f"{it['id']:12s} {s}/8{gap_note}")

    if total:
        print(f"\n== 평균 {sum(s for s, *_ in worst) / total:.2f}/8  (채점 {total}, 형식위반 {skipped})")
        for a, v in axes_sum.items():
            print(f"   {a:10s} {v / total:.2f}/2")

        if gaps:
            # 같은 답변을 두 번 채점해 점수가 재현되는가. 재현되지 않으면
            # 평균 점수도 의미가 없으므로 이 지표를 먼저 본다.
            unstable = [g for g in gaps if g[0] > 0]
            mean_gap = sum(g[0] for g in gaps) / len(gaps)
            print(f"\n== 심판 재현성 (같은 문항 2회 채점)")
            print(f"   점수 불일치 {len(unstable)}/{len(gaps)}"
                  f" ({len(unstable) / len(gaps):.0%}), 평균 차이 {mean_gap:.2f}점/8점")
            if mean_gap > 1.0:
                print("   ⚠ 평균 1점을 넘습니다. 점수를 성능 지표로 쓰지 마세요.")
            for g, qid, s1, s2 in sorted(gaps, reverse=True)[:5]:
                if g:
                    print(f"   {qid} {s1}/8 → {s2}/8 (차이 {g})")

        print("\n== 최저 5문항")
        for s, qid, findings in sorted(worst)[:5]:
            if isinstance(findings, dict):
                findings = " / ".join(f"{a}: {v}" for a, v in findings.items())
            print(f"   {qid} {s}/8 — {str(findings)[:220]}")


if __name__ == "__main__":
    main()
