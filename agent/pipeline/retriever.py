"""검색 계층 v0.

- DocsIndex: 안내문서 청크 BM25 검색. 한글은 어절 + 2음절 bigram 토큰으로
  형태소 분석기 없이 재현율을 확보한다.
- FundsIndex: funds.json 정형 조회. 펀드명 토큰 매칭과 조건 필터.
  수치 비교·정렬은 LLM이 아니라 여기서 끝낸다.
"""
from __future__ import annotations

import re
from functools import lru_cache

from rank_bm25 import BM25Okapi

from .. import data

# '100%'는 백분율 토큰으로 통째로 잡는다 — 한도·비율 질의의 핵심 변별자.
# 반면 맨숫자(400, 2025)는 금액·연도라 변별력이 없다 (tokenize에서 가중 구분)
TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+%|\d+")


def tokenize(text: str) -> list[str]:
    """어절 + 2음절 bigram. 반복 횟수가 곧 BM25 가중치다.

    - 한글 어절은 2회(온전한 매칭 우대), bigram·trigram은 1회(재현율 확보).
      trigram은 "종합과세된다는데" 같은 조사·어미 붙은 어절과
      "종합과세"의 매칭을 살린다 (형태소 분석기 없이 버티는 방법)
    - 영문 약어(ETF, DB, DC, IRP)는 3회 — 흔한 한글 bigram에 묻히기 쉬운
      반면 변별력은 가장 높은 토큰이라 강하게 친다
    - 숫자는 1회 — 금액·연도 등 우연히 겹치는 경우가 많아 변별력이 없다
    """
    out = []
    for tok in TOKEN.findall(text):
        if re.match(r"[가-힣]", tok):
            out += [tok, tok]
            out += [tok[i:i + 2] for i in range(len(tok) - 1)]
            out += [tok[i:i + 3] for i in range(len(tok) - 2)]
        elif tok.isdigit():
            out.append(tok)
        else:
            out += [tok.lower()] * 3  # 영문 약어와 '100%' 같은 백분율
    return out


# 고객 표현 ↔ 문서 용어의 어휘 갭을 메우는 도메인 동의어.
# 질의에 키가 있으면 값 단어들을 질의에 덧붙인다 (BM25라 추가만으로 가중).
# 주의: 키는 부분 문자열로 매칭되므로 다른 단어에 포함되지 않게 어간+어미로
# 구체화한다 ("해지"는 "정해지는"에 걸린다).
QUERY_EXPAND = {
    "해지하": "중도인출 기타소득세",
    "해지할": "중도인출 기타소득세",
    "해지를": "중도인출 기타소득세",
    "깨면": "중도해지 중도인출 기타소득세",
    "불이익": "세금 기타소득세 페널티",
    "살 수": "매수 매매 거래",
    "사고 싶": "매수 매매",
    "수수료": "보수 총보수",
    "안정적": "위험등급 낮은위험 채권",
    "얼마까지": "한도",
}

TITLE_BOOST = 3  # 제목 토큰 반복 횟수. 제목은 주제를 압축하므로 강하게 친다


class DocsIndex:
    def __init__(self):
        self.chunks = data.load_doc_chunks()
        self.bm25 = BM25Okapi([
            tokenize(c["text"]) + tokenize(c["title"]) * TITLE_BOOST
            for c in self.chunks])

    def search(self, query: str, k: int = 5, topics: list[str] | None = None,
               max_per_doc: int = 2) -> list[dict]:
        for key, extra in QUERY_EXPAND.items():
            if key in query:
                query += " " + extra
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        hits, per_doc = [], {}
        for i in order:
            if scores[i] <= 0:
                break
            c = self.chunks[i]
            if topics and c["topic"] not in topics:
                continue
            # 긴 문서가 상위 슬롯을 독식하지 않게 문서당 청크 수를 제한한다
            if per_doc.get(c["doc_id"], 0) >= max_per_doc:
                continue
            per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1
            hits.append({**c, "score": round(float(scores[i]), 2)})
            if len(hits) >= k:
                break
        return hits


NORM = re.compile(r"[\s()\[\]]|증권|자투자신탁|투자신탁|모투자신탁")


# 거의 모든 펀드명에 들어가는 범용 토큰. 이것만으로 펀드가 매칭되면 오탐이다
# ("퇴직연금 적립금 100%..."가 '한국투자퇴직연금...' 펀드에 걸리는 사례)
NAME_STOP = {"연금", "퇴직", "퇴직연", "직연금", "퇴직연금", "증권", "투자", "신탁",
             "투자신", "자신탁", "펀드", "주식", "채권", "혼합", "클래스",
             # '연금저축 세액공제…' 같은 제도 질의가 연금저축 펀드에 오매칭되는 것 방지
             "연금저", "금저축", "저축", "연금저축", "개인연금", "개인연", "인연금"}


def _name_tokens(name: str) -> set[str]:
    """펀드명은 붙여쓰기가 많아 어절 토큰만으로는 질의와 겹치지 않는다.
    질의 토큰화와 같은 방식으로 맞추되 범용 토큰은 제외한다."""
    return set(tokenize(NORM.sub(" ", name))) - NAME_STOP


class FundsIndex:
    def __init__(self):
        self.funds = data.load_funds()
        self._toks = [(f, _name_tokens(f.get("fund_name") or "")) for f in self.funds]

    def by_name(self, query: str, k: int = 5) -> list[dict]:
        """질의-펀드명 토큰 교집합 크기로 스코어링. 시리즈 질의면 여러 건이 잡힌다.
        최고점 대비 60% 미만은 우연히 일부 단어만 겹친 것으로 보고 버린다."""
        q = set(tokenize(query))
        scored = []
        for f, toks in self._toks:
            n = len(toks & q)
            if n >= 4:
                scored.append((n, f))
        if not scored:
            return []
        scored.sort(key=lambda x: -x[0])
        cutoff = max(4, scored[0][0] * 0.6)
        return [f for n, f in scored if n >= cutoff][:k]

    def filter(self, *, max_risk_grade: int | None = None, min_risk_grade: int | None = None,
               asset_type_group: str | None = None, pension_only: bool = False,
               sort_by_fee: bool = False, k: int = 10) -> list[dict]:
        out = []
        for f in self.funds:
            g = f.get("risk_grade")
            if max_risk_grade is not None and (g is None or g > max_risk_grade):
                continue
            if min_risk_grade is not None and (g is None or g < min_risk_grade):
                continue
            if asset_type_group and f.get("asset_type_group") != asset_type_group:
                continue
            if pension_only and not f.get("has_pension_class"):
                continue
            out.append(f)
        if sort_by_fee:
            out.sort(key=lambda f: (f.get("min_total_fee") is None, f.get("min_total_fee")))
        return out[:k]


def fund_brief(f: dict) -> str:
    """근거 표시에 쓰는 펀드 한 줄 요약 (출처 파일 포함)."""
    ret = f.get("returns") or {}
    return (f"{f.get('fund_name')} | 위험 {f.get('risk_grade')}등급({f.get('risk_label')}) "
            f"| {f.get('asset_type')} | 최저 총보수 {f.get('min_total_fee')}% "
            f"| 1년 수익률 {ret.get('y1')}% | 순자산 {f.get('aum')}백만원 "
            f"| 근거: {f.get('source', {}).get('file')} "
            f"p{f.get('source', {}).get('summary_page')} (작성기준 {f.get('base_date')})")


@lru_cache(maxsize=1)
def get_docs_index() -> DocsIndex:
    return DocsIndex()


@lru_cache(maxsize=1)
def get_funds_index() -> FundsIndex:
    return FundsIndex()
