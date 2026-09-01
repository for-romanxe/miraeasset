"""API 키 없이 실행하는 verifier 회귀 테스트 (#43)."""
import unittest

from agent.pipeline import verifier


class NumberMatchTest(unittest.TestCase):
    def test_matched_numbers_pass(self):
        unmatched, trace = verifier.verify_numbers(
            "세액공제 한도는 900만원입니다.", ["연 900만원까지 세액공제"], [])
        self.assertEqual(unmatched, [])
        self.assertIn("1개 중 1개 근거 확인", trace)

    def test_ungrounded_number_flagged(self):
        """근거에도 없고 두 수치의 합·차로도 안 나오면 그대로 미확인 처리."""
        unmatched, trace = verifier.verify_numbers(
            "IRP는 연간 700만원까지 세액공제됩니다.",
            ["연금저축은 600만원, IRP는 합산 900만원까지 세액공제"], [])
        self.assertTrue(any("700" in u for u in unmatched), unmatched)


class DerivableArithmeticTest(unittest.TestCase):
    """tax-17 오탐 — 근거 수치 두 개의 정당한 합·차 결과를 미확인으로 잘못 표시했었다."""

    def test_subtraction_of_evidence_numbers_is_not_flagged(self):
        calc_notes = ["사적연금 전체 20,000,000원 × 10.0% = 2,000,000원 "
                      "vs × 16.5% = 3,300,000원"]
        answer = "종합과세와 분리과세의 세액 차이는 1,300,000원입니다."
        unmatched, trace = verifier.verify_numbers(answer, [], calc_notes)
        self.assertEqual(unmatched, [])
        self.assertIn("유도 산술 인정", trace)

    def test_addition_of_evidence_numbers_is_not_flagged(self):
        unmatched, _ = verifier.verify_numbers(
            "두 계좌를 합치면 총 900만원입니다.",
            ["연금저축 600만원", "IRP 300만원"], [])
        self.assertEqual(unmatched, [])

    def test_unrelated_number_is_still_flagged_despite_other_evidence_numbers(self):
        """근거에 숫자가 여럿 있다고 아무 수치나 통과시키면 안 된다."""
        unmatched, _ = verifier.verify_numbers(
            "세액공제 한도는 700만원입니다.",
            ["연금저축 600만원", "IRP 합산 900만원"], [])
        self.assertTrue(any("700" in u for u in unmatched), unmatched)

    def test_percent_tokens_excluded_from_arithmetic(self):
        """%는 금액과 단위가 달라 합·차 유도 대상에서 제외해야 한다."""
        unmatched, _ = verifier.verify_numbers(
            "세율은 21.5%입니다.", ["세율 16.5%", "가산율 5%"], [])
        self.assertIn("21.5%", unmatched)


class KoreanNotationTest(unittest.TestCase):
    """한국어 금액 표기 동치 — 데모 실측: 계산 결과 1,155,000원을 답변이
    "115만 5천 원"으로 바꿔 써서 정답에 재확인 문구가 붙었다."""

    def test_korean_amount_matches_digit_evidence(self):
        unmatched, trace = verifier.verify_numbers(
            "합계는 115만 5천 원입니다.", [], ["세액공제 = 1,155,000원"])
        self.assertEqual(unmatched, [])
        self.assertIn("1개 근거 확인", trace)

    def test_korean_amount_without_won_suffix(self):
        unmatched, _ = verifier.verify_numbers(
            "총급여 5,500만 이하라면 적용됩니다.", ["총급여액 5,500만원 이하"], [])
        self.assertEqual(unmatched, [])

    def test_wrong_korean_amount_still_flagged(self):
        unmatched, _ = verifier.verify_numbers(
            "합계는 120만 원입니다.", [], ["세액공제 = 1,155,000원"])
        self.assertEqual(unmatched, ["120만 원"])


class MultiplicationDerivationTest(unittest.TestCase):
    """근거 수치 × 근거 % 유도 인정 — 데모 실측: "400만 원의 16.5%는 66만 원"이
    정당한 계산인데 미확인 판정됐다."""

    def test_percent_application_is_derived(self):
        unmatched, trace = verifier.verify_numbers(
            "400만 원의 16.5%인 66만 원을 공제받습니다.",
            ["연금저축 4,000,000원까지 16.5% 세액공제"], [])
        self.assertEqual(unmatched, [])
        self.assertIn("유도 산술 인정", trace)

    def test_wrong_product_still_flagged(self):
        """근거 수치 × 근거 %로 안 나오는 값은 여전히 미확인."""
        unmatched, _ = verifier.verify_numbers(
            "공제액은 77만 원입니다.",
            ["연금저축 4,000,000원까지 16.5% 세액공제"], [])
        self.assertEqual(unmatched, ["77만 원"])


