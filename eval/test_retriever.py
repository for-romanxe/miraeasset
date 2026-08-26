"""검색 어휘 확장이 특정 평가 문장을 암기하지 않는지 검증한다."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.pipeline.retriever import get_docs_index  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
