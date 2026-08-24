"""API 키 없이 실행하는 세제 계산기 회귀 테스트."""
import unittest

from agent.pipeline import answer
from agent.pipeline.calculator import split_amounts_by_account, tax_credit


class AccountMappingTest(unittest.TestCase):
    def test_amount_follows_account_name_not_order(self):
        """금액을 언급 순서가 아니라 계좌명 기준으로 배정한다 (#25)."""
        cases = [
            ("연금저축 400만원, IRP 300만원 넣었는데 세액공제 얼마 받아요?", (4_000_000, 3_000_000)),
            ("IRP 200만원이랑 연금저축 700만원 세액공제 얼마나 되나요?", (7_000_000, 2_000_000)),
            ("연금저축 700만원이랑 IRP 200만원 세액공제 얼마나 되나요?", (7_000_000, 2_000_000)),
            ("IRP에 1,800만원 넣으면 다 세액공제 되는 거죠?", (0, 18_000_000)),
        ]
        for question, expected in cases:
            self.assertEqual(split_amounts_by_account(question), expected, question)

    def test_no_account_name_falls_back(self):
        """계좌명이 없으면 None — 호출부가 순서 배정으로 폴백한다."""
        self.assertIsNone(split_amounts_by_account("900만원 세액공제 되나요?"))

    def test_cap_applies_regardless_of_order(self):
        """연금저축 600만원 캡이 언급 순서와 무관하게 적용된다."""
        for question in ["IRP 200만원이랑 연금저축 700만원 세액공제 얼마나 되나요?",
                         "연금저축 700만원이랑 IRP 200만원 세액공제 얼마나 되나요?"]:
            ps, irp = split_amounts_by_account(question)
            result, _, _ = tax_credit(pension_saving=ps, irp=irp)
            self.assertEqual(result["eligible"], 8_000_000, question)


class TriggerTest(unittest.TestCase):
    def test_credit_asked_without_the_term(self):
        """'세액공제'라는 용어 없이 물어도 계산기가 돌아야 한다 (#25)."""
        for question in ["IRP 300만원이랑 연금저축 400만원 넣었는데 다 공제되나요?",
                         "연금저축 500만원 넣으면 얼마나 돌려받나요?"]:
            trace = answer("t", question)["think_trace"]
            self.assertIn("[계산] 세액공제", trace, question)


if __name__ == "__main__":
    unittest.main()
