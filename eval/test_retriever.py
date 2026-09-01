"""검색 어휘 확장이 특정 평가 문장을 암기하지 않는지 검증한다."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.pipeline.retriever import format_aum, get_docs_index  # noqa: E402


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


class AumFormatTest(unittest.TestCase):
    def test_aum_shows_correct_eok_conversion(self):
        """"4,426백만원"만 주면 HCX가 "4,426억"으로 바꿔 쓴다 — 올바른 억원 병기."""
        self.assertEqual(format_aum(4426), "4,426백만원(약 44억원)")
        self.assertEqual(format_aum(1827), "1,827백만원(약 18억원)")


if __name__ == "__main__":
    unittest.main()
