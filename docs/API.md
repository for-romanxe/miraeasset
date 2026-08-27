# 연금 Agent API 명세서

제출용 평가 API. 과제 명세의 단일 엔드포인트 `GET /answer`를 그대로 구현한다.
평가는 싱글턴(질의 1건 → 완성된 답변 1건)이며 스트리밍 없이 전체를 하나의
JSON으로 반환한다 (8/6 설명회 Q&A 확인 사항).

## 기본 정보

| 항목 | 값 |
|---|---|
| Base URL | `http://<NCP 서버 IP 또는 도메인>` (배포 시 확정) |
| 프로토콜 | HTTP (HTTPS는 NCP Global DNS + Certificate Manager 구성 시) |
| 포트 | 80 (컨테이너 내부 8000 → 호스트 80 매핑) |
| 인증 | 없음 (평가 명세 기준) |
| 문자 인코딩 | UTF-8. 질문은 반드시 URL 인코딩해서 전달 |

라우터는 기본적으로 규칙 기반이며, `ROUTER_MODE=hcx`를 설정하면 HyperCLOVA X
분류를 사용한다. API 키 부재, 호출 실패, JSON 스키마 오류 때는 규칙 라우터로
자동 폴백하고 `think_trace`의 `[라우팅]` 항목에 이유를 남긴다.

## GET /answer

### 요청 파라미터 (query string)

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `question_id` | string | ✅ | 평가 측이 부여하는 질문 식별자. 응답에 그대로 반환 |
| `question` | string | ✅ | 자연어 질문 (한국어) |

```bash
curl -G "http://<서버주소>/answer" \
  --data-urlencode "question_id=Q-001" \
  --data-urlencode "question=연금저축이랑 IRP 합쳐서 세액공제 얼마까지 받을 수 있나요?"
```

Python에서는 `requests`로 같은 요청을 보낼 수 있다.

```python
import requests

response = requests.get(
    "http://<서버주소>/answer",
    params={
        "question_id": "Q-001",
        "question": "연금저축이랑 IRP 합쳐서 세액공제 얼마까지 받을 수 있나요?",
    },
    timeout=30,
)
response.raise_for_status()
print(response.json())
```

### 응답 (200, application/json)

과제 명세의 5필드 스키마. 필드 추가·이름 변경 금지 (AGENTS.md 규칙).

| 필드 | 타입 | 설명 |
|---|---|---|
| `question_id` | string | 요청의 question_id 그대로 |
| `question` | string | 요청의 question 그대로 |
| `retrieved_context` | string | 답변 근거로 검색된 문서 청크·펀드 요약. 청크는 `[docN(제목) 위치]` 라벨을 달고 `\n\n---\n\n`로 구분. 근거가 없는 응답(가드·역질문)은 빈 문자열 |
| `think_trace` | string | 파이프라인 처리 과정. `[라우팅]` `[검색]` `[상품조회]` `[계산]` `[생성]` `[검증]` 태그가 줄 단위로 쌓임 |
| `answer` | string | 최종 답변. 마지막 줄에 `근거: ...` 출처 표기가 항상 붙음 (역질문·가드·정보한계 제외) |

### 응답 예시 (실측, 발췌)

```json
{
  "question_id": "Q-001",
  "question": "연금저축이랑 IRP 합쳐서 세액공제 얼마까지 받을 수 있나요?",
  "retrieved_context": "[doc41(연금저축계좌, IRP 세액공제 안내) 본문]\n세액공제 안내\n연금저축과 IRP는 합산해서 연1,800만원까지 입금이 가능하다. ... 연금저축은 연600만원, IRP는 연금저축 납입액을 포함해서 연900만원이다. ...\n\n---\n\n[doc38(연금소득 종합과세 안내) 본문]\n...",
  "think_trace": "[라우팅] 유형=세제 ...\n[검색] doc41 본문(score 24.1), doc38 본문(...) ...\n[생성] LLM=..., 근거블록 5개\n[검증] 답변 수치 N개 모두 근거에서 확인",
  "answer": "연금저축과 IRP를 합산한 세액공제 납입한도는 연 900만원입니다. ...\n\n근거: doc41(연금저축계좌, IRP 세액공제 안내) 본문 / doc38(연금소득 종합과세 안내) 본문"
}
```

### 응답 유형별 동작

| 질의 유형 | retrieved_context | answer |
|---|---|---|
| 일반 (제도·세제·절차·상품) | 문서 청크 + 펀드 요약 | 근거 기반 답변 + 출처 |
| 조건이 빈 추천 질의 | 빈 문자열 | 역질문 (계좌·위험성향·기간 확인) |
| 데이터 범위 밖 (국민연금 수령액 등) | 빈 문자열 | 한계 고지 + 공적 기관 안내 |
| 개인정보·프롬프트 공격 | 빈 문자열 | 정중한 거절 |

### 오류

| 상황 | 응답 |
|---|---|
| `question_id`/`question` 누락 | 422 (FastAPI 검증 오류) |
| 내부 오류 — 같은 문항 1~2회째 | **503** — 주최측 재시도 유도 |
| 내부 오류 — 같은 문항 3회째(마지막 기회) | **200 + 5필드 스키마** — 아래 참고 |

주최측 공지(8/24)에 따르면 타임아웃(300초) 또는 5xx 응답 시 같은 문항을 **최대 2회
재시도**한다. 일시 장애에 곧바로 200+한계 고지를 반환하면 그 문항의 재시도 기회를
스스로 버리는 셈이므로, 첫 2회 실패는 503으로 돌려 재시도를 받는다. 재시도까지 모두
실패하면(3회째) 5필드 폴백을 반환해 빈손으로 끝나지 않는다. 성공하면 실패 카운터를
지워 이후 장애 때 다시 재시도를 받을 수 있다. 실제 예외는 서버 로그에만 남긴다.

```json
{
  "question_id": "Q-001",
  "question": "평가 질의 원문",
  "retrieved_context": "",
  "think_trace": "[오류] 일시적 장애로 답변을 생성하지 못했습니다",
  "answer": "죄송하지만 해당 내용은 제공된 자료의 범위를 벗어나 ..."
}
```

### 응답 시간

LLM 호출에 재시도 예산 상한을 둔다 (기본 90초, `CLOVASTUDIO_BUDGET_SEC`로 조정).
주최측 문항당 타임아웃은 300초지만, 300초를 다 쓰면 타임아웃으로 기록된 뒤에야
재시도를 받는다. 90초 안에 실패를 확정하고 503으로 즉시 재시도를 받는 편이 낫다.
백오프 마지막 단계 30초는 HCX 분당 호출 한도(429)의 창 리셋을 기다리는 값이다.

검색 인덱스는 서버 기동 시 미리 구축하므로 첫 질의가 불리하지 않다.

## GET /health

운영 확인용. `{"status": "ok"}` 반환. 평가 기간(9/7~9/20) 중 모니터링에 사용.

## 배포

```bash
# NCP 서버에서 (docker 설치 후)
git clone <레포 주소> && cd <레포>
CLOVASTUDIO_API_KEY=<키> ./scripts/deploy.sh
```

- 이미지: `python:3.11-slim` 기반, `agent/` + `parser/out/`(정형 데이터 약 1MB)만 포함
- 환경변수: `CLOVASTUDIO_API_KEY`(필수), `CLOVASTUDIO_MODEL`(기본 HCX-005)
- `--restart always`로 재부팅·크래시 자동 복구
