"""API 키 없이 실행하는 라우터 프롬프트·파서 회귀 테스트."""
import json
import unittest

from agent.pipeline.router import build_hcx_router_prompt, route, route_from_hcx


class RouterTest(unittest.TestCase):
    def test_assume_expose_for_one_missing_slot(self):
        result = route("장기로 안정적인 펀드 하나 추천해 주세요.")
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.assumptions, {"account": "IRP"})

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
