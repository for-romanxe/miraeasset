"""파이프라인 오케스트레이션: 라우팅 → 검색/조회 → 계산 → 생성."""
from __future__ import annotations

import os
import re

from . import calculator, compare, generator, verifier
from .retriever import fund_brief, get_docs_index, get_funds_index, parse_fund_filter
from .router import build_hcx_router_prompt, route, route_from_hcx


# 세액공제 계산 트리거. "세액공제"라는 용어를 안 쓰고 묻는 경우가 많다
# ("다 공제되나요?", "얼마나 돌려받나요?"). 바깥에서 이미 세제 분류를 통과한
# 질의만 들어오므로 이 정도 폭은 안전하다.
TAX_CREDIT_ASK = re.compile(r"세액\s*공제|공제\s*(되|받|해|가능)|돌려받|환급")


def answer(question_id: str, question: str) -> dict:
    trace: list[str] = []
    context_blocks: list[str] = []
    calc_notes: list[str] = []
    has_table = False  # 비교표 경로 여부 — verifier 2단계 생략 판단에 쓴다 (#59)

    r, routing_note = _select_route(question)
    trace.append(f"[라우팅] {routing_note} | {r.describe()}")

    # 안전성 가드: 개인정보·프롬프트 공격성 질의는 검색 없이 정중히 거절
    if r.unsafe:
        trace.append("[가드] 안전성 이슈 감지 → 거절 응답")
        return _respond(question_id, question, "", trace, generator.guard_answer())

    # 정보한계: 보유 데이터로 답할 수 없는 범위는 무리한 답변 대신 한계 고지
    if r.out_of_scope:
        trace.append("[한계] 데이터 범위 밖 질의 → 한계 고지")
        return _respond(question_id, question, "", trace, generator.limitation_answer())

    # 역질문 분기: 조건이 빈 추천 질의는 검색·생성 없이 확인 질문으로 응답
    if r.needs_clarification:
        trace.append("[분기] 조건 미충족 추천 질의 → 역질문")
        return _respond(question_id, question, "", trace,
                        generator.clarification_answer(r))

    if r.assumptions:
        trace.append("[가정] " + generator.assumption_disclosure(r))

    # 상품 조회: 펀드명 매칭은 라우터 판정과 무관하게 항상 시도한다.
    # ("솔로몬 국공채 뭐가 달라요"처럼 상품 키워드 없이 이름만 나오는 질의 대응)
    hits = get_funds_index().by_name(question)
    if hits:
        if "상품" not in r.categories:
            r.categories.append("상품")
        trace.append(f"[상품조회] 펀드명 매칭 {len(hits)}건: "
                     + ", ".join(f.get("fund_name", "?")[:20] for f in hits[:3]) + " …")
        # 비교 질의 + 복수 매칭이면 산문 대신 축별 비교표를 근거로 고정한다
        if len(hits) >= 2 and compare.wants_comparison(question):
            trace.append(f"[비교표] {len(hits)}개 펀드 6축 비교표 생성")
            context_blocks.append(compare.build_table(hits))
            has_table = True
        context_blocks += [fund_brief(f) for f in hits]
    else:
        # 조건 검색: "총보수 0.3% 아래 채권형"처럼 이름 없는 조건 질의는
        # by_name이 못 잡아 "해당 상품 없음" 오답이 났다 (석규 QA H 5/15)
        cond = parse_fund_filter(question)
        if cond:
            matches = get_funds_index().filter(**cond, k=5)
            if matches:
                if "상품" not in r.categories:
                    r.categories.append("상품")
                desc = ", ".join(f"{k}={v}" for k, v in cond.items())
                trace.append(f"[상품필터] 조건({desc}) 매칭 {len(matches)}건: "
                             + ", ".join(f.get("fund_name", "?")[:20] for f in matches[:3]) + " …")
                context_blocks.append(
                    "[조건 검색 결과 — 아래는 조건에 맞는 취급 펀드 목록입니다]")
                context_blocks += [fund_brief(f) for f in matches]

    # 문서 검색 (제도·세제·절차·일반)
    doc_hits = get_docs_index().search(question, k=5)
    if doc_hits:
        trace.append("[검색] " + ", ".join(
            f"{h['doc_id']} {h['marker']}(score {h['score']})" for h in doc_hits))
        context_blocks += [f"[{h['source']}]\n{h['text']}" for h in doc_hits]
    else:
        trace.append("[검색] 관련 문서 없음")

    # 세제 계산: 수치가 걸린 질의는 LLM이 아니라 계산기로
    if "세제" in r.categories:
        if TAX_CREDIT_ASK.search(question) and "ISA" not in question:
            amounts = calculator.extract_amounts(question)
            # 계좌명이 있으면 위치 기준으로 배정한다. 언급 순서대로 넣으면
            # "IRP 200만원이랑 연금저축 700만원"에서 캡이 잘못 적용된다.
            by_account = calculator.split_amounts_by_account(question)
            if by_account is None:
                by_account = (amounts[0] if amounts else 0,
                              amounts[1] if len(amounts) > 1 else 0)
            result, calc_trace, basis = calculator.tax_credit(
                pension_saving=by_account[0], irp=by_account[1])
            if amounts:
                trace.append(f"[계산] 세액공제({basis} 근거): {calc_trace}")
                calc_notes.append(calc_trace + f" (근거: {basis})")
                correction = calculator.tax_credit_premise_correction(
                    question, sum(amounts), result["eligible"])
                if correction:
                    trace.append(f"[전제교정] {correction}")
                    calc_notes.append(correction + f" (근거: {basis})")
            else:
                trace.append("[계산] 금액 미제시 → 한도 정보만 근거로 제공")
        # 중도인출·해지 질의는 아래 중도인출 분기가 담당한다. "세율" 한 단어에
        # 수령 시 연금소득세 표가 끼어들면 엉뚱한 근거가 된다 (300문 QA 세제 #58).
        if (re.search(r"연금소득세|받을 때.*세[금율]|수령.*세[금율]|세율", question)
                and not re.search(r"중도\s*(인출|해지)", question)):
            _, calc_trace, basis = calculator.pension_income_tax(
                calculator.extract_age(question))
            trace.append(f"[계산] 연금소득세({basis} 근거): {calc_trace}")
            calc_notes.append(calc_trace + f" (근거: {basis})")
        if re.search(r"퇴직(금|소득세).*(연금.*받|수령|감면)|감면.*퇴직", question):
            _, calc_trace, basis = calculator.retirement_tax_discount()
            trace.append(f"[계산] 퇴직소득세 감면({basis} 근거): {calc_trace}")
            calc_notes.append(calc_trace + f" (근거: {basis})")
        if "연금수령한도" in question:
            amounts = calculator.extract_amounts(question)
            year = re.search(r"(\d+)\s*년차", question)
            if amounts:
                _, calc_trace, basis = calculator.pension_withdrawal_limit(
                    amounts[0], int(year.group(1)) if year else 1)
                trace.append(f"[계산] 연금수령한도({basis} 근거): {calc_trace}")
                calc_notes.append(calc_trace + f" (근거: {basis})")
        # "IRP 깨는 세금"처럼 구어(깨다·헐다)로 물으면 계산기가 빠져 HCX가
        # 15.4% 같은 근거 없는 세율을 지어냈다 (승빈 QA #251) — 구어도 트리거한다.
        # 세금 쪽 표현도 구어가 많다: "몇 프로 떼나요"(#57 — 계산기가 빠지자
        # 개인회생을 부득이한 사유가 아니라고 반대로 판정), "손에 쥐는 돈이
        # 얼마죠"(#62 — 500만 해지에 825만 수령이라는 산술 붕괴).
        if re.search(r"중도(인출|해지).*(세금|세율|소득세)|세금.*중도(인출|해지)"
                     r"|(IRP|연금\s*저축|연금\s*계좌|퇴직\s*연금).{0,8}(깨|헐|해지)"
                     r".{0,14}(세금|세율|소득세|프로|퍼센트|얼마|떼|쥐는 돈)",
                     question):
            amounts = calculator.extract_amounts(question)
            # 금액이 없으면 세율만 안내한다 (amount=None 경로)
            result, calc_trace, basis = calculator.early_withdrawal_tax(
                amounts[0] if amounts else None, question,
                calculator.extract_age(question))
            trace.append(f"[계산] 중도인출 세금({basis} 근거): {calc_trace}")
            calc_notes.append(calc_trace + f" (근거: {basis})")
            correction = calculator.withdrawal_premise_correction(question, result)
            if correction:
                trace.append(f"[전제교정] {correction}")
                calc_notes.append(correction + f" (근거: {basis})")
        if "종합과세" in question:
            # 비교 계산은 16.5%와 종합세율이 함께 제시된 질의에서만.
            # 전제교정은 "무조건 종합과세죠?"처럼 16.5% 언급이 없어도 돌아야 한다.
            if "16.5%" in question:
                amounts = calculator.extract_amounts(question)
                rates = calculator.extract_percentages(question)
                comprehensive_rates = [rate for rate in rates if rate != 0.165]
                if amounts and comprehensive_rates:
                    _, calc_trace, basis = calculator.private_pension_tax_comparison(
                        amounts[0], comprehensive_rates[0])
                    trace.append(f"[계산] 종합과세 비교({basis} 근거): {calc_trace}")
                    calc_notes.append(calc_trace + f" (근거: {basis})")
            correction = calculator.pension_tax_premise_correction(question)
            if correction:
                trace.append(f"[전제교정] {correction}")
                calc_notes.append(correction + " (근거: doc38)")
        # "추가 공제가 얼마죠"처럼 '세액공제' 풀네임 없이 물으면 계산기가 빠져
        # 2,000만원 케이스에 한도값 300만원을 답했다 (300문 재실행 #81) —
        # 공제·혜택·옮기 표현까지 트리거를 넓힌다.
        if "ISA" in question and re.search(r"전환|이전|옮기", question) \
                and re.search(r"공제|혜택", question):
            amounts = calculator.extract_amounts(question)
            if amounts:
                result, calc_trace, basis = calculator.isa_transfer_credit(amounts[0])
                trace.append(f"[계산] ISA 전환 혜택({basis} 근거): {calc_trace}")
                calc_notes.append(calc_trace + f" (근거: {basis})")
                correction = calculator.isa_transfer_premise_correction(
                    question, result["additional_eligible"])
                if correction:
                    trace.append(f"[전제교정] {correction}")
                    calc_notes.append(correction + f" (근거: {basis})")

    llm_name = generator.get_llm().name
    answer_text = generator.generate_answer(question, context_blocks, calc_notes)
    trace.append(f"[생성] LLM={llm_name}, 근거블록 {len(context_blocks)}개")

    # 검증: 답변 수치가 근거 밖에서 오지 않았는지 대조 (환각 방어 1차)
    answer_text, verify_trace = verifier.apply(
        answer_text, context_blocks, calc_notes, llm_name, skip_claims=has_table,
        question=question,
        regenerate=lambda unsup: generator.regenerate_answer(
            question, context_blocks, calc_notes, unsup))
    trace.append(verify_trace)

    # 가정 명시: 빈 슬롯이 1개뿐이면 역질문 대신 가정을 밝히고 답한다.
    # 검증 뒤에 붙인다 — verifier는 LLM 생성물만 대조하면 된다.
    if r.assumptions:
        answer_text = generator.assumption_disclosure(r) + "\n\n" + answer_text

    # 출처 표기: LLM 준수 여부와 무관하게 코드가 보장한다 (모든 답변 필수 규정)
    sources = _collect_sources(doc_hits, hits, calc_notes)
    if sources:
        answer_text += "\n\n근거: " + " / ".join(sources)


    return _respond(question_id, question,
                    "\n\n---\n\n".join(context_blocks), trace, answer_text)


