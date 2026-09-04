"""검색 어휘 확장이 특정 평가 문장을 암기하지 않는지 검증한다."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.pipeline.retriever import (  # noqa: E402
    format_aum,
    get_docs_index,
    get_funds_index,
    parse_fund_filter,
)


class RetrieverGeneralizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = get_docs_index()

    def assert_doc_hit(self, question: str, expected: set[str]):
        hits = self.index.search(question, k=5)
        actual = {hit["doc_id"] for hit in hits}
        self.assertTrue(actual & expected, f"expected {expected}, got {actual}")

    def test_dc_operation_responsibility_paraphrase(self):
        self.assert_doc_hit(
            "DC형에서 투자 판단과 운용 손실은 회사가 책임지나요?",
            {"doc11", "doc15", "doc13"},
        )

    def test_pension_payment_application_paraphrase(self):
        self.assert_doc_hit(
            "IRP 연금 지급을 신청하려면 어떤 절차를 밟아야 하나요?",
            {"doc21", "doc2"},
        )

    def test_closed_company_direct_claim_paraphrase(self):
        self.assert_doc_hit(
            "직장이 폐업해서 퇴직급여가 지급 누락됐는데 직접 받을 방법이 있나요?",
            {"doc57"},
        )

    def test_tax_source_confirmation_paraphrase(self):
        self.assert_doc_hit(
            "IRP 과세 재원 확정과 과세 제외 금액은 어떻게 처리하나요?",
            {"doc19"},
        )

    def test_withdrawal_order_paraphrase(self):
        self.assert_doc_hit(
            "노후에 연금을 꺼내는 인출 순서와 준비 방법이 궁금해요.",
            {"doc37"},
        )


    def test_benefit_payment_precheck_retrieves_staff_role_chunk(self):
        hits = self.index.search(
            "퇴직연금 사무담당자가 급여 지급 전에 확인할 사항은 뭔가요?",
            k=5,
        )
        self.assertTrue(
            any(
                hit["doc_id"] == "doc55" and "사무담당자의 역할" in hit["text"]
                for hit in hits
            ),
            "doc55의 DB 퇴직급여 사무담당자 역할 청크가 필요합니다.",
        )


class FundConditionSearchTest(unittest.TestCase):
    """이름 없는 조건 질의 — by_name이 못 잡아 "없음" 오답이 났다 (석규 QA H 5/15)."""

    def test_fee_ceiling_with_asset_type(self):
        """"총보수 0.3% 아래 채권형" — 실제로 0.085%부터 여럿 있다 (#134 오답 재현)."""
        cond = parse_fund_filter("총보수 0.3% 아래 채권형 뭐 있어요?")
        self.assertEqual(cond["asset_type_group"], "채권형")
        self.assertEqual(cond["max_fee"], 0.3)
        matches = get_funds_index().filter(**cond, k=5)
        self.assertTrue(matches)
        self.assertTrue(all(f["min_total_fee"] <= 0.3 for f in matches))

    def test_cheapest_fund_sorts_by_fee(self):
        cond = parse_fund_filter("보수가 가장 저렴한 펀드가 뭐예요?")
        self.assertTrue(cond["sort_by_fee"])
        matches = get_funds_index().filter(**cond, k=3)
        fees = [f["min_total_fee"] for f in matches]
        self.assertEqual(fees, sorted(fees))

    def test_low_risk_within_asset_type(self):
        cond = parse_fund_filter("주식형 중 위험등급 낮은 게 있어요?")
        self.assertEqual(cond["asset_type_group"], "주식형")
        self.assertEqual(cond["sort_by_risk"], "low")

    def test_explanation_and_tax_questions_do_not_trigger(self):
        """설명·세제 질의를 조건 검색으로 오인하면 안 된다."""
        for q in ["채권형 펀드가 뭐예요?", "IRP 세액공제 한도 알려줘",
                  "연금저축 안정적으로 운용하는 원칙 알려줘"]:
            self.assertIsNone(parse_fund_filter(q), q)


class AumFormatTest(unittest.TestCase):
    def test_aum_shows_correct_eok_conversion(self):
        """"4,426백만원"만 주면 HCX가 "4,426억"으로 바꿔 쓴다 — 올바른 억원을 앞에."""
        self.assertEqual(format_aum(4426), "약 44억원(4,426백만원)")
        self.assertEqual(format_aum(1827), "약 18억원(1,827백만원)")


if __name__ == "__main__":
    unittest.main()
