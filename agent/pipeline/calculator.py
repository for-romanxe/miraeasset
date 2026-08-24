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


def tax_credit_premise_correction(question: str, claimed: int,
                                  eligible: int) -> str | None:
    """전액 공제 전제가 계산된 공제대상 한도를 넘으면 교정 문구를 반환한다."""
    claims_full_credit = bool(re.search(r"(전부|모두|다)\s*(세액)?공제|전액\s*(세액)?공제", question))
    if claims_full_credit and claimed > eligible:
        return (f"{claimed:,}원 전부가 세액공제된다는 전제는 맞지 않습니다. "
                f"세액공제 대상은 {eligible:,}원입니다.")
    return None


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


def pension_withdrawal_limit(account_value: int,
                             receive_year: int = 1) -> tuple[dict, str, str]:
    """연금계좌 평가액과 수령연차로 연간 연금수령한도를 계산."""
    if receive_year >= 11:
        trace = f"연금수령 {receive_year}년차부터는 연금수령한도 없음"
        return {"limit": None, "unlimited": True}, trace, "doc39"
    if receive_year < 1:
        raise ValueError("receive_year는 1 이상이어야 합니다")
    limit = account_value / (11 - receive_year) * 1.2
    trace = (f"연금수령한도: {account_value:,}원 ÷ (11 - {receive_year}년차) × 120% "
             f"= {limit:,.0f}원")
    return {"limit": round(limit), "unlimited": False}, trace, "doc39"


UNAVOIDABLE_REASONS = re.compile(
    r"파산|개인회생|천재지변|재난|사망|해외이주|금융회사(?:의)?\s*영업정지")
QUALIFYING_CARE = re.compile(
    r"(?:([3-9]|\d{2,})\s*개월(?:\s*이상)?.{0,8}요양|"
    r"요양.{0,8}([3-9]|\d{2,})\s*개월(?:\s*이상)?)")


def early_withdrawal_tax(amount: int, reason: str = "일반",
                         age: int | None = None) -> tuple[dict, str, str]:
    """세액공제 납입금·운용수익의 중도인출 세금을 계산."""
    unavoidable = bool(UNAVOIDABLE_REASONS.search(reason) or QUALIFYING_CARE.search(reason))
    if unavoidable:
        tax_type = "연금소득세"
        note = "세법상 부득이한 사유"
        if age is None:
            min_tax, max_tax = amount * 0.033, amount * 0.055
            trace = (f"중도인출 {amount:,}원: {reason}은 {note} → 연령에 따라 3.3%~5.5% "
                     f"{tax_type}({min_tax:,.0f}원~{max_tax:,.0f}원)")
            return {"tax": None, "tax_min": round(min_tax), "tax_max": round(max_tax),
                    "rate": None, "rate_range": (0.033, 0.055), "tax_type": tax_type,
                    "unavoidable": True}, trace, "doc20, doc46~doc50"
        rate = 0.055 if age < 70 else 0.044 if age < 80 else 0.033
    else:
        rate = 0.165
        tax_type = "기타소득세"
        note = "세법상 부득이한 사유 아님"
    tax = amount * rate
    trace = (f"중도인출 {amount:,}원 × {rate:.1%} {tax_type} "
             f"({reason}: {note}) = {tax:,.0f}원")
    return {"tax": round(tax), "rate": rate, "tax_type": tax_type,
            "unavoidable": unavoidable}, trace, "doc20, doc46~doc50"


def private_pension_tax_comparison(amount: int,
                                   comprehensive_rate: float) -> tuple[dict, str, str]:
    """연 1,500만원 초과 사적연금의 종합과세와 16.5% 분리과세를 비교."""
    if amount <= 15_000_000:
        trace = f"사적연금 {amount:,}원은 연 15,000,000원 이하 → 종합과세 비교 대상 아님"
        return {"comparison_required": False}, trace, "doc38"
    comprehensive_tax = amount * comprehensive_rate
    separate_tax = amount * 0.165
    favorable = "종합과세" if comprehensive_tax <= separate_tax else "16.5% 분리과세"
    trace = (f"사적연금 전체 {amount:,}원 × 종합세율 {comprehensive_rate:.1%} "
             f"= {comprehensive_tax:,.0f}원 vs × 16.5% = {separate_tax:,.0f}원 "
             f"→ {favorable} 유리")
    return {"comparison_required": True,
            "comprehensive_tax": round(comprehensive_tax),
            "separate_tax": round(separate_tax),
            "favorable": favorable}, trace, "doc38"


def isa_transfer_credit(transfer_amount: int) -> tuple[dict, str, str]:
    """ISA 만기자금의 연금계좌 전환에 따른 추가 세액공제 대상액 계산."""
    additional_eligible = min(transfer_amount * 0.1, 3_000_000)
    trace = (f"ISA 전환금액 {transfer_amount:,}원 × 10% = {transfer_amount * 0.1:,.0f}원, "
             f"300만원 한도 적용 → 추가 세액공제 대상 {additional_eligible:,.0f}원")
    return {"additional_eligible": round(additional_eligible)}, trace, "doc23"


AMOUNT = re.compile(r"(\d[\d,]*)\s*억\s*원|(\d[\d,]*)\s*만\s*원|(\d[\d,]*)\s*원")
AGE = re.compile(r"(\d{2})\s*세")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def extract_age(question: str) -> int | None:
    m = AGE.search(question)
    return int(m.group(1)) if m else None


def extract_amounts(question: str) -> list[int]:
    """질의에서 금액(원)을 추출. v0: 억원/만원/원 표기."""
    out = []
    for eok, man, won in AMOUNT.findall(question):
        if eok:
            out.append(int(eok.replace(",", "")) * 100_000_000)
        elif man:
            out.append(int(man.replace(",", "")) * 10_000)
        elif won:
            out.append(int(won.replace(",", "")))
    return out


def extract_percentages(question: str) -> list[float]:
    return [float(value) / 100 for value in PERCENT.findall(question)]
