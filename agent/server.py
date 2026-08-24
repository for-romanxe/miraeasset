"""평가용 API 서버 — 과제 명세의 GET /answer 스키마를 그대로 구현한다.

실행:
  uvicorn agent.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import pipeline
from .pipeline import generator

log = logging.getLogger("pension-agent")

app = FastAPI(title="연금 Agent", version="1.0.0")


class AnswerResponse(BaseModel):
    """평가 명세가 요구하는 5필드. 추가·개명 금지 규정을 코드로 고정한다."""

    question_id: str
    question: str
    retrieved_context: str
    think_trace: str
    answer: str


# 주최측 공지(8/24): 타임아웃(300초) 또는 5xx 응답이면 같은 문항을 최대 2회
# 재시도한다. 일시 장애에 곧바로 200+한계 고지를 주면 그 문항의 재시도 기회를
# 스스로 버리는 셈이다. 같은 question_id의 첫 2회 실패는 503으로 돌려 재시도를
# 받고, 마지막 기회(3회째)에만 5필드 폴백을 반환해 빈손으로 끝나지 않게 한다.
EVALUATOR_RETRIES = 2
_fail_counts: dict[str, int] = {}


@app.get("/answer", response_model=AnswerResponse)
def answer(question_id: str = Query(...), question: str = Query(...)) -> dict:
    try:
        result = pipeline.answer(question_id, question)
    except Exception:
        fails = _fail_counts.get(question_id, 0) + 1
        _fail_counts[question_id] = fails
        log.exception("answer failed (%d회째): question_id=%s", fails, question_id)
        if fails <= EVALUATOR_RETRIES:
            raise HTTPException(status_code=503, detail="일시적 장애, 재시도 요청")
        return {
            "question_id": question_id,
            "question": question,
            "retrieved_context": "",
            "think_trace": "[오류] 일시적 장애로 답변을 생성하지 못했습니다",
            "answer": generator.limitation_answer(),
        }
    _fail_counts.pop(question_id, None)
    return result


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
def warm_up() -> None:
    """검색 인덱스를 미리 구축한다.

    지연 로딩이면 평가 첫 질의가 인덱스 구축 시간을 혼자 부담한다.
    기동 시 끝내두면 모든 질의가 같은 조건에서 응답한다.
    """
    from .pipeline.retriever import get_docs_index, get_funds_index

    get_docs_index()
    get_funds_index()
    log.info("index warm-up done")
