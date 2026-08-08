"""질의 라우터 v0 — 키워드 규칙 기반.

질의 유형(복수 가능)과, 추천 질의일 때 필요한 조건 슬롯의 충족 여부를 판정한다.
목표 버전에서는 HyperCLOVA X 분류로 교체하되 반환 스키마는 유지한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TAX = re.compile(r"세액공제|세금|과세|절세|소득세|공제|연말정산|수령한도|수령연차|종합과세|세율|감면")
PRODUCT = re.compile(r"펀드|상품|ETF|보수|수수료|위험등급|수익률|추천|비교|잔고|클래스|투자설명서")
PROCEDURE = re.compile(r"중도인출|해지|이전|절차|방법|어떻게 하|신청|서류|인출")
SYSTEM = re.compile(r"DB|DC|IRP|퇴직연금|연금저축|디폴트옵션|규약|가입|제도|압류|지연이자|퇴직금")

RECOMMEND = re.compile(r"추천|골라|어떤 게 좋|뭐가 좋|하나만|추천해")

# 보유 데이터(사적연금 제도·세제 문서 + 투자설명서)로 답할 수 없는 범위.
# 무리한 답변 대신 한계 고지로 응답한다 (평가지표: 정보한계 대응)
# 주의: 짧은 키워드는 다른 단어의 부분 문자열로 걸린다 ("4주가 지나기"의 '주가').
# 문맥을 함께 요구하는 패턴으로 쓴다.
OUT_OF_SCOPE = re.compile(
    r"국민연금|공무원연금|군인연금|사학연금|기초연금"      # 공적연금 (과제 범위 밖)
    r"|주가.{0,8}(전망|어떻|얼마|알려)|시세|얼마나 오를|오를까"  # 미래 예측·실시간 시장정보
    r"|수익률.{0,6}(전망|예상)|(전망|예상).{0,6}수익률"
    r"|(?:실시간|오늘).{0,8}(주가|시세|금리|환율|수익률)"
    r"|(?:비트코인|가상자산|암호화폐).{0,10}(전망|추천|시세|매수|매도)"
    r"|(내|제)\s*.*(잔고|계좌).*(조회|알려)|잔고\s*조회")

# 개인정보·프롬프트 공격 등 안전성 이슈 (평가지표: 안전성 및 신뢰성)
UNSAFE = re.compile(
    r"\d{6}\s*-\s*\d{7}"                                    # 주민등록번호 형태
    r"|(?:비밀번호|계좌번호|카드번호).{0,12}(알려|조회|입력|노출|기억)"
    r"|(?:알려|조회|입력|노출).{0,12}(비밀번호|계좌번호|카드번호)"
    r"|(?:지금까지|기존|이전|모든).{0,8}(지시|명령).{0,8}(무시|잊어)"
    r"|(?:시스템|개발자).{0,5}(프롬프트|메시지|메세지|지시).{0,8}(보여|공개|출력)"
    r"|(?:프롬프트|시스템 메시지|시스템 메세지).{0,8}(보여|공개|출력)"
    r"|탈옥|jailbreak|안전\s*(규칙|장치).{0,8}(우회|무시)"
    r"|무조건.*(추천|사라)|단정적으로")

# 조건부 추천에 필요한 슬롯과 감지 패턴
SLOTS = {
    "account": re.compile(r"IRP|연금저축|DC|퇴직연금 계좌|개인연금"),
    "risk": re.compile(r"안정|저위험|고위험|공격|위험 (감내|성향)|잃지 않|보수적|수익 위주"),
    "horizon": re.compile(r"\d+\s*년|단기|중기|장기|은퇴|55세|퇴직까지"),
}


@dataclass
class Route:
    categories: list[str] = field(default_factory=list)
    is_recommendation: bool = False
    filled_slots: dict[str, bool] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    out_of_scope: bool = False
    unsafe: bool = False

    def describe(self) -> str:
        s = f"유형={','.join(self.categories) or '일반'}"
        if self.is_recommendation:
            s += f" | 추천질의 (슬롯 충족={ {k: v for k, v in self.filled_slots.items()} }"
            s += f", 부족={self.missing_slots})"
        return s


def route(question: str) -> Route:
    r = Route()
    if UNSAFE.search(question):
        r.unsafe = True
        return r
    if OUT_OF_SCOPE.search(question):
        r.out_of_scope = True
        return r
    if TAX.search(question):
        r.categories.append("세제")
    if PRODUCT.search(question):
        r.categories.append("상품")
    if PROCEDURE.search(question):
        r.categories.append("절차")
    if SYSTEM.search(question):
        r.categories.append("제도")

    if RECOMMEND.search(question) and "상품" in r.categories:
        r.is_recommendation = True
        r.filled_slots = {k: bool(p.search(question)) for k, p in SLOTS.items()}
        r.missing_slots = [k for k, v in r.filled_slots.items() if not v]
        # 슬롯이 2개 이상 비면 단정 추천 대신 역질문으로 분기한다 (평가지표 대응)
        r.needs_clarification = len(r.missing_slots) >= 2
    return r


SLOT_QUESTIONS = {
    "account": "어떤 계좌에서 운용하실 예정인가요? (IRP / 연금저축 / DC 등)",
    "risk": "감내할 수 있는 위험 수준은 어느 정도인가요? (원금 보전 중시 / 다소 감수 / 수익 위주)",
    "horizon": "투자 기간이나 은퇴까지 남은 기간은 어느 정도인가요?",
}
