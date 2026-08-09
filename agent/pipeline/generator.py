"""답변 생성 v0 — 근거 기반 프롬프트 구성 + 가드레일.

역질문 분기(라우터 판정)는 LLM을 거치지 않고 여기서 바로 답을 만든다.
LLM 프롬프트는 근거 밖 내용 생성 금지·근거 표시를 강제한다.
"""
from __future__ import annotations

from ..llm import get_llm
from .router import SLOT_ASSUMPTIONS, SLOT_QUESTIONS, Route

SYSTEM_RULES = """당신은 미래에셋증권 연금 상담 Agent입니다. 규칙:
1. 아래 [근거]에 있는 내용만으로 답하십시오. 근거에 없는 수치·사실을 만들지 마십시오.
2. 근거로 답할 수 없으면 "제공된 자료로는 확인할 수 없습니다"라고 밝히십시오.
3. 답변 끝에 사용한 근거 문서를 표시하십시오.
4. 특정 상품을 단정적으로 추천하지 마십시오. 조건별 결론만 제시하십시오.
5. 질문의 전제가 근거와 다르면 먼저 바로잡으십시오."""


def clarification_answer(route: Route) -> str:
    qs = [SLOT_QUESTIONS[s] for s in route.missing_slots]
    lines = "\n".join(f"- {q}" for q in qs)
    return ("정확한 안내를 위해 몇 가지만 먼저 확인하겠습니다.\n"
            f"{lines}\n"
            "알려주시면 조건에 맞는 상품 유형과 확인 포인트를 안내해 드리겠습니다. "
            "특정 상품의 단정적 추천은 드리지 않으며, 투자 판단은 투자설명서를 확인하신 뒤 "
            "본인 책임 하에 이루어져야 합니다.")


def assumption_disclosure(route: Route) -> str:
    return " ".join(SLOT_ASSUMPTIONS[slot][1] for slot in route.assumptions)


def limitation_answer() -> str:
    return ("죄송하지만 해당 내용은 제공된 자료의 범위를 벗어나 정확히 확인해 드릴 수 없습니다. "
            "저는 사적연금(퇴직연금 DB·DC·IRP, 연금저축)의 제도·세제 안내와 "
            "취급 상품의 투자설명서 기반 설명을 도와드릴 수 있습니다. "
            "국민연금 등 공적연금은 국민연금공단(1355), 실시간 시세·개인 계좌 정보는 "
            "홈페이지/모바일 앱 또는 고객센터를 이용해 주세요.")


def guard_answer() -> str:
    return ("요청하신 내용은 처리해 드릴 수 없습니다. "
            "개인정보(주민등록번호·계좌번호 등)는 이 상담 채널에 입력하지 말아 주세요. "
            "또한 특정 상품의 단정적 추천이나 안내 원칙을 벗어난 요청에는 응할 수 없습니다. "
            "연금 제도·세제·상품에 대한 질문이라면 근거 자료를 바탕으로 성실히 안내해 드리겠습니다.")


def build_prompt(question: str, context_blocks: list[str], calc_notes: list[str]) -> str:
    ctx = "\n\n---\n\n".join(context_blocks) if context_blocks else "(검색된 근거 없음)"
    calc = ("\n\n[계산 결과 — 이 수치를 그대로 사용할 것]\n" + "\n".join(calc_notes)) if calc_notes else ""
    return (f"{SYSTEM_RULES}\n\n[근거]\n{ctx}{calc}\n\n[질문]\n{question}\n\n"
            "[답변] 근거에 기반해 한국어로 답하십시오.")


def generate_answer(question: str, context_blocks: list[str], calc_notes: list[str]) -> str:
    llm = get_llm()
    return llm.generate(build_prompt(question, context_blocks, calc_notes))
