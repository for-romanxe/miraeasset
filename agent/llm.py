"""LLM 호출 인터페이스.

규칙상 서비스 LLM은 HyperCLOVA X만 허용된다. 8/6 크레딧 수령 전까지는
MockLLM으로 파이프라인을 관통시키고, 이후 HyperClovaX로 교체한다.
교체 지점은 get_llm() 하나다.
"""
from __future__ import annotations

import os


class MockLLM:
    """크레딧 수령 전 개발용. 프롬프트를 실행하지 않고 표식만 돌려준다."""

    name = "mock"

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        return ("[MOCK LLM] HyperCLOVA X 연동 전입니다. "
                "아래 근거로 답변이 생성될 예정입니다.\n\n" + prompt[-1200:])


class HyperClovaX:
    """CLOVA Studio Chat Completions v3 호출. 키 발급 후 활성화.

    엔드포인트·요청 형식은 서비스소개 자료 25쪽 '코드 보기' 스니펫 기준
    (v3, content가 typed part 배열). 필요 환경변수: CLOVASTUDIO_API_KEY,
    (선택) CLOVASTUDIO_MODEL — 기본 HCX-005.
    """

    name = "hyperclova-x"
    ENDPOINT = "https://clovastudio.stream.ntruss.com/v3/chat-completions/{model}"

    def __init__(self):
        self.api_key = os.environ["CLOVASTUDIO_API_KEY"]
        self.model = os.environ.get("CLOVASTUDIO_MODEL", "HCX-005")

    # 평가 기간(9/7~9/20) 중 간헐적 연결 끊김·5xx로 답변 하나가 통째로
    # 실패하지 않도록 재시도한다. 지수 백오프, 마지막 시도는 그대로 예외를 올린다.
    RETRIES = 3
    BACKOFF = (0.5, 1.5, 3.0)

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        import time
        import uuid

        import requests

        for attempt in range(self.RETRIES):
            try:
                r = requests.post(
                    self.ENDPOINT.format(model=self.model),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
                        "Content-Type": "application/json",
                    },
                    json={
                        "messages": [{
                            "role": "user",
                            "content": [{"type": "text", "text": prompt}],
                        }],
                        "maxTokens": max_tokens,
                        "temperature": 0.1,
                        "topP": 0.8,
                    },
                    timeout=60,
                )
                # 4xx는 요청 자체가 틀린 것이므로 재시도해도 같다 (429는 예외)
                if r.status_code < 500 and r.status_code != 429:
                    break
                r.raise_for_status()
            except requests.exceptions.RequestException:
                # 마지막 시도면 그대로 올려서 호출부가 알게 한다
                if attempt == self.RETRIES - 1:
                    raise
                time.sleep(self.BACKOFF[attempt])

        r.raise_for_status()
        content = r.json()["result"]["message"]["content"]
        # v3는 content가 typed part 배열로 올 수 있다
        if isinstance(content, list):
            return "".join(p.get("text", "") for p in content)
        return content


def get_llm():
    if os.environ.get("CLOVASTUDIO_API_KEY"):
        return HyperClovaX()
    return MockLLM()
