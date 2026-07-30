"""세제 계산기 v0 — 수치 계산은 LLM이 아니라 여기서 한다.

각 함수는 (결과 dict, 계산 과정 문자열, 근거 doc_id)를 돌려준다.
수치·규칙은 안내문서(doc41 등)를 근거로 하며, 답변에는 근거 문서를 함께 표시한다.
"""
from __future__ import annotations

import re

PENSION_SAVING_CAP = 6_000_000     # 연금저축 세액공제 한도 (연)
TOTAL_CAP = 9_000_000              # 연금저축+IRP 합산 한도 (연)
RATE_LOW = 0.165                   # 총급여 5,500만원 이하 (지방소득세 포함)
RATE_HIGH = 0.132
INCOME_THRESHOLD = 55_000_000


def tax_credit(pension_saving: int = 0, irp: int = 0,
               gross_income: int | None = None) -> tuple[dict, str, str]:
    """연금저축·IRP 납입액의 세액공제액 계산."""
    ps = min(pension_saving, PENSION_SAVING_CAP)
    eligible = min(ps + irp, TOTAL_CAP)
    if gross_income is None:
        low, high = eligible * RATE_LOW, eligible * RATE_HIGH
        trace = (f"공제대상 min(연금저축 {pension_saving:,} → {ps:,}) + IRP {irp:,} "
                 f"= {eligible:,}원(한도 {TOTAL_CAP:,}) × 16.5%/13.2% "
                 f"= {low:,.0f}원(총급여 5,500만 이하) / {high:,.0f}원(초과)")
        result = {"eligible": eligible, "credit_low": round(low), "credit_high": round(high)}
    else:
        rate = RATE_LOW if gross_income <= INCOME_THRESHOLD else RATE_HIGH
        credit = eligible * rate
        trace = (f"공제대상 {eligible:,}원 × {rate:.1%} (총급여 {gross_income:,}원 기준) "
                 f"= {credit:,.0f}원")
        result = {"eligible": eligible, "rate": rate, "credit": round(credit)}
    return result, trace, "doc41"


AMOUNT = re.compile(r"(\d[\d,]*)\s*만\s*원|(\d[\d,]*)\s*원")


def extract_amounts(question: str) -> list[int]:
    """질의에서 금액(원)을 추출. v0: 만원/원 표기만."""
    out = []
    for man, won in AMOUNT.findall(question):
        if man:
            out.append(int(man.replace(",", "")) * 10_000)
        elif won:
            out.append(int(won.replace(",", "")))
    return out
