"""답변-근거 대조 검증 (Verifier).

설명회 발표 기준 금융권 최악 실패 유형이 '검증 실패'다. 생성된 답변이
근거(retrieved_context + 계산 결과) 밖의 수치를 말하고 있지 않은지 대조한다.

1단계 (결정적): 답변의 모든 수치 토큰이 근거 어딘가에 존재하는지 검사.
   수치는 환각의 가장 위험한 형태이고, 문자열 대조만으로 잡을 수 있다.
   단, 문자열 대조만으로는 두 가지를 못 잡는다:
     - 근거의 두 수치를 정당하게 합·차 계산한 새 수치를 "미확인"으로 오탐
       (tax-17: 330만-200만=130만). _derivable()로 구제한다.
     - 수치가 근거에 문자 그대로 있지만 가리키는 대상이 다른 경우
       (연금 "수령" 종합과세 기준 1,500만원을 "납입" 한도로 잘못 서술해도
       "1500"이라는 문자열 자체는 근거에 있어 1단계를 통과함). 이건 문자열
       대조로는 원리상 못 잡는다 — 그래서 2단계가 필요하다 (#43).
2단계 (HCX): 문장 단위 의미 검증. verify_claims_llm()이 답변을 문장으로 쪼개
   각 문장이 근거로 지지되는지 HCX에 판정시킨다. 답변마다 호출 하나가 추가로
   붙으므로 비용·지연이 늘어난다 — scope="numeric"으로 수치 포함 문장만 보내
   비용을 줄인다 (전체 문장 검증과의 비교는 eval/verifier_bench.py).
"""
from __future__ import annotations

import json
import re

from ..llm import get_llm

# 수치 토큰: 1,155,000 / 16.5% / 900만원의 '900' 등. 한 자리 숫자는
# 목록 번호(①1.2.)와 구분이 안 돼 두 자리 이상 또는 소수·퍼센트만 본다.
NUM = re.compile(r"\d[\d,]*\.\d+%?|\d[\d,]{1,}%?|\d%")

_SENT_END = re.compile(r"(?<=[.!?])\s+")
# 번호 목록 마커("1. ", "2) ")를 문장 끝으로 오인해 "1."과 본문을 분리하면
# 안 된다 — sys-1 실측에서 4항목짜리 목록이 마커만 8개의 빈 "문장"으로
# 쪼개져 전부 미지지 처리됐다 (검증 로직이 아니라 분리 단계의 버그였다).
_LIST_MARKER = re.compile(r"^(?:\d+[.)]|[-*·•])\s*")

# 사실을 새로 주장하지 않는 정형 문장 — LLM 검증 대상에서 제외한다.
# scope="all" 표본 실측(19문항)에서 미지지 오탐 5건이 전부 이 유형이었다:
# 도입문("…는 다음과 같습니다:"), 마무리 권유("…참고하여 …추천드립니다"),
# 한계 고지 정형구("제공된 자료로는 확인할 수 없습니다"). 프롬프트 규칙
# ("연결·설명 문장은 지지로")만으로는 안 걸러져서 결정적으로 거른다.
# 한계 고지·거절 정형구는 "근거에 없다"는 메타 진술이라, 검증2가 근거 인용을
# 못 찾아 미지지로 찍고 재확인 문구(※)를 덧붙였다. 정상적인 정보한계·단정거절
# 답변에 문구가 붙어 오히려 신뢰를 깎는다 (승빈 QA 101~200 실측: 🔴 52건 중
# 대부분이 이 유형). 사실을 새로 주장하지 않으므로 검증 대상에서 제외한다.
_NON_CLAIM = re.compile(
    r"다음과 같|아래와 같|참고하[여시]|추천드립니다"
    # 한계 고지·거절: "확인할 수 없", "알 수 없", "정보가 없", "찾을 수 없",
    # "판단하기 어렵", "제공(해 드릴/할) 수 없", "답변(을 드리기/드릴/제공)…어렵/없",
    # "명시(되어 있지 않|한 내용/정보가 없)", "포함되어 있지 않"
    r"|확인할 수 없|확인하기 어렵|알 수 없|판단하기 어렵|판단할 수 없"
    r"|정보가 (없|포함되어 있지 않|제공되지 않)|정보는 (없|제공되지 않)"
    r"|찾을 수 없|명시(되어 있지 않|한 (내용|정보)(이|가)? 없)"
    r"|포함되어 있지 않|포함하고 있지 않|제공하고 있지 않|제공되지 않"
    r"|답변(을 드리기|드리기|을 제공)[^.]*?(어렵|없|없습니다)"
    r"|제공(해 드릴|할|해드릴) 수 없|드릴 수 없|줄 수 없"
    r"|단정(적으로)?( 추천| 선택)?(할 수 없|하기 어렵)")


