"""API 키 없이 실행하는 라우터 프롬프트·파서 회귀 테스트."""
import json
import unittest

from agent.pipeline.router import build_hcx_router_prompt, route, route_from_hcx


class RouterTest(unittest.TestCase):
    def test_assume_expose_for_one_missing_slot(self):
        result = route("장기로 안정적인 펀드 하나 추천해 주세요.")
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.assumptions, {"account": "IRP"})

    def test_recommendation_without_the_word_recommend(self):
        """'추천'이라는 단어 없이 묻는 추천 요구도 잡아야 한다 (#23)."""
        for q in ["IRP에 뭐 담는 게 나을까요?",
                  "IRP에서 어떤 상품이 좋을까요?",
                  "연금저축에 무슨 펀드가 괜찮을까요?"]:
            self.assertTrue(route(q).is_recommendation, q)

    def test_explanation_is_not_treated_as_recommendation(self):
        """설명 요구를 추천으로 오인하면 불필요한 역질문이 나간다 (#23)."""
        for q in ["IRP가 뭐가 좋은 점이 있나요?",
                  "연금저축 계좌에서 ETF를 실시간으로 거래할 수 있나요?",
                  "디폴트옵션이 뭔가요?",
                  "퇴직금 담보대출이 되나요?"]:
            self.assertFalse(route(q).is_recommendation, q)

    def test_principal_preservation_fills_risk_slot(self):
        """'원금 보전'은 위험 성향 표현이다 (#24)."""
        for q in ["원금 보전되는 상품 추천해 주세요.",
                  "손해 안 보는 펀드 추천해 주세요."]:
            self.assertNotIn("risk", route(q).missing_slots, q)

    def test_hcx_mock_response_is_parsed(self):
        question = "70세인데 IRP에서 연금 2,000만원을 받으면 세금이 어떻게 되나요?"
        raw = json.dumps({
            "categories": ["세제", "제도"], "age": 70,
            "amounts": [{"value_won": 20_000_000, "purpose": "연금 수령액"}],
            "account_types": ["IRP"], "is_recommendation": False,
            "out_of_scope": False, "unsafe": False,
        })
        self.assertEqual(route_from_hcx(raw, question).categories, ["세제", "제도"])
        self.assertIn(question, build_hcx_router_prompt(question))

    def test_invalid_hcx_response_falls_back(self):
        result = route_from_hcx("not-json", "IRP 세액공제는 얼마인가요?")
        self.assertIn("세제", result.categories)


if __name__ == "__main__":
    unittest.main()
