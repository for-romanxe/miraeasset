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
    """CLOVA Studio Chat Completions 호출. 8/6 키 발급 후 활성화.

    필요 환경변수: CLOVASTUDIO_API_KEY, (선택) CLOVASTUDIO_MODEL
    """

    name = "hyperclova-x"
    ENDPOINT = "https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/{model}"

    def __init__(self):
        self.api_key = os.environ["CLOVASTUDIO_API_KEY"]
        self.model = os.environ.get("CLOVASTUDIO_MODEL", "HCX-005")

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        import requests

        r = requests.post(
            self.ENDPOINT.format(model=self.model),
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "messages": [{"role": "user", "content": prompt}],
                "maxTokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["result"]["message"]["content"]


def get_llm():
    if os.environ.get("CLOVASTUDIO_API_KEY"):
        return HyperClovaX()
    return MockLLM()
