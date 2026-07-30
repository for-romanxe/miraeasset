# 연금 Agent

제10회 2026 미래에셋증권 AI Festival "연금 Agent" 과제.
주최 측 배포 데이터(투자설명서 PDF 100건 + 안내문서 58건)를 정형 데이터로 변환하고,
이를 근거로 답하는 평가용 API 서버를 만든다.

## 팀 문서

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 파이프라인 설계안·로드맵 (논의용 초안)
- [docs/IDEAS.md](docs/IDEAS.md) — 차별화 아이디어 7선과 우선순위
- [docs/PENSION_BASICS.md](docs/PENSION_BASICS.md) — 연금 도메인 개념 정리

## Agent 뼈대 (agent/)

평가 명세의 `GET /answer` 스키마를 그대로 구현한 walking skeleton.
LLM은 8/6 크레딧 수령 전까지 Mock이며, `CLOVASTUDIO_API_KEY` 환경변수를
설정하면 HyperCLOVA X 호출로 자동 전환된다 (agent/llm.py).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn agent.server:app --host 0.0.0.0 --port 8000
curl -G "http://localhost:8000/answer" \
  --data-urlencode "question_id=Q-001" \
  --data-urlencode "question=연금저축이랑 IRP 세액공제 한도가 얼마인가요?"
```

파이프라인: 라우터(유형·슬롯 판정) → 검색(docs BM25 + funds 정형 조회) →
세제 계산기 → 생성(근거 고정 프롬프트). 조건이 빈 추천 질의는 역질문으로 분기.

## 데이터 파이프라인 (parser/)

## 산출물

| 경로 | 내용 |
|---|---|
| `parser/out/funds.json` | 투자설명서 100건 파싱 결과. 상품 6축(상품분류·위험등급·판매클래스·총보수·수익률·시장잔고) + 근거 페이지 |
| `parser/schema.json` | funds.json 필드 스키마 (JSON Schema) |
| `parser/out/docs/doc1~58.md` | 안내문서 58건 전문 텍스트. 근거 표시용 `[페이지 N]`/`[슬라이드 N]`/`[시트]` 마커 포함 |
| `parser/out/docs.json` | 안내문서 카탈로그 (제목·주제 태그·형식·분량·추출 방법) |
| `parser/out/INDEX.md` | 안내문서 주제별 목차 (제도 18 · 세제 16 · 업무절차 11 · 상품운용 9 · 디폴트옵션 4) |

## 파이프라인

- `parser/parse_prospectus.py` — 투자설명서 PDF → funds.json.
  `pdftotext -layout` 전문 + 요약정보 페이지만 pdfplumber 좌표 파싱.
  운용사별 서식 차이(% 접미사, 코드 선행형 클래스명, 단일 클래스, 병합 셀 수익률 표 등) 대응.
  100건 중 97건 경고 없음 — 나머지 3건은 신규 설정 펀드로 원문 자체에 수익률·결산 재무가 없음
  (`parse_warnings`에 기록, Agent의 한계 고지용).
- `parser/parse_docs.py` — 안내문서(pdf/docx/pptx/xlsx) → 마크다운 + 카탈로그.
  이미지 스캔 PDF 17건은 macOS Vision 프레임워크 한국어 OCR로 추출.

## 재현

```bash
cd parser
python3 -m venv .venv && .venv/bin/pip install pdfplumber openpyxl python-docx \
    pyobjc-framework-Vision pyobjc-framework-Quartz
brew install poppler   # pdftotext, pdftoppm
.venv/bin/python parse_prospectus.py   # ../투자설명서/{ISIN}/R2_{ISIN}.pdf 필요
.venv/bin/python parse_docs.py         # ../docs_renamed/doc*.{pdf,docx,pptx,xlsx} 필요
```

원본 데이터(주최 측 배포 zip)는 저장소에 포함하지 않는다. 로컬 기준 경로:
`~/Downloads/data/2.연금/` (투자설명서/, docs_renamed/). OCR은 macOS 전용(Vision 프레임워크).
