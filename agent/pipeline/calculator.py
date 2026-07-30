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


def pension_income_tax(age: int | None = None) -> tuple[dict, str, str]:
    """연금소득세율(지방소득세 포함). 나이 미상이면 전 구간 표를 돌려준다."""
    table = [(55, 69, 5.5), (70, 79, 4.4), (80, 200, 3.3)]
    if age is None:
        trace = "연금소득세율: 55~69세 5.5% / 70~79세 4.4% / 80세 이상 3.3% (연금 형태 수령 시)"
        return {"table": table}, trace, "doc38"
    rate = next((r for lo, hi, r in table if lo <= age <= hi), None)
    if rate is None:
        trace = f"{age}세는 연금 수령 개시 연령(55세) 미만 — 연금소득세율 적용 대상 아님"
        return {"rate": None}, trace, "doc38"
    trace = f"연금소득세율: {age}세 → {rate}% (55~69세 5.5 / 70대 4.4 / 80세~ 3.3)"
    return {"rate": rate}, trace, "doc38"


def retirement_tax_discount(receive_year: int = 1) -> tuple[dict, str, str]:
    """퇴직소득세 감면율: 연금 수령 시 30%, 11년차부터 40%."""
    rate = 0.4 if receive_year >= 11 else 0.3
    trace = (f"퇴직소득세 감면: 연금수령 {receive_year}년차 → {rate:.0%} 감면 "
             "(1~10년차 30%, 11년차부터 40%)")
    return {"discount": rate}, trace, "doc51"


AMOUNT = re.compile(r"(\d[\d,]*)\s*만\s*원|(\d[\d,]*)\s*원")
AGE = re.compile(r"(\d{2})\s*세")


def extract_age(question: str) -> int | None:
    m = AGE.search(question)
    return int(m.group(1)) if m else None


def extract_amounts(question: str) -> list[int]:
    """질의에서 금액(원)을 추출. v0: 만원/원 표기만."""
    out = []
    for man, won in AMOUNT.findall(question):
        if man:
            out.append(int(man.replace(",", "")) * 10_000)
        elif won:
            out.append(int(won.replace(",", "")))
    return out
