"""API 키 없이 실행하는 generator 프롬프트 가드 테스트 (#62).

HCX의 행동 자체는 결정적으로 시험할 수 없으므로, 실측으로 효과를 확인한
프롬프트 규칙이 실수로 지워지지 않는 것을 지킨다.
"""
import unittest

from agent.pipeline import generator, verifier


class PromptRuleGuardTest(unittest.TestCase):
    def test_conditional_answer_rule_present(self):
        """규칙 8 (#62): 예/아니오 질문의 단답 일반화 금지.

        do-42p 실측 — 규칙 추가 전 단답 시작 4/4, 추가 후 조건부 6/6."""
        self.assertIn("예/아니오", generator.SYSTEM_RULES)
        self.assertIn("단정으로 시작하지", generator.SYSTEM_RULES)
        prompt = generator.build_prompt("펀드 청산금도 만기로 보나요?", ["근거"], [])
        self.assertIn("예/아니오", prompt)

    def test_notation_equivalence_rule_present(self):
        """검증2 표기 동치 (#62): "200만 원"과 "2,000,000원"을 다른 수치로
        보고 미지지 오탐을 내던 문제 — tax-17 실측 미지지 4건 → 0건."""
        self.assertIn("표기 방식이 달라도", verifier.CLAIM_VERIFY_PROMPT)


if __name__ == "__main__":
    unittest.main()
