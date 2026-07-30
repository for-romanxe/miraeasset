"""파서 산출물(funds.json, docs)을 로딩한다. 모든 모듈이 여기서 데이터를 얻는다."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNDS_PATH = ROOT / "parser" / "out" / "funds.json"
DOCS_DIR = ROOT / "parser" / "out" / "docs"
DOCS_CATALOG_PATH = ROOT / "parser" / "out" / "docs.json"

SECTION = re.compile(r"\n## \[([^\]]+)\]\n")


@lru_cache(maxsize=1)
def load_funds() -> list[dict]:
    return json.loads(FUNDS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_docs_catalog() -> dict[str, dict]:
    rows = json.loads(DOCS_CATALOG_PATH.read_text(encoding="utf-8"))
    return {r["doc_id"]: r for r in rows}


@lru_cache(maxsize=1)
def load_doc_chunks() -> list[dict]:
    """docs/*.md를 근거 인용 단위(청크)로 자른다.

    1차 분할은 페이지·슬라이드·시트 마커, 마커 단위가 너무 길면 문단으로 2차 분할.
    청크마다 출처 라벨(doc_id·제목·마커)을 유지해 답변의 근거 표시에 그대로 쓴다.
    """
    catalog = load_docs_catalog()
    chunks = []
    for md in sorted(DOCS_DIR.glob("doc*.md"),
                     key=lambda p: int(re.search(r"\d+", p.stem).group())):
        doc_id = md.stem
        title = (catalog.get(doc_id) or {}).get("title") or doc_id
        topic = (catalog.get(doc_id) or {}).get("topic", "")
        body = md.read_text(encoding="utf-8")
        parts = SECTION.split(body)
        # parts = [머리말, 마커1, 본문1, 마커2, 본문2, ...]
        for i in range(1, len(parts), 2):
            marker, text = parts[i], parts[i + 1].strip()
            for piece in _split_long(text):
                chunks.append({
                    "doc_id": doc_id, "title": title, "topic": topic,
                    "marker": marker, "text": piece,
                    "source": f"{doc_id}({title}) {marker}",
                })
    return chunks


def _split_long(text: str, limit: int = 900) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []
    out, buf = [], ""
    for para in text.split("\n\n"):
        # 표(마크다운)는 빈 줄이 없어 문단 하나가 수만 자가 된다.
        # 문단 자체가 한도를 넘으면 줄 단위로 다시 쪼갠다 (표는 행 묶음이 된다).
        pieces = [para]
        if len(para) > limit:
            pieces, line_buf = [], ""
            for line in para.split("\n"):
                if line_buf and len(line_buf) + len(line) > limit:
                    pieces.append(line_buf)
                    line_buf = ""
                line_buf += line + "\n"
            if line_buf.strip():
                pieces.append(line_buf)
        for piece in pieces:
            if buf and len(buf) + len(piece) > limit:
                out.append(buf.strip())
                buf = ""
            buf += piece + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out
