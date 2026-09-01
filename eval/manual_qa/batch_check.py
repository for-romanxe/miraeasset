#!/usr/bin/env python3
"""시험 질문 파일을 파이프라인에 일괄 실행하고 점검 리포트를 만든다.

기본은 서버 없이 파이프라인을 직접 호출한다(--direct, 기본값). 레포 루트에서
.venv + .env(CLOVASTUDIO_API_KEY)만 있으면 실행되므로 팀원이 자기 컴퓨터에서
바로 돌릴 수 있다.

사용:
  # 레포 루트에서, 키 로드 후
  set -a && . ./.env && set +a
  .venv/bin/python eval/manual_qa/batch_check.py eval/manual_qa/시험질문-승빈-안전경계-300.txt
  ... <파일> -n 20        # 앞 20문항만
  ... <파일> --start 51   # 51번부터 이어서
  ... <파일> --http       # 데모 서버(127.0.0.1:8090)로 실행하는 옛 방식

주의: HCX 한도(계정 공유 분당 60요청/6만 토큰) 때문에 문항 간 5초 간격.
100문항 ≈ 20~25분, 비용 ≈ 500원. 같은 키를 쓰는 팀원끼리 동시에 돌리면
서로 429가 나므로 시간을 나눠서 돌린다.
리포트는 질문 파일과 같은 폴더에 <파일명>-리포트.md 로 저장된다(중간 저장).
"""
import re
import sys
import time
from pathlib import Path

BASE = "http://127.0.0.1:8090"
PACE = 5.0
ROOT = Path(__file__).resolve().parent.parent.parent  # 레포 루트


def load_questions(path: Path) -> list[tuple[str, str]]:
    out, section = [], ""
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line.startswith("##"):
            section = line.lstrip("#").strip()
        m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if m:
            q = re.sub(r"\s*\([^)]*→[^)]*\)\s*$", "", m.group(2))  # 기대 주석 제거
            out.append((section, q))
    return out


def make_answerer(use_http: bool):
    """(question_id, question) -> dict(5필드) 를 돌려주는 함수를 만든다."""
    if use_http:
        import requests

        def via_http(qid: str, q: str) -> dict:
            r = requests.get(f"{BASE}/answer",
                             params={"question_id": qid, "question": q},
                             timeout=180)
            return r.json()
        return via_http

    # 직접 호출: 데모 서버 불필요. server.answer와 동일하게 예외를 5필드로 감싼다.
    sys.path.insert(0, str(ROOT))
    from agent import pipeline
    from agent.pipeline import generator

    def via_direct(qid: str, q: str) -> dict:
        try:
            return pipeline.answer(qid, q)
        except Exception:
            return {
                "question_id": qid, "question": q, "retrieved_context": "",
                "think_trace": "[오류] 일시적 장애로 답변을 생성하지 못했습니다",
                "answer": generator.limitation_answer(),
            }
    return via_direct


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = Path(args[0]).expanduser()
    n = int(args[args.index("-n") + 1]) if "-n" in args else None
    start = int(args[args.index("--start") + 1]) if "--start" in args else 1
    use_http = "--http" in args
    answer = make_answerer(use_http)

    items = load_questions(path)[start - 1:][:n]
    report = path.with_name(path.stem + "-리포트.md")
    mode = "데모 서버(HTTP)" if use_http else "파이프라인 직접 호출"

    lines = [f"# 점검 리포트 — {path.name} ({len(items)}문항, {mode})\n"]
    flagged = 0
    for i, (section, q) in enumerate(items, start):
        t0 = time.time()
        try:
            d = answer(f"QA-{i}", q)
        except Exception as e:
            print(f"[{i}] 오류 {type(e).__name__}: {q[:40]}", flush=True)
            lines.append(f"## {i}. {q}\n- ⚠️ 요청 오류: {type(e).__name__}\n")
            time.sleep(20)
            continue
        dt = time.time() - t0
        verify = [l for l in d["think_trace"].split("\n")
                  if l.startswith(("[검증", "[라우팅", "[전제교정", "[가드", "[가정"))]
        notice = "※" in d["answer"]
        bad = notice or any("미확인" in v or ("미지지 " in v and "0건" not in v)
                            for v in verify)
        if bad:
            flagged += 1
        mark = "\U0001f534" if bad else "\U0001f7e2"
        print(f"[{i}/{start + len(items) - 1}] {mark} {dt:4.1f}s  {q[:44]}", flush=True)
        lines.append(f"## {i}. {mark} {q}")
        lines.append(f"_{section} · {dt:.1f}s_")
        lines.append("")
        lines.append("> " + d["answer"][:400].replace("\n", "\n> "))
        lines.append("")
        for v in verify:
            lines.append(f"- `{v[:140]}`")
        lines.append("")
        report.write_text("\n".join(lines), encoding="utf-8")  # 중간 저장
        time.sleep(PACE)

    lines.insert(1, f"\n**요약: {len(items)}문항 중 점검 필요(\U0001f534) {flagged}건**\n")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n완료 — 리포트: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
