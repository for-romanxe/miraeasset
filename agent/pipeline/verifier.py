"""답변-근거 대조 검증 (Verifier).

설명회 발표 기준 금융권 최악 실패 유형이 '검증 실패'다. 생성된 답변이
근거(retrieved_context + 계산 결과) 밖의 수치를 말하고 있지 않은지 대조한다.

1단계 (결정적): 답변의 모든 수치 토큰이 근거 어딘가에 존재하는지 검사.
   수치는 환각의 가장 위험한 형태이고, 문자열 대조만으로 잡을 수 있다.
   단, 문자열 대조만으로는 두 가지를 못 잡는다:
     - 근거의 두 수치를 정당하게 합·차 계산한 새 수치를 "미확인"으로 오탐
       (tax-17: 330만-200만=130만). _derivable()로 구제한다.
     - 수치가 근거에 문자 그대로 있지만 가리키는 대상이 다른 경우
       (연금 "수령" 종합과세 기준 1,500만원을 "납입" 한도로 잘못 서술해도
       "1500"이라는 문자열 자체는 근거에 있어 1단계를 통과함). 이건 문자열
       대조로는 원리상 못 잡는다 — 그래서 2단계가 필요하다 (#43).
2단계 (HCX): 문장 단위 의미 검증. verify_claims_llm()이 답변을 문장으로 쪼개
   각 문장이 근거로 지지되는지 HCX에 판정시킨다. 답변마다 호출 하나가 추가로
   붙으므로 비용·지연이 늘어난다 — scope="numeric"으로 수치 포함 문장만 보내
   비용을 줄인다 (전체 문장 검증과의 비교는 eval/verifier_bench.py).
"""
from __future__ import annotations

import json
import re

from ..llm import get_llm

# 수치 토큰: 1,155,000 / 16.5% / 900만원의 '900' 등. 한 자리 숫자는
# 목록 번호(①1.2.)와 구분이 안 돼 두 자리 이상 또는 소수·퍼센트만 본다.
NUM = re.compile(r"\d[\d,]*\.\d+%?|\d[\d,]{1,}%?|\d%")

_SENT_END = re.compile(r"(?<=[.!?])\s+")


def _normalize(text: str) -> str:
    return text.replace(",", "").replace(" ", "")


def _numbers(text: str) -> list[str]:
    return [n for n in NUM.findall(text) if len(n.replace(",", "").rstrip("%")) >= 2 or "%" in n]


def _num_value(tok: str) -> float | None:
    """수치 토큰을 숫자로. %는 단위가 달라 합·차 유도 대상에서 제외한다."""
    if "%" in tok:
        return None
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _derivable(target: str, evidence_nums: list[float]) -> bool:
    """target이 근거 수치 두 개의 합·차로 정당하게 유도됐는지 확인."""
    v = _num_value(target)
    if v is None:
        return False
    for i, a in enumerate(evidence_nums):
        for b in evidence_nums[i + 1:]:
            if abs(a + b - v) < 0.5 or abs(a - b - v) < 0.5 or abs(b - a - v) < 0.5:
                return True
    return False


def _split_sentences(text: str) -> list[str]:
    """줄바꿈으로 먼저 나누고(목록 항목 보존), 줄 안에서 문장 부호로 다시 나눈다."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("근거:") or line.startswith("※"):
            continue  # 출처 표기·재확인 안내 줄은 주장이 아니라 검증 대상이 아님
        for s in _SENT_END.split(line):
            s = s.strip(" -*·")
            if s:
                out.append(s)
    return out


def verify_numbers(answer: str, context_blocks: list[str],
                   calc_notes: list[str]) -> tuple[list[str], str]:
    """답변 수치가 근거에 존재하는지 검사. (미확인 수치 목록, 트레이스) 반환."""
    evidence_text = " ".join(context_blocks) + " " + " ".join(calc_notes)
    evidence_norm = _normalize(evidence_text)
    evidence_nums = [v for v in (_num_value(n) for n in _numbers(evidence_text)) if v is not None]
    nums = _numbers(answer)
    if not nums:
        return [], "[검증] 답변에 수치 없음 — 수치 검증 통과"
    unmatched, derived = [], []
    for n in nums:
        if _normalize(n).rstrip("%") in evidence_norm:
            continue
        if _derivable(n, evidence_nums):
            derived.append(n)
            continue
        unmatched.append(n)
    ok = len(nums) - len(unmatched) - len(derived)
    parts = [f"답변 수치 {len(nums)}개 중 {ok}개 근거 확인"]
    if derived:
        parts.append(f"유도 산술 인정 {len(derived)}개({', '.join(derived[:5])})")
    if unmatched:
        parts.append(f"미확인 {len(unmatched)}개({', '.join(unmatched[:5])})")
    return unmatched, "[검증] " + ", ".join(parts)


# 근거에 문자 그대로 있는 수치라도 "무엇에 대한 값인가"가 틀리면 1단계로는
# 못 잡는다 (1,500만원=수령 종합과세 기준 vs 납입 한도). 문장 단위로 근거와
# 다시 대조해 이 유형을 잡는다. findings를 먼저 요구하지 않고 번호만 받는 건
# 이 검증이 채점(judge)이 아니라 이진 판정이라 그럴 필요가 없어서다 — 다만
# "정당한 유도 산술은 지지로 본다"는 조건은 명시해야 tax-17 같은 오탐이 재발한다.
CLAIM_VERIFY_PROMPT = """당신은 사실 검증관입니다. [근거]와 [계산 결과]를 보고
[답변] 문장들이 지지되는지 판정하세요.

