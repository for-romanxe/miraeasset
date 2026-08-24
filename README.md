# 연금 Agent

제10회 2026 미래에셋증권 AI Festival "연금 Agent" 과제.
주최 측 배포 데이터(투자설명서 PDF 100건 + 안내문서 58건)를 정형 데이터로 변환하고,
이를 근거로 답하는 평가용 API 서버를 만든다.

## 작업 규칙 (PR 워크플로)

main에 직접 푸시하지 않는다 (플랜 제약으로 강제 장치가 없으니 서로 약속).

1. 브랜치를 만들어 작업: `git checkout -b feat/작업이름`
2. 푸시 후 PR 생성: `gh pr create` (템플릿의 체크리스트 작성)
3. 머지 전에 `python eval/run_eval.py` 점수가 떨어지지 않았는지 확인
4. 팀원 1명 확인 후 머지 (급한 오타 수정 등은 셀프 머지 허용)

## 팀 문서

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 파이프라인 설계안·로드맵 (논의용 초안)
- [docs/IDEAS.md](docs/IDEAS.md) — 차별화 아이디어 7선과 우선순위
- [docs/PENSION_BASICS.md](docs/PENSION_BASICS.md) — 연금 도메인 개념 정리

## Agent 뼈대 (agent/)

평가 명세의 `GET /answer` 스키마를 그대로 구현한 walking skeleton.
LLM은 **HyperCLOVA X(HCX-005)** 를 쓴다. `CLOVASTUDIO_API_KEY` 환경변수가
있으면 HCX를, 없으면 MockLLM을 자동 선택한다 (agent/llm.py). 키 없이도
검색·라우팅·계산기 경로를 그대로 돌려볼 수 있다.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn agent.server:app --host 0.0.0.0 --port 8000
curl -G "http://localhost:8000/answer" \
  --data-urlencode "question_id=Q-001" \
  --data-urlencode "question=연금저축이랑 IRP 세액공제 한도가 얼마인가요?"
```

파이프라인: 라우터(유형·슬롯 판정) → 검색(docs BM25 + funds 정형 조회) →
세제 계산기 → 생성(근거 고정 프롬프트) → 검증(수치 대조) → 출처 표기.
조건이 빈 추천 질의는 역질문으로 분기.

API 스키마·응답 유형별 동작은 [docs/API.md](docs/API.md) 참고.

### 배포 (NCP 평가 서버)

```bash
CLOVASTUDIO_API_KEY=<키> ./scripts/deploy.sh   # docker build + 80포트 기동 + 헬스체크
```

### 평가·측정 도구 (eval/)

| 스크립트 | 용도 |
|---|---|
| `run_eval.py` | 결정적 회귀 채점 (문서 인용·수치·분기) — PR 전 필수 |
| `llm_judge.py` | 답변 문장 품질 LLM 채점 (4축 루브릭, 키 없으면 드라이런) |
| `perf.py` | 콜드스타트·문항당 지연 측정 (LLM 제외) |
| `load_test.py` | 실행 중인 API에 전체 평가셋을 순차·동시 요청해 상태코드·스키마·지연 추세 측정 |

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
