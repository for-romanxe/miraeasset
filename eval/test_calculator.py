"""API 키 없이 실행하는 세제 계산기 회귀 테스트."""
import unittest

from agent.pipeline import answer
from agent.pipeline.calculator import (
    pension_income_tax,
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

    def test_bare_eok_amount_is_parsed(self):
        """"1억 있으면"처럼 원을 생략해도 금액으로 읽는다 (spot 재확인 #2).

        미발동 시 HCX가 수령한도를 ÷(11-1) 대신 ÷11로 계산했다."""
        trace = answer("t", "1년차에 수령한도라는 게 있다면서요? 1억 있으면 첫해 최대 얼마까지 뺄 수 있어요?")["think_trace"]
        self.assertIn("[계산] 연금수령한도", trace)
        self.assertIn("12,000,000", trace)

    def test_monthly_amount_is_annualized_for_credit(self):
        """"매달 30만원"은 연 360만원으로 환산해 세액공제를 계산한다 (복합 QA #11)."""
        trace = answer("t", "매달 30만원씩 연금저축에 붓고 있어요. 1년 공제액이 얼마나 되나요?")["think_trace"]
        self.assertIn("[계산] 세액공제", trace)
        self.assertIn("3,600,000", trace)

    def test_pension_income_tax_includes_net_amount(self):
        """수령액이 있으면 세액·실수령까지 계산한다 — HCX가 4.4% 곱셈을 반복해서
        틀렸다 (복합 QA #26: 1,147.2만이 정답인데 1,152만·1,158만)."""
        _, trace, _ = pension_income_tax(72, 12_000_000)
        self.assertIn("528,000", trace)
        self.assertIn("11,472,000", trace)

    def test_withdrawal_limit_triggers_with_spacing_variants(self):
        """"수령한도라는 게 있다면서요"도 계산기가 돈다 (복합 QA #79·#236).

        미발동 시 HCX가 ÷(11-n)을 빼먹고 10배 오계산(800만→8천만)했다."""
        trace = answer("t", "수령한도라는 게 있다면서요. 계좌에 6천만원 있고 2년차면 한도 얼마고, 넘게 빼면 어떻게 돼요?")["think_trace"]
        self.assertIn("[계산] 연금수령한도", trace)
        self.assertIn("8,000,000", trace)

    def test_colloquial_tax_words_trigger_calc(self):
        """세금 쪽 표현도 구어를 인식한다 (#57 "몇 프로", #62 "손에 쥐는 돈").

        계산기가 빠지자 개인회생을 부득이한 사유가 아니라고 반대로 판정하고
        (정답: 65세 5.5% 연금소득세), 500만 해지에 825만 수령이라는 산술
        붕괴가 나왔다."""
        trace = answer("t", "개인회생 중인데 IRP 깨면 몇 프로 떼나요? 65세입니다.")["think_trace"]
        self.assertIn("[계산] 중도인출 세금", trace)
        self.assertIn("5.5% 연금소득세", trace)
        trace = answer("t", "연금저축 500만원 해지하면 손에 쥐는 돈이 얼마죠?")["think_trace"]
        self.assertIn("[계산] 중도인출 세금", trace)
        self.assertIn("825,000", trace)


if __name__ == "__main__":
    unittest.main()
