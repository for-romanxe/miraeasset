# 평가 기간 운영 매뉴얼 (9/7 10:00 ~ 9/11 15:00)

평가 답변 수집은 **9/7(월) 10:00 ~ 9/11(금) 15:00** 사이에 순차 진행된다 (9/4 공지 — 기존 9/20에서 단축).
엔드포인트는 구글 폼으로 제출 완료(9/5), 평가 호출은 그 주소(211.188.62.72)로 온다.
이 기간 서버는 끊김 없이 응답해야 한다. 이 문서 하나로 상태 확인 → 장애 대응 →
재배포까지 처리할 수 있게 정리했다. 서버 접속 키는 연성 로컬(`~/.ssh/pen017_deploy_key`)에 있다.

## 서버 정보

| 항목 | 값 |
|---|---|
| 서버 | NCP `pen017api` (s2-g3a, ubuntu-24.04, KR-1, 시간요금제 115원/h) |
| 공인 IP | 211.188.62.72 (HTTP 80) |
| 코드 위치 | 서버 `/root/pension-agent` |
| 컨테이너 | `pension-agent` — `--restart always` (재부팅·프로세스 사망 시 자동 복구) |
| 접속 | `ssh -i ~/.ssh/pen017_deploy_key root@211.188.62.72` (연성만 가능) |

## 일일 점검 (당번, 1분이면 끝)

누구나 자기 컴퓨터에서 실행 — SSH 불필요:

```bash
curl -m 10 http://211.188.62.72/health
# {"status":"ok"} 이외의 응답이거나 무응답이면 아래 장애 대응으로
```

하루 2회(오전/오후) 권장. 9/7부터는 주최측 수집 서버와의 공개망 통신도 서버 안에서 자가 점검할 수 있다
(평가와 무관·자율): `ssh(배포키) → curl -s http://34.47.115.128/health` 이상 발견 시 팀 채팅에 알리고, SSH가 필요한 조치는 연성에게.

### 당번표 (팀 논의로 채우기)

| 기간 | 당번 |
|---|---|
| 9/7(월)~9/8(화) | (미정) |
| 9/9(수)~9/11(금) 15:00 | (미정) |

## 장애 대응 (연성 — SSH 필요)

증상별 순서대로:

```bash
# 1. 컨테이너 상태·최근 로그
ssh -i ~/.ssh/pen017_deploy_key root@211.188.62.72 \
  "docker ps -a --filter name=pension-agent && docker logs --tail 100 pension-agent"

# 2. 컨테이너만 재시작 (대부분 여기서 해결)
ssh -i ~/.ssh/pen017_deploy_key root@211.188.62.72 "docker restart pension-agent"

# 3. 그래도 안 되면 서버 재부팅 (--restart always라 컨테이너 자동 기동)
ssh -i ~/.ssh/pen017_deploy_key root@211.188.62.72 "reboot"
```

- `docker logs`에서 HCX 401/403 → 키 문제 (아래 키 로테이션 절차로 재기동)
- 서버 자체가 SSH도 안 되면 → NCP 콘솔에서 서버 상태 확인 후 재시작
- 헬스체크는 살아 있는데 `/answer`가 5xx → 로그 확인 후 컨테이너 재시작. 평가 명세상
  5xx는 채점기가 2회 재시도하므로 몇 분 내 복구하면 영향 최소

## 재배포 (코드 수정 반영 — 9/6 마감 후엔 금지)

로컬 main 최신 기준:

```bash
git archive --format=tar.gz -o /tmp/pension-agent.tar.gz HEAD
scp -i ~/.ssh/pen017_deploy_key /tmp/pension-agent.tar.gz root@211.188.62.72:/root/
ssh -i ~/.ssh/pen017_deploy_key root@211.188.62.72 \
  "rm -rf /root/pension-agent && mkdir /root/pension-agent \
   && tar -xzf /root/pension-agent.tar.gz -C /root/pension-agent \
   && cd /root/pension-agent && CLOVASTUDIO_API_KEY=<키> ./scripts/deploy.sh"
curl -m 10 http://211.188.62.72/health   # 외부 확인까지 해야 완료
```

**⚠️ 제출 기한 9/6(일) 23:59 (9/4 공지). 이후 커밋·푸시·재배포는 엄격 금지 — 제출 코드 검증 작업이 있을 수 있음.** 마감 후 장애는
재시작·재부팅(코드 불변)으로만 대응한다.

## HCX 키 로테이션 (9/7 전 필수 1회)

현재 키가 채팅에 노출된 적 있어 평가 시작 전 교체한다:

1. CLOVA Studio 콘솔에서 새 키 발급 → 기존 키 폐기
2. 세 명 모두 로컬 `.env`의 `CLOVASTUDIO_API_KEY` 교체
3. 서버 컨테이너 새 키로 재기동:
   ```bash
   ssh -i ~/.ssh/pen017_deploy_key root@211.188.62.72 \
     "cd /root/pension-agent && CLOVASTUDIO_API_KEY=<새키> ./scripts/deploy.sh"
   ```
4. `curl "http://211.188.62.72/answer?question_id=t&question=IRP가 뭔가요?"` 로 실답변 확인

## 평가 종료 후 (9/20 이후)

- 평가 종료(9/11 15:00) 뒤에는 서버를 내려도 된다. 9/30 전에 NCP 리소스 삭제: 서버 반납 → 공인 IP 반납 (서버 반납 시 체크박스)
- 크레딧이 소멸성이므로 서버는 9/11까지 계속 켜둬도 비용 부담 없음 (~4만원/2주)