def _normalize(text: str) -> str:
    return text.replace(",", "").replace(" ", "")


def _numbers(text: str) -> list[str]:
    return [n for n in NUM.findall(text) if len(n.replace(",", "").rstrip("%")) >= 2 or "%" in n]


def _num_value(tok: str) -> float | None:
    """수치 토큰을 숫자로. %는 단위가 달라 합·차 유도 대상에서 제외한다."""
    if "%" in tok:
        return None
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


# 한국어 금액 표기: "115만 5천 원", "1,500만원", "5,500만" (원 생략), "1억 2,000만원".
# HCX가 계산 결과 1,155,000원을 답변에서 이렇게 바꿔 쓰는 일이 흔해, 문자열
# 대조만으로는 정답 수치가 미확인 판정돼 재확인 문구가 붙었다 (데모 실측).
# 억·만이 최소 하나 있어야 매칭한다 — "1,155,000원" 같은 일반 표기는 기존 경로.
_KAMOUNT = re.compile(
    r"(?:(\d[\d,]*)\s*억)?\s*(?:(\d[\d,]*)\s*만)\s*(?:(\d[\d,]*)\s*천)?\s*원?"
    r"|(\d[\d,]*)\s*억\s*원?")


def _k_won(m: "re.Match") -> float:
    def g(i):
        return float(m.group(i).replace(",", "")) if m.group(i) else 0.0
    if m.group(4):  # "3억" 단독
        return g(4) * 100_000_000
    return g(1) * 100_000_000 + g(2) * 10_000 + g(3) * 1_000


def _percent_values(text: str) -> list[float]:
    return [float(t.rstrip("%").replace(",", "")) for t in NUM.findall(text) if "%" in t]


def _derivable_value(v: float, evidence_nums: list[float],
                     evidence_pcts: list[float]) -> bool:
    """v가 근거 수치의 합·차 또는 근거 수치 × 근거 % 로 유도되는지 확인.

    곱셈 인정 근거: "400만 원의 16.5%는 66만 원" 같은 정당한 % 적용이
    미확인 판정돼 재확인 문구를 만들었다 (데모 실측). 근거에 실재하는
    수치 × 근거에 실재하는 %만 인정하므로 임의 수치는 통과하지 못한다."""
    for i, a in enumerate(evidence_nums):
        for b in evidence_nums[i + 1:]:
            if abs(a + b - v) < 0.5 or abs(a - b - v) < 0.5 or abs(b - a - v) < 0.5:
                return True
        for p in evidence_pcts:
            if abs(a * p / 100.0 - v) < 0.5:
                return True
            # 실수령액 2단계: "1,200만원에서 5.5%를 떼면 1,134만원" (복합 QA #26).
            # 같은 a에 같은 p를 적용한 차만 인정하므로 임의 조합은 통과 못 한다 —
            # 실제로 #26의 4.4%를 4%로 잘못 계산한 1,152만원은 그대로 잡힌다.
            if abs(a - a * p / 100.0 - v) < 0.5:
                return True
    return False


