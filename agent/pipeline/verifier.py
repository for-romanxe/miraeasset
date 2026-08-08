"""답변-근거 대조 검증 (Verifier).

설명회 발표 기준 금융권 최악 실패 유형이 '검증 실패'다. 생성된 답변이
근거(retrieved_context + 계산 결과) 밖의 수치를 말하고 있지 않은지 대조한다.

1단계 (지금, 결정적): 답변의 모든 수치 토큰이 근거 어딘가에 존재하는지 검사.
   수치는 환각의 가장 위험한 형태이고, 문자열 대조만으로 잡을 수 있다.
2단계 (HCX 연동 후): 수치가 아닌 주장 단위의 의미 검증 — verify_claims_llm()에
   검증 프롬프트를 붙인다.
"""
from __future__ import annotations

import re

# 수치 토큰: 1,155,000 / 16.5% / 900만원의 '900' 등. 한 자리 숫자는
# 목록 번호(①1.2.)와 구분이 안 돼 두 자리 이상 또는 소수·퍼센트만 본다.
NUM = re.compile(r"\d[\d,]*\.\d+%?|\d[\d,]{1,}%?|\d%")


def _normalize(text: str) -> str:
    return text.replace(",", "").replace(" ", "")


def _numbers(text: str) -> list[str]:
    return [n for n in NUM.findall(text) if len(n.replace(",", "").rstrip("%")) >= 2 or "%" in n]


def verify_numbers(answer: str, context_blocks: list[str],
                   calc_notes: list[str]) -> tuple[list[str], str]:
    """답변 수치가 근거에 존재하는지 검사. (미확인 수치 목록, 트레이스) 반환."""
    evidence = _normalize(" ".join(context_blocks) + " " + " ".join(calc_notes))
    nums = _numbers(answer)
    if not nums:
        return [], "[검증] 답변에 수치 없음 — 수치 검증 통과"
    unmatched = []
    for n in nums:
        if _normalize(n).rstrip("%") not in evidence:
            unmatched.append(n)
    ok = len(nums) - len(unmatched)
    if unmatched:
        trace = (f"[검증] 답변 수치 {len(nums)}개 중 {ok}개 근거 확인, "
                 f"미확인 {len(unmatched)}개: {', '.join(unmatched[:5])}")
    else:
        trace = f"[검증] 답변 수치 {len(nums)}개 모두 근거에서 확인"
    return unmatched, trace


def verify_claims_llm(answer: str, context_blocks: list[str]) -> str | None:
    """주장 단위 의미 검증 — HCX 연동 후 활성화.

    TODO(HCX): 답변을 문장 단위로 나눠 각 주장이 근거에 의해 지지되는지
    HCX에게 판정시키고, 지지되지 않는 문장을 반환한다.
    """
    return None


def apply(answer: str, context_blocks: list[str], calc_notes: list[str],
          llm_name: str) -> tuple[str, str]:
    """검증을 수행하고 (필요 시 보정된 답변, 트레이스)를 돌려준다.

    미확인 수치가 있으면: Mock 단계에서는 기록만 남기고, 실제 LLM 답변에는
    확정 문장 대신 재확인 안내를 덧붙인다 (근거 없는 수치를 단정하지 않기).
    """
    unmatched, trace = verify_numbers(answer, context_blocks, calc_notes)
    if unmatched and llm_name != "mock":
        answer += ("\n\n※ 위 답변 중 일부 수치는 제공된 자료에서 직접 확인되지 "
                   "않았습니다. 정확한 값은 근거 문서를 확인해 주세요.")
    return answer, trace