class SentenceSplitTest(unittest.TestCase):
    def test_splits_on_sentence_end_and_newline(self):
        text = "IRP는 개인형 퇴직연금입니다. 연 1,800만원까지 납입 가능합니다.\n- 세액공제 한도는 900만원입니다."
        sentences = verifier._split_sentences(text)
        self.assertEqual(len(sentences), 3)
        self.assertTrue(sentences[2].startswith("세액공제"))

    def test_numbered_list_marker_not_split_off(self):
        """sys-1 실측 버그 — "1. 문장"이 "1."과 "문장"으로 쪼개지면 안 된다."""
        text = "IRP는 다음이 가입할 수 있습니다:\n1. 자영업자\n2. DC 가입자"
        sentences = verifier._split_sentences(text)
        self.assertEqual(sentences, ["IRP는 다음이 가입할 수 있습니다:", "자영업자", "DC 가입자"])

    def test_parenthesis_list_marker_not_split_off(self):
        text = "1) 첫째 조건\n2) 둘째 조건"
        sentences = verifier._split_sentences(text)
        self.assertEqual(sentences, ["첫째 조건", "둘째 조건"])

    def test_source_line_dropped(self):
        sentences = verifier._split_sentences("답변입니다.\n\n근거: doc41(연금저축) 본문")
        self.assertEqual(sentences, ["답변입니다."])

    def test_reconfirmation_notice_dropped(self):
        sentences = verifier._split_sentences(
            "답변입니다.\n\n※ 위 답변 중 일부 내용은 확인되지 않았습니다.")
        self.assertEqual(sentences, ["답변입니다."])


class QuestionNumberTest(unittest.TestCase):
    """질문의 수치를 답변이 되풀이하는 것은 환각이 아니다 (300문 QA 실측)."""

    def test_question_number_restated_in_answer_passes(self):
        unmatched, _ = verifier.verify_numbers(
            "수령액이 연 1,600만 원이면 1,500만 원을 초과하므로 선택이 필요합니다.",
            ["연 1,500만원 초과 수령 시 종합과세 또는 16.5% 분리과세"], [],
            question="수령액이 연 1,600만원이면 무조건 종합과세인가요?")
        self.assertEqual(unmatched, [])

    def test_number_absent_from_question_and_evidence_still_flagged(self):
        unmatched, _ = verifier.verify_numbers(
            "약 9억 원 이하 주택이 대상입니다.",
            ["퇴직연금 관련 근거"], [],
            question="주택연금 가입 조건이 궁금해요.")
        self.assertEqual(unmatched, ["9억 원"])


class NonClaimFilterTest(unittest.TestCase):
    """한계 고지·거절 정형구는 검증2 대상에서 제외한다 (승빈 QA 101~200 실측).

    이런 메타 진술을 검증2에 보내면 근거 인용을 못 찾아 미지지로 찍고
    재확인 문구(※)를 붙여, 정상적인 정보한계·단정거절 답변의 신뢰를 깎았다."""

    LIMITATION = [
        "제공된 자료로는 오늘 코스피 지수에 대해 알 수 없습니다.",
        "제공된 자료에는 실패 없는 상품을 명시한 내용이 없습니다.",
        "공시된 펀드 보수에 대한 구체적인 내용을 찾을 수 없습니다.",
        "환율 변동에 따른 투자의 적절성을 판단하기 어렵습니다.",
        "특정 상품을 단정적으로 추천할 수 없습니다.",
        "관련 정보가 포함되어 있지 않으므로 답변을 제공할 수 없습니다.",
    ]
    REAL_CLAIM = [
        "안정 모드로 운용한다는 것은 위험이 낮은 상품을 의미합니다.",
        "연금저축 세액공제 한도는 연 600만원입니다.",
        "IRP는 만 55세 이후 연금으로 수령할 수 있습니다.",
    ]

    def test_limitation_statements_excluded(self):
        for s in self.LIMITATION:
            self.assertTrue(verifier._NON_CLAIM.search(s), s)

    def test_real_claims_still_checked(self):
        for s in self.REAL_CLAIM:
            self.assertIsNone(verifier._NON_CLAIM.search(s), s)


class SkipClaimsTest(unittest.TestCase):
    """비교표 경로에서는 2단계를 생략한다 (#59 — 시나리오 D 오탐 10건 실측)."""

    def test_skip_claims_leaves_trace_and_no_notice(self):
        answer, trace = verifier.apply(
            "위험등급은 5등급입니다.", ["| 위험등급 | 5등급 |"], [],
            "hyperclova-x", skip_claims=True)
        self.assertIn("비교표 경로", trace)
        self.assertNotIn("※", answer)

    def test_number_check_still_runs_when_claims_skipped(self):
        """2단계만 생략 — 1단계 수치 대조는 비교표 경로에서도 유지돼야 한다."""
        answer, trace = verifier.apply(
            "총보수는 0.99%입니다.", ["| 최저 총보수(연) | 0.275% |"], [],
            "hyperclova-x", skip_claims=True)
        self.assertIn("미확인", trace)
        self.assertIn("※", answer)


class ClaimVerifyMockTest(unittest.TestCase):
    """CLOVASTUDIO_API_KEY 없이 돌리는 스위트라 MockLLM 경로만 검증한다."""

    def test_mock_llm_skips_claim_check(self):
        unsupported, trace = verifier.verify_claims_llm(
            "연금저축과 IRP 합쳐서 1,800만원까지 납입 가능합니다.",
            ["연 1,800만원까지 납입 가능"], [])
        self.assertEqual(unsupported, [])
        self.assertIsNone(trace)


class ApplyTest(unittest.TestCase):
    def test_apply_appends_no_disclaimer_in_mock_mode(self):
        answer, trace = verifier.apply(
            "IRP는 연 700만원까지 세액공제됩니다.",
            ["연금저축 600만원, IRP 합산 900만원"], [], "mock")
        self.assertNotIn("직접 확인되지", answer)
        self.assertIn("미확인", trace)

    def test_apply_keeps_trace_single_block_when_claim_check_skipped(self):
        _, trace = verifier.apply(
            "세액공제 한도는 900만원입니다.", ["연 900만원까지 세액공제"], [], "mock")
        self.assertNotIn("[검증2]", trace)


if __name__ == "__main__":
    unittest.main()