def _derivable(target: str, evidence_nums: list[float],
               evidence_pcts: list[float] | None = None) -> bool:
    """target 토큰이 근거 수치들로부터 정당하게 유도됐는지 확인."""
    pcts = evidence_pcts or []
    if "%" in target:
        # %는 근거 %끼리의 '차'만 유도로 인정한다 — "1년 수익률 4.0%와 3.47%의
        # 차 0.53%p" 같은 정당한 비교 산술 (석규 QA #148). 합은 인정하지 않는다:
        # 14%+1.4%=15.4% 같은 환각 세율 조합이 통과되는 통로가 된다.
        try:
            v = float(target.rstrip("%").replace(",", ""))
        except ValueError:
            return False
        return any(abs(abs(a - b) - v) < 0.005
                   for i, a in enumerate(pcts) for b in pcts[i + 1:])
    v = _num_value(target)
    if v is None:
        return False
    return _derivable_value(v, evidence_nums, pcts)


def _split_sentences(text: str) -> list[str]:
    """줄바꿈으로 먼저 나누고(목록 항목 보존), 줄 안에서 문장 부호로 다시 나눈다."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("근거:") or line.startswith("※"):
            continue  # 출처 표기·재확인 안내 줄은 주장이 아니라 검증 대상이 아님
        line = _LIST_MARKER.sub("", line, count=1)
        for s in _SENT_END.split(line):
            s = s.strip(" -*·")
            if s:
                out.append(s)
    return out


def verify_numbers(answer: str, context_blocks: list[str],
                   calc_notes: list[str], question: str = "") -> tuple[list[str], str]:
    """답변 수치가 근거에 존재하는지 검사. (미확인 수치 목록, 트레이스) 반환.

    질문 텍스트도 대조 대상에 포함한다 — "수령액이 1,600만원이면?"에 답하며
    1,600을 되풀이하는 것은 환각이 아닌데, 근거에만 대조하면 미확인으로
    찍혔다 (300문 QA 실측: 세제 리포트 미확인 13건 중 절반이 질문 수치
    재진술). 질문의 틀린 전제를 확인 없이 승인하는 문제는 검증2와
    전제교정의 몫이다 — 검증1은 존재 대조만 한다.

    CONFUSABLE_FACTS(프롬프트 고정 사실)의 한도·세율 수치도 근거로 인정한다 —
    900만·600만 같은 검증된 한도를 모델이 프롬프트에서 가져와 옳게 답했는데
    검색 근거에 그 문서가 안 걸리면 미확인으로 찍혔다 (승빈 QA #265·#273).
    본문 전체가 아니라 값 화이트리스트만 넣는다: 원문에는 "60%, 90일"처럼
    쓰지 말라고 든 금지 예시 수치도 있어 통째로 넣으면 그 환각이 통과된다."""
    from .generator import PROMPT_FACT_PCTS, PROMPT_FACT_WONS
    evidence_text = (" ".join(context_blocks) + " " + " ".join(calc_notes)
                     + " " + question)
    evidence_norm = _normalize(evidence_text)
    evidence_nums = [v for v in (_num_value(n) for n in _numbers(evidence_text)) if v is not None]
    # 근거의 한국어 금액("900만원")도 원 단위 값으로 집합에 넣는다
    evidence_nums += [_k_won(m) for m in _KAMOUNT.finditer(evidence_text)]
    evidence_vals = {round(v) for v in evidence_nums} | PROMPT_FACT_WONS
    evidence_pcts = _percent_values(evidence_text) + list(PROMPT_FACT_PCTS)

    # 주기 납입 질의의 연 환산 — "매달 30만원"의 연 360만원이 근거 어디에도
    # 없어 미확인으로 찍혔다 (복합 QA B 카테고리 실측 다수). 질문이 주기
    # 표현을 쓸 때만, 값 대조 집합에 한해 환산값을 인정한다 (합·차·곱셈
    # 유도의 소스로는 쓰지 않아 조합 폭발과 우연 일치를 막는다).
    if re.search(r"매달|매월|월\s*\d|매주|격월|주\s*\d", question):
        evidence_vals |= {round(v * k) for v in evidence_nums
                         for k in (12, 6, 52) if v > 0}

    # 답변의 한국어 금액은 통째로 값 대조한다 — 토큰화하면 "115만 5천 원"이
    # "115"와 "5"로 쪼개져 어떤 문자열 대조로도 살아남지 못한다.
    unmatched, derived, k_count, k_ok = [], [], 0, 0
    masked = answer
    for m in _KAMOUNT.finditer(answer):
        k_count += 1
        v = _k_won(m)
        masked = masked.replace(m.group(0), " ", 1)
        if round(v) in evidence_vals:
            k_ok += 1
        elif _derivable_value(v, evidence_nums, evidence_pcts):
            derived.append(m.group(0).strip().rstrip("원").strip() + "원")
        else:
            unmatched.append(m.group(0).strip())

    nums = _numbers(masked)
    if not nums and not k_count:
        return [], "[검증] 답변에 수치 없음 — 수치 검증 통과"
    for n in nums:
        if _normalize(n).rstrip("%") in evidence_norm:
            continue
        # %차 유도는 답변이 "0.53%p"처럼 명시적 차이 표기일 때만 —
        # 표기 제한 없이 인정했더니 "평균임금의 60%" 환각이 근거 %끼리의
        # 우연한 차와 일치해 통과했다 (자기교정 실측 회귀).
        pct_diff_ok = "%" not in n or (n + "p") in masked
        if pct_diff_ok and _derivable(n, evidence_nums, evidence_pcts):
            derived.append(n)
            continue
        unmatched.append(n)
    total = len(nums) + k_count
    ok = total - len(unmatched) - len(derived)
    parts = [f"답변 수치 {total}개 중 {ok}개 근거 확인"]
    if derived:
        parts.append(f"유도 산술 인정 {len(derived)}개({', '.join(derived[:5])})")
    if unmatched:
        parts.append(f"미확인 {len(unmatched)}개({', '.join(unmatched[:5])})")
    return unmatched, "[검증] " + ", ".join(parts)


# 근거에 문자 그대로 있는 수치라도 "무엇에 대한 값인가"가 틀리면 1단계로는
# 못 잡는다 (1,500만원=수령 종합과세 기준 vs 납입 한도). 문장 단위로 근거와
# 다시 대조해 이 유형을 잡는다.
#
# 처음에는 미지지 번호만 바로 답하게 했더니, 근거와 실제로 어긋나지 않는데도
# 두 개의 비슷한 금액(1,500만원/1,800만원)이 같은 답변에 나온다는 이유만으로
# 둘 중 하나를 거의 매번(5/5) 미지지로 찍었다 — 근거 없이 "의심스러워 보이는"
# 문장을 지어내는 패턴 매칭이었다. llm_judge.py가 겪은 것과 같은 함정
# (점수부터 찍고 근거를 사후에 짜맞춤)이라, 같은 해법을 썼다: 각 문장마다
# 뒷받침 근거를 먼저 인용하게 하고, 인용을 못 하면 그때만 미지지로 확정한다.
CLAIM_VERIFY_PROMPT = """당신은 사실 검증관입니다. [근거]와 [계산 결과]를 보고
[답변] 문장들이 지지되는지 판정하세요.

문장마다 다음 순서로 판단하세요:
1. 이 문장의 사실·수치를 직접 뒷받침하는 [근거]나 [계산 결과]의 문구를 그대로
   옮겨 적으세요 (quote). 뒷받침하는 문구가 없으면 quote를 빈 문자열로 두세요.
2. quote를 옮겨 적었다면, 그 quote가 문장과 같은 대상·기준(무엇에 대한
   값인지)을 말하는지 확인하세요. 같은 대상·기준이면 지지(O), 다른
   대상·기준에 수치만 갖다 붙였다면 미지지(X)입니다.
3. quote가 없으면 무조건 미지지(X)입니다. [근거]에 있는 두 수치의 합·차로
   자연스럽게 유도되는 문장, 또는 특정 사실·수치를 새로 주장하지 않는
   연결·설명 문장은 quote 없이도 지지(O)로 판정하세요.
4. 근거에 있는 조건·예외를 문장에서 생략한 것은 오류가 아닙니다. 문장이 말한
   내용 자체가 근거와 어긋나지 않으면 지지(O)입니다.

quote를 실제로 찾지 못했으면서 지지로 판정하지 마세요 — 짐작으로 의심하지도
마세요. quote가 있으면 원칙적으로 지지입니다.

수 표기 방식이 달라도 값이 같으면 같은 수치입니다 — "200만 원"과
"2,000,000원", "1,500만원"과 "15,000,000원"은 같은 값이므로, 표기만 다른
수치를 이유로 미지지(X)로 판정하지 마세요.

반드시 아래 JSON 형식으로, 문장 번호 순서대로 모두 답하세요:
{{"checks": [{{"n": 0, "quote": "<근거 문구 또는 빈 문자열>", "verdict": "O 또는 X"}}, ...]}}

[근거]
{context}

[계산 결과]
{calc}

[답변 — 번호별 문장]
{numbered}"""


def _parse_indices(raw: str) -> list[int]:
    """checks 배열에서 verdict가 X인 문장 번호만 뽑는다."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return []
    try:
        checks = json.loads(m.group()).get("checks", [])
    except json.JSONDecodeError:
        return []
    return [c["n"] for c in checks
           if isinstance(c, dict) and str(c.get("verdict", "")).strip().upper().startswith("X")
           and isinstance(c.get("n"), int)]


def verify_claims_llm(answer: str, context_blocks: list[str], calc_notes: list[str],
                      *, scope: str = "all") -> tuple[list[str], str | None]:
    """HCX로 문장 단위 의미 검증.

    scope="all" (기본값): 모든 문장을 검증한다. 8/25 채점 최저 문항 prem-3의
    결함("추가납입금·명예퇴직금은 압류 금지 대상이 아니다" — 근거와 정반대)이
    수치 없는 문장이라 numeric으로는 원리상 못 잡는 것이 실측됐다. 미탐(환각
    통과 → Hallucination 지표 직격)이 오탐(정답에 재확인 안내 한 줄)보다
    비싸고, 문항당 지연 +0.9초는 평가 타임아웃 300초(8/24 공지) 안에서
    무의미해 all을 기본으로 한다.
    scope="numeric": 수치 포함 문장만 — 비용·오탐을 더 줄여야 할 때의 대안.
    실측 비교는 eval/verifier_bench.py.

    반환: (미지지 문장 목록, 트레이스). Mock 단계에서는 (빈 목록, None) —
    apply()가 None이면 트레이스에 이 단계를 아예 안 붙인다.
    """
    llm = get_llm()
    if llm.name == "mock":
        return [], None
    sentences = _split_sentences(answer)
    # 10자 미만은 "(doc41)" 같은 분리 부스러기라 주장으로 볼 수 없다 (실측 오탐).
    targets = [(i, s) for i, s in enumerate(sentences)
              if (scope == "all" or _numbers(s))
              and len(s) >= 10 and not _NON_CLAIM.search(s)]
    if not targets:
        return [], "[검증2] 검증 대상 문장 없음 — 의미 검증 생략"
    numbered = "\n".join(f"{i}. {s}" for i, s in targets)
    ctx = "\n\n---\n\n".join(context_blocks)[:4000] if context_blocks else "(근거 없음)"
    calc = "\n".join(calc_notes) if calc_notes else "(없음)"
    prompt = CLAIM_VERIFY_PROMPT.format(context=ctx, calc=calc, numbered=numbered)
    # quote를 문장마다 받으므로 번호만 받을 때보다 토큰이 더 든다.
    raw = llm.generate(prompt, max_tokens=120 + 80 * len(targets))
    # 심판이 검증 대상 목록에 없는 번호를 X로 찍는 일이 실측됐다 (필터로
    # 제외한 도입문이 미지지로 둔갑). 대상으로 보낸 번호만 인정한다.
    target_idx = {i for i, _ in targets}
    bad = [sentences[i] for i in _parse_indices(raw) if i in target_idx]
    trace = (f"[검증2] {scope} 범위 {len(targets)}문장 검증, 미지지 {len(bad)}건"
             + (f": {bad[0][:60]}" if bad else ""))
    return bad, trace


def apply(answer: str, context_blocks: list[str], calc_notes: list[str],
          llm_name: str, *, skip_claims: bool = False,
          question: str = "", regenerate=None) -> tuple[str, str]:
    """검증을 수행하고 (필요 시 보정된 답변, 트레이스)를 돌려준다.

    미확인 수치나 미지지 문장이 있으면: Mock 단계에서는 기록만 남기고, 실제
    LLM 답변에는 확정 문장 대신 재확인 안내를 덧붙인다 (근거 없는 내용을
    단정하지 않기). 2단계는 1단계 결과와 무관하게 항상 실행한다 — "문자열은
    근거에 있지만 대상이 틀린" 경우는 1단계가 원리상 못 잡기 때문이다.

    예외가 skip_claims=True(비교표 경로, #59): 비교표는 funds.json에서 코드로
    만든 결정적 데이터라 의미 검증의 추가 가치가 없는데, 답변이 표를 목록으로
    풀어 쓰면 상품명·항목 조각이 인용 매칭에 실패해 오탐이 난다 (시나리오 D
    실측: 27문장 중 미지지 10건 — 전부 오탐). 수치는 1단계가 표와 대조해
    그대로 잡으므로 2단계만 생략한다.
    """
    unmatched, trace = verify_numbers(answer, context_blocks, calc_notes, question)
    if skip_claims:
        unsupported, trace2 = [], "[검증2] 비교표 경로 — 결정적 근거라 의미 검증 생략"
    else:
        unsupported, trace2 = verify_claims_llm(answer, context_blocks, calc_notes)
    if trace2:
        trace += "\n" + trace2

    # 자기교정(#62 세션): 미지지 문장이 있고 재생성 콜백이 있으면 1회 다시 쓰게
    # 하고 재검증한다. 깨끗해지면 채택, 줄었지만 남으면 개선분 채택 후 안내,
    # 효과 없으면 원본 유지. 재생성·재검증에 HCX 호출 2회가 추가되지만 평가
    # 타임아웃 300초(8/24 공지) 안에서 감당된다. 폴백이 현행 동작이라 최악의
    # 경우에도 지금과 같다.
    if unsupported and regenerate is not None and llm_name != "mock":
        new_answer = regenerate(unsupported)
        r_unmatched, _ = verify_numbers(new_answer, context_blocks, calc_notes, question)
        if skip_claims:
            r_unsupported = []
        else:
            r_unsupported, _ = verify_claims_llm(new_answer, context_blocks, calc_notes)
        if not r_unsupported and not r_unmatched:
            trace += (f"\n[자기교정] 미지지 {len(unsupported)}건 → 재생성 후 0건, "
                      "교정 답변 채택")
            return new_answer, trace
        if len(r_unsupported) + len(r_unmatched) < len(unsupported) + len(unmatched):
            trace += (f"\n[자기교정] 미지지 {len(unsupported)}→{len(r_unsupported)}건, "
                      "개선분 채택 후 안내")
            answer, unmatched, unsupported = new_answer, r_unmatched, r_unsupported
        else:
            trace += (f"\n[자기교정] 재생성 효과 없음(미지지 {len(r_unsupported)}건), "
                      "원본 유지")

    if (unmatched or unsupported) and llm_name != "mock":
        answer += ("\n\n※ 위 답변 중 일부 내용은 제공된 자료에서 직접 확인되지 "
                   "않았습니다. 정확한 값은 근거 문서를 확인해 주세요.")
    return answer, trace
