"""평가용 API 서버 — 과제 명세의 GET /answer 스키마를 그대로 구현한다.

실행:
  uvicorn agent.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI, Query

from . import pipeline

app = FastAPI(title="연금 Agent", version="0.1.0")


@app.get("/answer")
def answer(question_id: str = Query(...), question: str = Query(...)) -> dict:
    return pipeline.answer(question_id, question)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
