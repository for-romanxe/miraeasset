# 작업 규칙 (AI 코딩 도구 공통)

이 레포는 미래에셋증권 AI Festival "연금 Agent" 과제 팀 작업장이다.
전체 그림은 README.md, 역할별 할 일은 docs/TASKS.md 참고.

## 반드시 지킬 것

1. **main에 직접 커밋·푸시하지 않는다.** 브랜치를 만들어 작업하고 PR로 올린다.
2. **작업 후 `.venv/bin/python eval/run_eval.py`를 실행**해 점수가 떨어지지
   않았는지 확인한다. 현재 기준 105/105. 떨어졌으면 원인을 고치고 나서 PR.
3. 새 기능을 만들면 `eval/build_evalset.py`에 검증 문항을 같이 추가한다
   (추가 후 `eval/build_evalset.py` 실행해서 evalset.jsonl 재생성).
4. 연금 제도·세제의 수치와 규칙은 **반드시 `parser/out/docs/` 원문에서 확인**하고
   쓴다. 모델의 기억이나 웹 검색으로 채우지 않는다 — 대회 규정상 답변 근거는
   제공 자료여야 한다.
5. API 응답 스키마(question_id, question, retrieved_context, think_trace, answer)는
   대회 평가 명세라 변경 금지.
6. 서비스 런타임에 HyperCLOVA X 외의 LLM API를 연동하지 않는다 (대회 규정,
   위반 시 평가 제외). 개발 도구로 다른 AI를 쓰는 것은 무관하다.

## 자주 쓰는 명령

```bash
.venv/bin/python eval/run_eval.py        # 자동 채점 (-v: 실패 상세)
.venv/bin/python eval/build_evalset.py   # 평가셋 재생성
.venv/bin/uvicorn agent.server:app --port 8000   # API 서버 실행
```

## 구조 한눈에

- `agent/` — API 서버와 파이프라인 (router → retriever → calculator → generator)
- `eval/` — 평가셋과 자동 채점 하네스
- `parser/` — 원본 데이터를 정형화한 파이프라인과 산출물 (`parser/out/`)
- `docs/` — 팀 문서 (설계·분담·도메인 개념)