지지(O)로 판정:
- 문장의 사실·수치가 [근거]나 [계산 결과]에 그대로 있음
- [근거]에 있는 두 수치의 합·차로 자연스럽게 유도됨
- 특정 사실·수치를 새로 주장하지 않는 연결·설명 문장

미지지(X)로 판정:
- [근거]·[계산 결과] 어디에도 없는 수치·사실을 단정함
- 수치 자체는 [근거]에 있지만, 그 수치가 실제로 가리키는 대상·기준과
  문장의 주장이 다름 (예: 근거의 "수령 시 기준"을 "납입 한도"로 서술)

문장마다 번호가 매겨져 있습니다. 미지지 문장 번호만 JSON 배열로 답하세요.
모두 지지되면 []. 문장을 옮겨 적지 말고 번호만 쓰세요.

[근거]
{context}

[계산 결과]
{calc}

[답변 — 번호별 문장]
{numbered}

[답변] 미지지 문장 번호의 JSON 배열만 출력. 예: [2, 5]"""


def _parse_indices(raw: str) -> list[int]:
    m = re.search(r"\[[\d,\s]*\]", raw)
    if not m:
        return []
    try:
        return [int(x) for x in json.loads(m.group())]
    except (json.JSONDecodeError, ValueError):
        return []


def verify_claims_llm(answer: str, context_blocks: list[str], calc_notes: list[str],
                      *, scope: str = "numeric") -> tuple[list[str], str | None]:
    """HCX로 문장 단위 의미 검증.

    scope="numeric": 수치가 포함된 문장만 검증 대상으로 보낸다 (기본값 —
    이 검증의 목적이 "맥락이 틀린 수치" 탐지이므로 수치 없는 문장까지 보낼
    이유가 적고, 프롬프트가 짧아져 비용도 준다).
    scope="all": 모든 문장을 보낸다 — 수치 없는 문장의 사실 오류까지 잡지만
    호출당 비용·지연이 늘어난다. eval/verifier_bench.py로 실측 비교한다.

    반환: (미지지 문장 목록, 트레이스). Mock 단계에서는 (빈 목록, None) —
    apply()가 None이면 트레이스에 이 단계를 아예 안 붙인다.
    """
    llm = get_llm()
    if llm.name == "mock":
        return [], None
    sentences = _split_sentences(answer)
    targets = [(i, s) for i, s in enumerate(sentences)
              if scope == "all" or _numbers(s)]
    if not targets:
        return [], "[검증2] 수치 포함 문장 없음 — 의미 검증 생략"
    numbered = "\n".join(f"{i}. {s}" for i, s in targets)
    ctx = "\n\n---\n\n".join(context_blocks)[:4000] if context_blocks else "(근거 없음)"
    calc = "\n".join(calc_notes) if calc_notes else "(없음)"
    prompt = CLAIM_VERIFY_PROMPT.format(context=ctx, calc=calc, numbered=numbered)
    raw = llm.generate(prompt, max_tokens=200)
    bad = [sentences[i] for i in _parse_indices(raw) if 0 <= i < len(sentences)]
    trace = (f"[검증2] {scope} 범위 {len(targets)}문장 검증, 미지지 {len(bad)}건"
             + (f": {bad[0][:60]}" if bad else ""))
    return bad, trace


def apply(answer: str, context_blocks: list[str], calc_notes: list[str],
          llm_name: str) -> tuple[str, str]:
    """검증을 수행하고 (필요 시 보정된 답변, 트레이스)를 돌려준다.

    미확인 수치나 미지지 문장이 있으면: Mock 단계에서는 기록만 남기고, 실제
    LLM 답변에는 확정 문장 대신 재확인 안내를 덧붙인다 (근거 없는 내용을
    단정하지 않기). 2단계는 1단계 결과와 무관하게 항상 실행한다 — "문자열은
    근거에 있지만 대상이 틀린" 경우는 1단계가 원리상 못 잡기 때문이다.
    """
    unmatched, trace = verify_numbers(answer, context_blocks, calc_notes)
    unsupported, trace2 = verify_claims_llm(answer, context_blocks, calc_notes)
    if trace2:
        trace += "\n" + trace2
    if (unmatched or unsupported) and llm_name != "mock":
        answer += ("\n\n※ 위 답변 중 일부 내용은 제공된 자료에서 직접 확인되지 "
                   "않았습니다. 정확한 값은 근거 문서를 확인해 주세요.")
    return answer, trace
