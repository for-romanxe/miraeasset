"""API 키 없이 실행하는 세제 계산기 회귀 테스트."""
import unittest

from agent.pipeline import answer
from agent.pipeline.calculator import (
    early_withdrawal_tax,
    isa_transfer_premise_correction,
    pension_tax_premise_correction,
    split_amounts_by_account,
    tax_credit,
    withdrawal_premise_correction,
)


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


class PremiseCorrectionTest(unittest.TestCase):
    def test_private_pension_tax_applies_to_full_amount(self):
        question = "사적연금 1,500만원 초과분에만 16.5% 분리과세하는 거죠?"
        self.assertIn("전체 금액", pension_tax_premise_correction(question))

    def test_isa_transfer_credit_is_ten_percent_with_cap(self):
        correction = isa_transfer_premise_correction(
            "ISA 만기자금 5,000만원을 옮기면 전액 세액공제되나요?", 3_000_000)
        self.assertIn("최대 3,000,000원", correction)

    def test_unavoidable_withdrawal_is_not_always_16_5_percent(self):
        result, _, _ = early_withdrawal_tax(10_000_000, "개인회생", age=72)
        correction = withdrawal_premise_correction(
            "개인회생이어도 중도인출은 무조건 16.5% 세금이죠?", result)
        self.assertIn("4.4% 연금소득세", correction)

    def test_comprehensive_tax_is_not_unconditional(self):
        """"무조건 종합과세" 단정을 16.5% 언급 없이도 교정한다 (300문 QA 세제 #26)."""
        correction = pension_tax_premise_correction(
            "수령액이 연 1,600만원이면 무조건 종합과세인가요?")
        self.assertIn("선택할 수 있습니다", correction)
        # 파이프라인에서도 전제교정이 calc_notes로 들어가는지 확인
        trace = answer("t", "수령액이 연 1,600만원이면 무조건 종합과세인가요?")["think_trace"]
        self.assertIn("[전제교정]", trace)

    def test_comprehensive_tax_correction_skips_below_threshold(self):
        """1,500만원 이하 금액이 명시된 질문에는 초과-선택지 교정을 붙이지 않는다."""
        self.assertIsNone(pension_tax_premise_correction(
            "수령액이 연 1,200만원이면 무조건 종합과세인가요?"))


class RateOnlyWithdrawalTest(unittest.TestCase):
    def test_care_withdrawal_without_amount_gets_rate_note(self):
        """금액 없는 중도인출 세율 질의도 계산기가 세율을 근거로 준다 (세제 #58)."""
        result, trace, _ = early_withdrawal_tax(
            None, "6개월 요양 진단받았는데 중도인출 세율이 어떻게 되죠?")
        self.assertTrue(result["unavoidable"])
        self.assertIn("3.3%~5.5% 연금소득세", trace)

    def test_general_withdrawal_without_amount_gets_16_5(self):
        result, trace, _ = early_withdrawal_tax(None, "그냥 중도인출하면 세율이 어떻게 되나요?")
        self.assertEqual(result["rate"], 0.165)
        self.assertIn("16.5% 기타소득세", trace)

    def test_pipeline_uses_withdrawal_calc_not_pension_income_table(self):
        """"세율" 단어로 수령 시 연금소득세 표가 끼어들지 않는다."""
        trace = answer("t", "6개월 요양 진단받았는데 중도인출 세율이 어떻게 되죠?")["think_trace"]
        self.assertIn("[계산] 중도인출 세금", trace)
        self.assertNotIn("[계산] 연금소득세", trace)

    def test_isa_transfer_triggers_without_full_term(self):
        """'세액공제' 풀네임 없이 "추가 공제"로 물어도 ISA 계산기가 돈다 (재실행 #81).

        계산기가 빠지면 2,000만원 케이스(정답 200만원)에 한도값 300만원을 답했다."""
        trace = answer("t", "ISA 만기자금 2,000만원을 연금저축으로 옮기면 추가 공제가 얼마죠?")["think_trace"]
        self.assertIn("[계산] ISA 전환 혜택", trace)
        self.assertIn("2,000,000", trace)

    def test_colloquial_break_triggers_withdrawal_calc(self):
        """"IRP 깨는 세금"처럼 구어로 물어도 계산기가 돈다 (승빈 QA #251).

        계산기가 빠지면 HCX가 15.4% 같은 근거 없는 세율을 지어냈다."""
        for question in ["IRP 깨는 세금 알려줘.", "연금저축 헐면 세금 얼마나 떼요?"]:
            trace = answer("t", question)["think_trace"]
            self.assertIn("[계산] 중도인출 세금", trace, question)
            self.assertIn("16.5%", trace, question)


if __name__ == "__main__":
    unittest.main()