def _select_route(question: str):
    """환경변수로 라우터를 전환하고 HCX 장애 시 규칙 라우터로 폴백한다."""
    mode = os.environ.get("ROUTER_MODE", "rule").strip().lower()
    if mode != "hcx":
        return route(question), "모드=rule"

    llm = generator.get_llm()
    if llm.name == "mock":
        return route(question), "모드=hcx → rule 폴백(API 키 없음)"

    try:
        raw = llm.generate(build_hcx_router_prompt(question), max_tokens=256)
        result = route_from_hcx(raw, question)
    except Exception:
        return route(question), "모드=hcx → rule 폴백(HCX 호출 실패)"
    if result.source != "hcx":
        return result, "모드=hcx → rule 폴백(JSON 검증 실패)"
    return result, "모드=hcx"


def _collect_sources(doc_hits, fund_hits, calc_notes) -> list[str]:
    """답변 꼬리에 붙일 근거 표기. 문서는 제목·위치까지, 펀드는 설명서 페이지까지."""
    out, seen = [], set()
    for h in doc_hits or []:
        if h["doc_id"] in seen:
            continue
        seen.add(h["doc_id"])
        out.append(f"{h['doc_id']}({h['title']}) {h['marker']}")
    for f in fund_hits or []:
        src = f.get("source", {})
        out.append(f"{src.get('file')} p{src.get('summary_page')}")
    # 계산 근거 doc는 calc_notes 문자열 끝의 "(근거: docN)" 표기에서 수집
    for note in calc_notes:
        m = re.search(r"\(근거:\s*([^)]+)\)", note)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(f"{m.group(1)}(계산 근거)")
    return out[:8]


def _respond(qid: str, q: str, ctx: str, trace: list[str], ans: str) -> dict:
    return {
        "question_id": qid,
        "question": q,
        "retrieved_context": ctx,
        "think_trace": "\n".join(trace),
        "answer": ans,
    }
