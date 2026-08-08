"""펀드 시리즈 비교표 생성.

'솔로몬 국공채 단기·중장기·장기 뭐가 달라요' 같은 비교 질의에서,
매칭된 펀드들을 6축(위험등급·자산유형·총보수·연금클래스·수익률·순자산)으로
정렬한 마크다운 표를 만들어 근거 블록으로 넣는다. 수치 비교를 LLM의
산문에 맡기지 않고 표로 고정하는 것이 목적.
"""
from __future__ import annotations

COMPARE_HINT = ("비교", "차이", "달라", "다른가", "다르", "뭐가 나", "어떤 게")


def wants_comparison(question: str) -> bool:
    return any(h in question for h in COMPARE_HINT)


def _short_name(f: dict) -> str:
    name = f.get("fund_name") or f.get("isin", "?")
    return name if len(name) <= 22 else name[:21] + "…"


def build_table(funds: list[dict]) -> str:
    """펀드 2개 이상을 축별로 비교하는 마크다운 표 + 근거 표기."""
    rows = [
        "| 구분 | " + " | ".join(_short_name(f) for f in funds) + " |",
        "|---" * (len(funds) + 1) + "|",
    ]

    def row(label, fn):
        cells = []
        for f in funds:
            v = fn(f)
            cells.append("-" if v is None else str(v))
        rows.append(f"| {label} | " + " | ".join(cells) + " |")

    row("위험등급", lambda f: f"{f.get('risk_grade')}등급({f.get('risk_label')})"
        if f.get("risk_grade") else None)
    row("자산유형", lambda f: f.get("asset_type"))
    row("최저 총보수(연)", lambda f: f"{f.get('min_total_fee')}%"
        if f.get("min_total_fee") is not None else None)
    row("연금계좌 클래스", lambda f: "있음" if f.get("has_pension_class") else "없음")
    row("1년 수익률", lambda f: f"{(f.get('returns') or {}).get('y1')}%"
        if (f.get("returns") or {}).get("y1") is not None else None)
    row("3년 수익률", lambda f: f"{(f.get('returns') or {}).get('y3')}%"
        if (f.get("returns") or {}).get("y3") is not None else None)
    row("순자산(백만원)", lambda f: f"{f.get('aum'):,.0f}" if f.get("aum") else None)

    sources = "; ".join(
        f"{f.get('isin')}: {f.get('source', {}).get('file')} "
        f"p{f.get('source', {}).get('summary_page')} (기준 {f.get('base_date')})"
        for f in funds)
    small = [f for f in funds if f.get("is_small_fund")]
    note = ""
    if small:
        note = ("\n주의: " + ", ".join(_short_name(f) for f in small)
                + " — 소규모 집합투자기구(임의해지 가능성 고지 대상)")
    return "[펀드 비교표]\n" + "\n".join(rows) + note + "\n근거: " + sources
