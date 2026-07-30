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

TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")


def tokenize(text: str) -> list[str]:
    out = []
    for tok in TOKEN.findall(text):
        if re.match(r"[가-힣]", tok):
            out.append(tok)
            out += [tok[i:i + 2] for i in range(len(tok) - 1)]
        else:
            out.append(tok.lower())
    return out


class DocsIndex:
    def __init__(self):
        self.chunks = data.load_doc_chunks()
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks])

    def search(self, query: str, k: int = 5, topics: list[str] | None = None) -> list[dict]:
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        hits = []
        for i in order:
            if scores[i] <= 0:
                break
            c = self.chunks[i]
            if topics and c["topic"] not in topics:
                continue
            hits.append({**c, "score": round(float(scores[i]), 2)})
            if len(hits) >= k:
                break
        return hits


NORM = re.compile(r"[\s()\[\]]|증권|자투자신탁|투자신탁|모투자신탁")


def _name_tokens(name: str) -> set[str]:
    """펀드명은 붙여쓰기가 많아 어절 토큰만으로는 질의와 겹치지 않는다.
    질의 토큰화와 같은 bigram 방식으로 맞춘다."""
    return set(tokenize(NORM.sub(" ", name)))


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
