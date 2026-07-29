#!/usr/bin/env python3
"""투자설명서 PDF 100건을 메타 스키마(schema.json)로 파싱한다.

전략:
  - 전체 텍스트는 `pdftotext -layout`로 한 번에 뽑는다. 컬럼 정렬이 보존되고 빠르다.
    페이지 구분은 form feed(\\f).
  - 보수 표만 pdfplumber로 요약정보 페이지 1장을 좌표 파싱한다.
    표 안에서 셀이 여러 줄로 접히는 경우(예: '수수료미징구-오프라인-보' / '수체감(C1)')
    레이아웃 텍스트로는 클래스명과 숫자가 다른 줄로 갈라져 매칭이 깨지기 때문.
  - 컬럼 의미는 위치가 아니라 헤더 문자열로 매핑한다. 운용사마다 컬럼 순서가 다르다.

사용:
  python parse_prospectus.py                # 전체
  python parse_prospectus.py KR510902511M   # 특정 ISIN만
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber

BASE = Path(__file__).resolve().parent.parent / "투자설명서"
OUT = Path(__file__).resolve().parent / "out"

NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


# ---------------------------------------------------------------- 공통 유틸

def to_num(s):
    """'1,234' / '-23.62' / '0.235%' -> float. 아니면 None.
    삼성·한화 등 일부 서식은 보수 숫자에 %를 붙여 적는다."""
    if s is None:
        return None
    s = str(s).replace("\n", "").replace(" ", "").strip().rstrip("%")
    if not NUM.match(s):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def pdftotext(path: Path) -> list[str]:
    """페이지별 레이아웃 보존 텍스트."""
    r = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.split("\f")


# ---------------------------------------------------------------- 필드 추출

def find_summary_page(pages: list[str]) -> int | None:
    """요약정보(=간이투자설명서 요약) 페이지 인덱스. 분류·보수·수익률이 모두 여기 있다."""
    for i, t in enumerate(pages[:20]):
        if re.search(r"[<\[]\s*(요약정보|간이투자설명서)", t):
            if "투자비용" in t or "총보수" in t:
                return i
    # 대체 앵커: '분류' 행과 보수 표가 같은 페이지에 있는 곳
    for i, t in enumerate(pages[:20]):
        if re.search(r"투자신탁\s*,\s*증권", t) and "총보수" in t:
            return i
    # 대체 앵커 2: 요약 표기가 없는 본문형 투자설명서(하나·신한 등)는
    # '투자비용' 항목이 있는 페이지가 보수·수익률 표의 시작점이다.
    for i, t in enumerate(pages[:20]):
        if "투자비용" in t and "총보수" in t:
            return i
    return None


def parse_fund_name(pages: list[str]) -> str | None:
    head = "\n".join(pages[:3])
    pats = [
        r"1\.\s*집합투자기구\s*명칭\s*\n\s*([^\n]+)",
        r"집\s*합\s*투\s*자\s*기\s*구\s*명\s*칭\s*[:：]\s*([^\n]+)",
        r"이\s*투자설명서는\s*[’'\"]?([^\n]+?)[’'\"]?\s*에\s*대한",
        # 이름이 길어 줄바꿈되거나 '이'가 앞줄로 밀린 서식(한국투자·KCGI 등)
        r"투자설명서는\s*[’'\"]?(.{4,160}?)[’'\"]?\s*에\s*대한",
        r"이\s*요약정보는\s*[’'\"]?([^\n]+?)[’'\"]?\s*의\s*투자설명서",
    ]
    for p in pats:
        m = re.search(p, head, re.S)
        if m:
            name = re.sub(r"\s+", "", m.group(1)).strip()
            name = re.sub(r"\((?:[A-Z]?\d{3,6})\)$", "", name)  # 꼬리 펀드코드 제거
            if 4 < len(name) < 160:
                return name
    return None


def parse_manager(pages: list[str]) -> str | None:
    head = "\n".join(pages[:3])
    m = re.search(r"2\.\s*집합투자업자\s*명칭\s*\n\s*(.+)", head)
    if m:
        return m.group(1).strip()
    m = re.search(r"([가-힣A-Za-z]{2,20}(?:자산운용|투자신탁운용|운용)\s*(?:주식회사|㈜|\(주\))?)", head)
    return m.group(1).strip() if m else None


def parse_base_date(pages: list[str]) -> str | None:
    head = "\n".join(pages[:6])
    m = re.search(r"작성\s*기준일\s*[:：]?\s*(\d{4})[년.\-]\s*(\d{1,2})[월.\-]\s*(\d{1,2})", head)
    if not m:
        m = re.search(r"4\.\s*작성\s*기준일\s*\n\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", head)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


RISK_LABELS = {
    1: "매우 높은 위험", 2: "높은 위험", 3: "다소 높은 위험",
    4: "보통 위험", 5: "낮은 위험", 6: "매우 낮은 위험",
}


def parse_risk(pages: list[str]):
    """'N등급으로 분류하였습니다' 문장을 1순위 근거로 삼는다.
    표지의 등급 눈금(1 2 3 4 5 6)과 혼동되지 않는 유일한 앵커다."""
    head = "\n".join(pages[:8])
    m = re.search(r"([1-6])\s*등급.{0,40}?분류하였습니다", head, re.S)
    if not m:
        m = re.search(r"투자\s*위험\s*등급\s*\n?\s*([1-6])\s*등급", head)
    if not m:
        m = re.search(r"([1-6])\s*등급\s*[\[(]\s*(매우\s*)?(높은|낮은|보통|다소)", head)
    if not m:
        return None, None
    g = int(m.group(1))
    lm = re.search(rf"{g}\s*등급\s*[\[(]\s*([^)\]]+?)\s*[)\]]", head)
    label = re.sub(r"\s+", " ", lm.group(1)).strip() if lm else RISK_LABELS.get(g)
    return g, label


STRUCT_TAGS = ["투자신탁", "투자회사", "개방형", "폐쇄형", "추가형", "단위형",
               "모자형", "종류형", "전환형", "재간접형", "상장형", "성과연동운용보수형"]


def parse_classification(pages: list[str]):
    """'분류' 행. 라벨이 '분 류'로 띄어져 있거나 값이 다음 줄인 경우가 있어
    라벨 대신 '투자신탁, 증권(...)' 패턴 자체를 앵커로 쓴다."""
    head = "\n".join(pages[:12])
    m = re.search(r"(투자신탁|투자회사)\s*,\s*(증권형?)\s*\(([^)]+)\)(.{0,120})", head)
    if not m:
        return None, None, []
    asset_type = re.sub(r"\s+", "", m.group(3))
    tail = m.group(0)
    structure = [t for t in STRUCT_TAGS if t in tail]

    a = asset_type
    if "재간접" in a:
        group = "재간접형"
    elif "혼합" in a:
        group = "혼합형"
    elif "주식" in a:
        group = "주식형"
    elif "채권" in a:
        group = "채권형"
    elif "파생" in a:
        group = "파생형"
    else:
        group = "기타"
    return asset_type, group, structure


RETURN_KEYS = [(r"최근\s*1\s*년", "y1"), (r"최근\s*2\s*년", "y2"), (r"최근\s*3\s*년", "y3"),
               (r"최근\s*5\s*년", "y5"), (r"설정일\s*이후", "since_inception")]
NOT_FUND_ROW = re.compile(r"비교지수|벤치마크|변동성|표준편차|동종|운용역|운용경력|억원|개월")


def parse_returns_from_tables(tables: list[list[list[str]]]):
    """투자실적 추이 표에서 펀드 본체 행의 연평균 수익률.

    헤더 셀과 값 셀이 한 칸씩 어긋나는 표가 흔해서(운용사별 괘선 차이),
    컬럼 인덱스를 그대로 쓰지 않고 '가장 가까운 헤더 컬럼'에 값을 붙인다.
    """
    empty = {k: None for _, k in RETURN_KEYS}
    for tbl in tables:
        flat = " ".join(c for row in tbl for c in row if c)
        if not re.search(r"최근\s*1\s*년", flat):
            continue
        # 헤더 컬럼 위치 수집
        hdr: dict[str, int] = {}
        hdr_row = None
        for ri, row in enumerate(tbl):
            for ci, cell in enumerate(row):
                c = re.sub(r"\s+", "", cell or "")
                c = re.sub(r"\([^)]*\)$", "", c)   # '설정일 이후(%)'
                c = re.sub(r"차$", "", c)           # '최근 1년차' (교보 등)
                for pat, key in RETURN_KEYS:
                    if key not in hdr and re.fullmatch(pat.replace(r"\s*", ""), c):
                        hdr[key] = ci
                        hdr_row = ri
        # 운용전문인력 표(동종 연평균 수익률)는 최근 1·2년 컬럼만 있다.
        # 펀드 투자실적 표는 최소 최근 1·2·3년을 갖추므로 3개 미만이면 배제.
        if "y1" not in hdr or len(hdr) < 3:
            continue
        for ri, row in enumerate(tbl):
            if hdr_row is not None and ri <= hdr_row:
                continue
            # 기간 행: 날짜가 '2'/'024.05.13~'로 쪼개져 숫자 2가 값으로 오인된다
            if any("~" in (c or "") or "∼" in (c or "") for c in row):
                continue
            label = " ".join(c for c in row if c and to_num(c) is None)
            if NOT_FUND_ROW.search(label):
                continue
            vals = [(ci, to_num(c)) for ci, c in enumerate(row) if to_num(c) is not None]
            # 연도(2024) 같은 값 제외, 수익률 범위만
            vals = [(ci, v) for ci, v in vals if -100 < v < 1000 and abs(v) < 500]
            if len(vals) < 2:
                continue
            out, used = dict(empty), set()
            for ci, v in vals:
                cand = [(abs(ci - hi), k) for k, hi in hdr.items()
                        if k not in used and abs(ci - hi) <= 2]
                if not cand:
                    continue
                _, k = min(cand)
                out[k] = v
                used.add(k)
            if any(v is not None for v in out.values()):
                return out
    return empty


DEC = re.compile(r"-?\d{1,3}\.\d{1,2}(?!\d|\.\d)")


def parse_returns_from_text(pages: list[str], sp: int | None):
    """수익률 표가 병합 셀로 뭉개져 표 추출이 실패한 경우의 폴백.

    레이아웃 텍스트에서 '최근 1년 … 최근 3년' 헤더 줄을 찾고, 아래에서
    펀드 본체 줄의 소수(수익률) 값을 헤더 순서대로 붙인다. 날짜·연도는
    소수점 패턴에 걸리지 않아 자연히 배제된다.
    """
    empty = {k: None for _, k in RETURN_KEYS}
    if sp is None:
        return empty
    lines = "\n".join(pages[sp:sp + 3]).split("\n")
    for i, l in enumerate(lines):
        if not (re.search(r"최근\s*1\s*년", l) and re.search(r"최근\s*[23]\s*년", l)):
            continue
        hdr_window = " ".join(lines[i:i + 3])
        keys = [k for pat, k in RETURN_KEYS if re.search(pat, hdr_window)]
        if not keys:
            continue
        for l2 in lines[i + 1:i + 20]:
            if NOT_FUND_ROW.search(l2) or "~" in l2 or "∼" in l2:
                continue
            # 토큰을 순서대로 읽되 '-'(해당없음)를 빈 슬롯으로 세어
            # 신규 펀드의 설정일이후 값이 앞 컬럼으로 밀리지 않게 한다.
            seq = []
            for tok in l2.split():
                if tok in DASH:
                    seq.append(None)
                elif DEC.fullmatch(tok) and -100 < float(tok) < 500:
                    seq.append(float(tok))
            if sum(1 for v in seq if v is not None) < 2:
                continue
            out = dict(empty)
            for k, v in zip(keys, seq):
                out[k] = v
            return out
    return empty


UNIT_FACTOR = {"원": 1e-6, "천원": 1e-3, "백만원": 1.0, "억원": 100.0, "십억원": 1000.0}


def parse_aum(pages: list[str]):
    """요약재무정보의 자본총계(=순자산총액) 최근 결산기 값.

    반환값은 (백만원 환산값, 원문단위, 결산기, 페이지idx).
    단위 표기가 운용사마다 원/천원/백만원으로 갈려서 환산해 저장한다.
    """
    for i, t in enumerate(pages):
        if "자본총계" not in t:
            continue
        lines = t.split("\n")
        li = next(k for k, l in enumerate(lines) if "자본총계" in l)

        # 운용사(집합투자업자) 소개·재무제표의 자본총계는 펀드 순자산이 아니다.
        # '3조 3,469억원' 같은 한글 단위 표기, 또는 위쪽에 자본잉여금 행이
        # 있으면(회사 대차대조표 — 펀드 재무는 원본·수익조정금 구성) 건너뛴다.
        if re.search(r"[조억]\s*원", lines[li]):
            continue
        if any("자본잉여금" in l for l in lines[max(0, li - 6):li]):
            continue

        # 단위: 자본총계 줄보다 위쪽에서 가장 가까운 (단위: X) 또는 [단위:X].
        # 표가 페이지에 걸쳐 잘리면 단위 표기가 앞 페이지에 남으므로 거기까지 본다.
        unit = None
        search = list(reversed(lines[:li]))
        if i > 0:
            search += list(reversed(pages[i - 1].split("\n")))
        for l in search:
            um = re.search(r"[(\[]\s*단위\s*[:：]?\s*([^)\]]+?)\s*[)\]]", l)
            if um:
                cand = re.sub(r"\s+", "", um.group(1)).split(",")[0]
                if cand in UNIT_FACTOR:
                    unit = cand
                    break
        # 결산기: '항목' 헤더 줄의 첫 번째 N기(...) = 최근 결산기
        period = None
        for l in reversed(lines[:li]):
            if re.search(r"항\s*목", l):
                pm = re.search(r"(\d+\s*기\s*\(?[\d.~\s\-]*\)?)", l)
                if pm:
                    period = re.sub(r"\s+", "", pm.group(1))
                break

        nums = re.findall(r"-?[\d,]+", lines[li].split("자본총계", 1)[1])
        vals = [v for v in (to_num(n) for n in nums) if v is not None]
        if not vals:
            continue
        raw = vals[0]
        if unit is None and raw >= 1e9:
            unit = "원"  # 10억 이상의 원시값은 원 단위로만 설명 가능하다
        million = raw * UNIT_FACTOR[unit] if unit else None
        return million, raw, unit, period, i
    return None, None, None, None, None


# ---------------------------------------------------------------- 보수 표

CLASS_CODE = re.compile(r"\(([A-Za-z][A-Za-z0-9]{0,3}(?:-[A-Za-z0-9]{1,3}){0,2})\)\s*$")
# 'A(수수료선취-오프라인)'처럼 코드가 이름 앞에 오는 서식(우리·KB 등)
CLASS_CODE_HEAD = re.compile(r"^([A-Za-z][A-Za-z0-9]{0,3}(?:-[A-Za-z0-9]{1,3})?)\((?=[가-힣])")


def find_class_code(cell: str):
    m = CLASS_CODE.search(cell)
    if m:
        return m.group(1)
    m = CLASS_CODE_HEAD.match(cell)
    return m.group(1) if m else None


def classify_code(code: str | None, name: str):
    """클래스 코드에서 연금계좌 매수 가능성과 온라인 여부를 판정한다.
    코드가 깨졌을 때를 대비해 한글 명칭도 함께 본다."""
    c = (code or "").upper()
    is_pension = bool(re.match(r"^[A-Z]+-P2", c)) or "퇴직연금" in name
    is_personal = (bool(re.match(r"^[A-Z]+-P(?!2)", c)) or "개인연금" in name) and not is_pension
    is_online = c.endswith("E") and "-" in c or bool(re.search(r"-E\b", c)) or "온라인" in name
    return is_pension, is_personal, is_online


FRONT_LOAD = re.compile(r"납입금액|이내|%")
DASH = {"-", "–", "—", "‐"}


def scan_fee_row(row: list[str], name: str):
    """보수 행에서 보수(%)·총비용 예시·선취수수료 문구를 분리해 모은다.

    컬럼 헤더는 운용사마다 얇은 빈 컬럼이 끼어들어 값과 한두 칸씩 어긋나므로
    헤더 매핑 대신 값을 순서대로 모은다. 슬롯 배정은 표 단위로 뒤에서 한다.

    해당 없는 칸이 '-'로 비어 있으면(예: 개인연금 클래스의 동종유형 총보수)
    첫 보수 숫자가 나온 뒤의 '-'를 빈 슬롯으로 세어 넣는다.
    (첫 숫자 이전의 '-'는 선취판매수수료 '없음' 표기다)
    """
    fees, costs = [], []
    for c in row:
        raw = (c or "").replace("\n", "").strip()
        if raw in DASH:
            if fees:
                fees.append(None)  # 해당 없는 보수 칸
            continue
        v = to_num(raw)
        if v is None:
            continue
        # 소수점이 있으면 보수(%), 없으면 총비용 예시(천원)
        if "." in raw and abs(v) < 20:
            fees.append(v)
        else:
            costs.append(v)

    front = None
    for c in row:
        t = re.sub(r"\s+", "", (c or "").replace("\n", ""))
        if (t and to_num(t) is None and t != name
                and "환매" not in t and FRONT_LOAD.search(t)):
            front = t
            break
    return fees, costs, front


def assign_fee_slots(fees: list, costs: list, front, slots: int):
    """모은 값을 스키마 필드에 배정한다.

    협회 표준 서식의 값 순서는 총보수 → 판매보수 → 동종유형 총보수 → 총보수·비용.
    다만 표 자체에 총보수·비용 컬럼이 없는 서식(slots=3)이 있고,
    개별 행에서 동종유형 칸이 '-' 없이 통째로 생략되는 서식(삼성)이 있어
    표의 최대 보수 개수(slots)를 기준으로 부족분은 동종유형부터 비운다.
    """
    total = fees[0] if len(fees) > 0 else None
    sales = fees[1] if len(fees) > 1 else None
    peer = tcr = None
    if slots >= 4:
        if len(fees) >= 4:
            peer, tcr = fees[2], fees[3]
        elif len(fees) == 3:
            tcr = fees[2]  # 동종유형 생략 행
    else:
        peer = fees[2] if len(fees) > 2 else None

    # 총비용 예시: 표준은 1/2/3/5/10년 5개. 신규 펀드는 1/2/3년 3개만 공시.
    ck = ["y1", "y2", "y3", "y5", "y10"]
    tail = costs[-5:]
    if len(tail) not in (3, 4, 5):
        tail = []
    cost_example = {k: (tail[i] if i < len(tail) else None) for i, k in enumerate(ck)}

    return {
        "total_fee": total, "sales_fee": sales,
        "peer_total_fee": peer, "total_cost_ratio": tcr,
        "cost_example": cost_example,
        "front_load": front, "fee_numbers_raw": fees,
    }


def load_tables(pdf_path: Path, page_idx: int) -> list[list[list[str]]]:
    """요약정보 페이지부터 3페이지분의 표를 한 번에 읽는다.
    보수 표와 투자실적 표가 페이지를 넘겨 배치되는 경우가 있다."""
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for off in range(3):
            pi = page_idx + off
            if pi >= len(pdf.pages):
                break
            for tbl in pdf.pages[pi].extract_tables():
                out.append([[(c or "").strip() for c in row] for row in tbl])
    return out


def parse_fee_table(tables: list[list[list[str]]]):
    """표들에서 보수 행을 수집한다.

    클래스명이 '수수료선취-' / '오프라인형(A)' 처럼 두 그리드 행으로 접히면서
    숫자는 윗행에만 있는 표가 있어, 이름은 인접 행까지 이어 붙여 찾는다.
    """
    classes, warns = [], []
    for tbl in tables:
        flat = " ".join(c for r in tbl for c in r if c)
        # 투자실적(수익률) 표는 숫자 구성이 비슷해 오인하기 쉬우므로 배제
        if re.search(r"최근\s*1\s*년", flat) and "총보수" not in flat:
            continue
        rows = []  # (name, code, fees, costs, front)
        for ri, row in enumerate(tbl):
            n_num = sum(1 for c in row if to_num(c) is not None)
            if n_num < 5:
                continue
            # 이 행 → 다음 행 → 이전 행 순으로 클래스 코드를 찾는다
            name, code = "", None
            for cand_row in (row, tbl[ri + 1] if ri + 1 < len(tbl) else [],
                             tbl[ri - 1] if ri else []):
                for c in cand_row:
                    flatc = re.sub(r"\s+", "", (c or "").replace("\n", ""))
                    code = find_class_code(flatc)
                    if code:
                        name = flatc
                        break
                if code:
                    break
            if not code:
                # 단일 클래스 펀드는 클래스명 자리에 '투자신탁'만 적혀 있다
                first = next((re.sub(r"\s+", "", (c or "").replace("\n", ""))
                              for c in row if (c or "").strip()), "")
                if first in ("투자신탁", "투자회사") and "총보수" in flat:
                    name, code = first, "단일"
                else:
                    continue
            # 이름이 다음 행에 있었다면 앞부분을 이어 붙인다
            if name and not name.startswith(("수수료", "클래스", "종류", "투자")):
                for c in row:
                    fc = re.sub(r"\s+", "", (c or "").replace("\n", ""))
                    if fc and to_num(fc) is None and fc.startswith("수수료"):
                        name = fc + name
                        break

            fees, costs, front = scan_fee_row(row, name)
            # 보수 행은 반드시 총비용 예시(정수 천원 값)를 동반한다.
            # 클래스명이 붙은 '수익률' 행(예: 클래스별 투자실적)을 걸러내는 가드.
            if len(costs) < 2 or not fees:
                continue
            rows.append((name, code, fees, costs, front))

        slots = max((len(f) for _, _, f, _, _ in rows), default=0)
        for name, code, fees, costs, front in rows:
            vals = assign_fee_slots(fees, costs, front, slots)
            is_p, is_pp, is_on = classify_code(code, name)
            classes.append({
                "code": code, "name": name,
                "front_load": vals["front_load"],
                "total_fee": vals["total_fee"],
                "sales_fee": vals["sales_fee"],
                "peer_total_fee": vals["peer_total_fee"],
                "total_cost_ratio": vals["total_cost_ratio"],
                "cost_example": vals["cost_example"],
                "fee_numbers_raw": vals["fee_numbers_raw"],
                "is_pension": is_p,
                "is_personal_pension": is_pp,
                "is_online": is_on,
            })
    seen, uniq = set(), []
    for c in classes:
        if c["code"] in seen:
            continue
        seen.add(c["code"])
        uniq.append(c)
    return uniq, warns


# ---------------------------------------------------------------- 엔트리

def parse_one(isin: str) -> dict:
    path = BASE / isin / f"R2_{isin}.pdf"
    pages = pdftotext(path)
    warns: list[str] = []

    sp = find_summary_page(pages)
    if sp is None:
        warns.append("요약정보 페이지를 찾지 못함")

    name = parse_fund_name(pages)
    if not name:
        warns.append("펀드명 추출 실패")
    grade, label = parse_risk(pages)
    if grade is None:
        warns.append("위험등급 추출 실패")
    atype, agroup, structure = parse_classification(pages)
    if not atype:
        warns.append("상품분류(자산유형) 추출 실패")
    aum, aum_raw, aum_unit, aum_period, aum_page = parse_aum(pages)
    if aum_raw is None:
        warns.append("시장잔고(자본총계) 추출 실패")
    elif aum is None:
        warns.append(f"시장잔고 단위 미상 (원문값 {aum_raw:,.0f})")

    tables = load_tables(path, sp) if sp is not None else []
    classes, cw = parse_fee_table(tables)
    warns += cw
    if not classes:
        warns.append("판매클래스 추출 실패")
    elif not any(c["total_fee"] is not None for c in classes):
        warns.append("총보수 값 추출 실패")

    returns = parse_returns_from_tables(tables)
    if all(v is None for v in returns.values()):
        returns = parse_returns_from_text(pages, sp)
    if all(v is None for v in returns.values()):
        # 설정 1년 미만 펀드는 원문에 '해당사항 없음'으로 적혀 있다. 추출 실패와 구분한다.
        blob = " ".join(c for t in tables for r in t for c in r if c)
        if re.search(r"(해당\s*사항\s*없음|신규\s*(설정|펀드)|미\s*도래)", blob):
            warns.append("수익률 원문 미공시(신규 설정 등)")
        else:
            warns.append("수익률 추출 실패")

    fees = [c["total_fee"] for c in classes if c["total_fee"] is not None]
    pension_fees = [c["total_fee"] for c in classes
                    if c["is_pension"] and c["total_fee"] is not None]

    return {
        "isin": isin,
        "fund_name": name,
        "asset_manager": parse_manager(pages),
        "base_date": parse_base_date(pages),
        "risk_grade": grade,
        "risk_label": label,
        "asset_type": atype,
        "asset_type_group": agroup,
        "structure": structure,
        "classes": classes,
        "has_pension_class": any(c["is_pension"] or c["is_personal_pension"] for c in classes),
        "min_total_fee": min(fees) if fees else None,
        "pension_total_fee": min(pension_fees) if pension_fees else None,
        "returns": returns,
        "aum": round(aum, 1) if aum is not None else None,
        "aum_raw": aum_raw,
        "aum_unit": aum_unit,
        "aum_period": aum_period,
        "is_small_fund": (aum < 5000) if aum is not None else None,
        "page_count": len(pages) - 1,
        "source": {
            "file": f"투자설명서/{isin}/R2_{isin}.pdf",
            "summary_page": (sp + 1) if sp is not None else None,
            "aum_page": (aum_page + 1) if aum_page is not None else None,
        },
        "parse_warnings": warns,
    }


def main():
    targets = sys.argv[1:] or sorted(p.name for p in BASE.iterdir() if p.is_dir())
    OUT.mkdir(exist_ok=True)
    results = []
    for i, isin in enumerate(targets, 1):
        try:
            rec = parse_one(isin)
        except Exception as e:  # 한 건 실패로 전체가 멈추지 않게
            rec = {"isin": isin, "parse_warnings": [f"예외: {type(e).__name__}: {e}"]}
        results.append(rec)
        w = len(rec.get("parse_warnings", []))
        print(f"[{i:3d}/{len(targets)}] {isin}  경고 {w}건"
              f"{'  ' + ' / '.join(rec['parse_warnings']) if w else ''}", flush=True)

    (OUT / "funds.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {OUT / 'funds.json'} ({len(results)}건)")


if __name__ == "__main__":
    main()
