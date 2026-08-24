"""평가용 API 서버 — 과제 명세의 GET /answer 스키마를 그대로 구현한다.

실행:
  uvicorn agent.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Query
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


@app.get("/answer", response_model=AnswerResponse)
def answer(question_id: str = Query(...), question: str = Query(...)) -> dict:
    # 평가 기간(9/7~9/20) 중 어떤 예외가 나도 500을 돌려주지 않는다.
    # 500은 답변 품질 문제가 아니라 응답 스키마 위반이다. 답을 못 하더라도
    # 5필드를 지켜 한계를 고지한다.
    try:
        return pipeline.answer(question_id, question)
    except Exception:
        log.exception("answer failed: question_id=%s", question_id)
        return {
            "question_id": question_id,
            "question": question,
            "retrieved_context": "",
            "think_trace": "[오류] 일시적 장애로 답변을 생성하지 못했습니다",
            "answer": generator.limitation_answer(),
        }


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
