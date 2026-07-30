"""파이프라인 오케스트레이션: 라우팅 → 검색/조회 → 계산 → 생성."""
from __future__ import annotations

from . import calculator, generator
from .retriever import fund_brief, get_docs_index, get_funds_index
from .router import route


def answer(question_id: str, question: str) -> dict:
    trace: list[str] = []
    context_blocks: list[str] = []
    calc_notes: list[str] = []

    r = route(question)
    trace.append(f"[라우팅] {r.describe()}")

    # 역질문 분기: 조건이 빈 추천 질의는 검색·생성 없이 확인 질문으로 응답
    if r.needs_clarification:
        trace.append("[분기] 조건 미충족 추천 질의 → 역질문")
        return _respond(question_id, question, "", trace,
                        generator.clarification_answer(r))

    # 상품 조회: 펀드명 매칭은 라우터 판정과 무관하게 항상 시도한다.
    # ("솔로몬 국공채 뭐가 달라요"처럼 상품 키워드 없이 이름만 나오는 질의 대응)
    hits = get_funds_index().by_name(question)
    if hits:
        if "상품" not in r.categories:
            r.categories.append("상품")
        trace.append(f"[상품조회] 펀드명 매칭 {len(hits)}건: "
                     + ", ".join(f.get("fund_name", "?")[:20] for f in hits[:3]) + " …")
        context_blocks += [fund_brief(f) for f in hits]

    # 문서 검색 (제도·세제·절차·일반)
    doc_hits = get_docs_index().search(question, k=5)
    if doc_hits:
        trace.append("[검색] " + ", ".join(
            f"{h['doc_id']} {h['marker']}(score {h['score']})" for h in doc_hits))
        context_blocks += [f"[{h['source']}]\n{h['text']}" for h in doc_hits]
    else:
        trace.append("[검색] 관련 문서 없음")

    # 세제 계산: 세액공제 질의 + 금액이 있으면 계산기 사용
    if "세제" in r.categories and "세액공제" in question:
        amounts = calculator.extract_amounts(question)
        result, calc_trace, basis = calculator.tax_credit(
            pension_saving=amounts[0] if amounts else 0,
            irp=amounts[1] if len(amounts) > 1 else 0)
        if amounts:
            trace.append(f"[계산] 세액공제({basis} 근거): {calc_trace}")
            calc_notes.append(calc_trace + f" (근거: {basis})")
        else:
            trace.append("[계산] 금액 미제시 → 한도 정보만 근거로 제공")

    answer_text = generator.generate_answer(question, context_blocks, calc_notes)
    trace.append(f"[생성] LLM={generator.get_llm().name}, 근거블록 {len(context_blocks)}개")
    return _respond(question_id, question,
                    "\n\n---\n\n".join(context_blocks), trace, answer_text)


def _respond(qid: str, q: str, ctx: str, trace: list[str], ans: str) -> dict:
    return {
        "question_id": qid,
        "question": q,
        "retrieved_context": ctx,
        "think_trace": "\n".join(trace),
        "answer": ans,
    }
