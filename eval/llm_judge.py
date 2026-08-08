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
JUDGE_PROMPT = """당신은 연금 상담 답변의 채점자입니다. 아래 [질문]에 대한 [답변]을
[근거자료]와 대조해 4개 축으로 채점하세요.

채점 축 (각 0~2점):
- grounding: 답변의 모든 사실·수치가 근거자료 안에서 확인되는가.
  근거에 없는 주장이 하나라도 있으면 0점.
- relevance: 질문이 실제로 물은 것에 답했는가. 관련 정보 나열에 그치면 1점.
- compliance: 규정 준수 — 특정 상품을 단정적으로 추천하지 않는가,
  답변할 수 없는 것을 아는 척하지 않는가, 출처를 밝혔는가.
- clarity: 연금을 모르는 고객이 읽고 이해할 수 있는가. 용어를 풀어 썼는가.

반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 붙이지 마세요.
{{"grounding": 0, "relevance": 0, "compliance": 0, "clarity": 0, "reason": "한 줄 총평"}}

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

    total, axes_sum, skipped, worst = 0, {}, 0, []
    for it in items:
        resp = pipeline.answer(it["id"], it["question"])
        scores = judge_one(judge, it["question"], resp)
        if scores is None:
            skipped += 1
            continue
        s = sum(scores[a] for a in ("grounding", "relevance", "compliance", "clarity"))
        total += 1
        for a in ("grounding", "relevance", "compliance", "clarity"):
            axes_sum[a] = axes_sum.get(a, 0) + scores[a]
        worst.append((s, it["id"], scores.get("reason", "")))
        print(f"{it['id']:12s} {s}/8  {scores}")

    if total:
        print(f"\n== 평균 {sum(s for s, *_ in worst) / total:.2f}/8  (채점 {total}, 형식위반 {skipped})")
        for a, v in axes_sum.items():
            print(f"   {a:10s} {v / total:.2f}/2")
        print("\n== 최저 5문항")
        for s, qid, reason in sorted(worst)[:5]:
            print(f"   {qid} {s}/8 — {reason}")


if __name__ == "__main__":
    main()
