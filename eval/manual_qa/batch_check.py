#!/usr/bin/env python3
"""시험 질문 파일을 데모 서버에 일괄 실행하고 점검 리포트를 만든다.

사용:
  python batch_check.py ~/Downloads/시험질문-연성-세제계산-100.txt
  python batch_check.py <파일> -n 20          # 앞 20문항만
  python batch_check.py <파일> --start 51     # 51번부터

주의: HCX 한도(계정 공유 분당 60요청/6만 토큰) 때문에 문항 간 5초 간격.
100문항 ≈ 20~25분, 비용 ≈ 500원. 셋이 동시에 돌리지 말고 순서대로.
리포트는 같은 폴더에 <파일명>-리포트.md 로 저장된다.
"""
import re
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8090"
PACE = 5.0


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


def main() -> int:
    args = sys.argv[1:]
    path = Path(args[0]).expanduser()
    n = int(args[args.index("-n") + 1]) if "-n" in args else None
    start = int(args[args.index("--start") + 1]) if "--start" in args else 1
    items = load_questions(path)[start - 1:][:n]
    report = path.with_name(path.stem + "-리포트.md")

    lines = [f"# 점검 리포트 — {path.name} ({len(items)}문항)\n"]
    flagged = 0
    for i, (section, q) in enumerate(items, start):
        t0 = time.time()
        try:
            r = requests.get(f"{BASE}/answer",
                             params={"question_id": f"QA-{i}", "question": q},
                             timeout=180)
            d = r.json()
        except Exception as e:
            print(f"[{i}] 오류 {type(e).__name__}: {q[:40]}", flush=True)
            lines.append(f"## {i}. {q}\n- ⚠️ 요청 오류: {type(e).__name__}\n")
            time.sleep(20)
            continue
        dt = time.time() - t0
        verify = [l for l in d["think_trace"].split("\n")
                  if l.startswith(("[검증", "[라우팅", "[전제교정", "[가드", "[가정"))]
        notice = "※" in d["answer"]
        bad = notice or any("미확인" in v or "미지지 " in v and "0건" not in v for v in verify)
        if bad:
            flagged += 1
        mark = "🔴" if bad else "🟢"
        print(f"[{i}/{start + len(items) - 1}] {mark} {dt:4.1f}s  {q[:44]}", flush=True)
        lines.append(f"## {i}. {mark} {q}")
        lines.append(f"_{section} · {dt:.1f}s · HTTP {r.status_code}_")
        lines.append("")
        lines.append("> " + d["answer"][:400].replace("\n", "\n> "))
        lines.append("")
        for v in verify:
            lines.append(f"- `{v[:140]}`")
        lines.append("")
        report.write_text("\n".join(lines), encoding="utf-8")  # 중간 저장
        time.sleep(PACE)

    lines.insert(1, f"\n**요약: {len(items)}문항 중 점검 필요(🔴) {flagged}건**\n")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n완료 — 리포트: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
