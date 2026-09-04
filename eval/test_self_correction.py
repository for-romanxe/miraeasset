"""자기교정 오케스트레이션 테스트 (#62 세션).

HCX 없이 verifier.apply의 재생성 흐름만 검증한다. verify_numbers/
verify_claims_llm과 재생성 콜백을 스텁으로 갈아끼워, 재생성 결과에 따라
채택/개선/원본유지 분기가 맞는지 본다.
"""
import unittest
from unittest.mock import patch

from agent.pipeline import verifier


class SelfCorrectionTest(unittest.TestCase):
    def _run(self, first_unsupported, regen_unsupported, regen_unmatched=None,
             first_unmatched=None):
        """verify를 스텁으로 고정하고 apply를 돌린다.

        verify_claims_llm은 첫 호출에 first_unsupported, 두 번째(재검증)에
        regen_unsupported를 돌려주도록 순차 스텁.
        """
        calls = {"claims": 0, "nums": 0}
        first_unmatched = first_unmatched or []
        regen_unmatched = regen_unmatched or []

        def fake_claims(ans, ctx, calc):
            calls["claims"] += 1
            return (first_unsupported if calls["claims"] == 1 else regen_unsupported,
                    "[검증2] stub")

        def fake_nums(ans, ctx, calc, question=""):
            calls["nums"] += 1
            return (first_unmatched if calls["nums"] == 1 else regen_unmatched,
                    "[검증] stub")

        with patch.object(verifier, "verify_claims_llm", fake_claims), \
                patch.object(verifier, "verify_numbers", fake_nums):
            return verifier.apply(
                "원본 답변", ["근거"], [], "hyperclova-x",
                regenerate=lambda unsup: "교정된 답변")

    def test_clean_after_regen_adopts_new_answer(self):
        """재생성 후 미지지 0건이면 교정 답변을 채택하고 안내 문구는 없다."""
        answer, trace = self._run(["나쁜 문장"], [])
        self.assertEqual(answer, "교정된 답변")
        self.assertIn("교정 답변 채택", trace)
        self.assertNotIn("※", answer)

    def test_partial_improvement_adopts_new_with_notice(self):
        """미지지가 줄었지만 남으면 개선분을 채택하고 안내 문구를 붙인다."""
        answer, trace = self._run(["문장A", "문장B"], ["문장A"])
        self.assertEqual(answer.split("\n\n※")[0], "교정된 답변")
        self.assertIn("2→1건", trace)
        self.assertIn("※", answer)

    def test_no_improvement_keeps_original(self):
        """재생성이 개선을 못 하면 원본을 유지하고 안내를 붙인다."""
        answer, trace = self._run(["문장A"], ["문장A"])
        self.assertEqual(answer.split("\n\n※")[0], "원본 답변")
        self.assertIn("효과 없음", trace)
        self.assertIn("※", answer)

    def test_no_regenerate_callback_falls_back(self):
        """콜백이 없으면 기존 동작(안내 문구)만."""
        def fake_claims(a, c, cn):
            return ["문장A"], "[검증2] stub"

        def fake_nums(a, c, cn, question=""):
            return [], "[검증] stub"

        with patch.object(verifier, "verify_claims_llm", fake_claims), \
                patch.object(verifier, "verify_numbers", fake_nums):
            answer, trace = verifier.apply("원본", ["근거"], [], "hyperclova-x")
        self.assertIn("※", answer)
        self.assertNotIn("자기교정", trace)

    def test_mock_llm_never_self_corrects(self):
        """Mock 단계에서는 재생성을 시도하지 않는다 (회귀 보호)."""
        called = {"regen": False}

        def regen(unsup):
            called["regen"] = True
            return "x"

        def fake_claims(a, c, cn):
            return ["문장A"], "[검증2] stub"

        def fake_nums(a, c, cn, question=""):
            return [], "[검증] stub"

        with patch.object(verifier, "verify_claims_llm", fake_claims), \
                patch.object(verifier, "verify_numbers", fake_nums):
            answer, trace = verifier.apply("원본", ["근거"], [], "mock", regenerate=regen)
        self.assertFalse(called["regen"])
        self.assertNotIn("※", answer)


if __name__ == "__main__":
    unittest.main()
