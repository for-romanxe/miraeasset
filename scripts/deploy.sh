#!/usr/bin/env bash
# NCP 평가 서버 배포 — 서버에 클론한 레포 루트에서 실행한다.
#   CLOVASTUDIO_API_KEY=... ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${CLOVASTUDIO_API_KEY:-}" ]; then
  echo "CLOVASTUDIO_API_KEY 환경변수를 먼저 설정하세요" >&2
  exit 1
fi

docker build -t pension-agent .
docker rm -f pension-agent 2>/dev/null || true
# --restart always: 평가 기간(9/7~9/20) 중 재부팅·프로세스 사망에도 자동 복구
docker run -d --name pension-agent --restart always \
  -p 80:8000 \
  -e CLOVASTUDIO_API_KEY \
  -e CLOVASTUDIO_MODEL="${CLOVASTUDIO_MODEL:-HCX-005}" \
  pension-agent

sleep 3
curl -fsS "http://localhost/health" >/dev/null && echo "헬스체크 OK — http://<서버IP>/answer 준비됨"
