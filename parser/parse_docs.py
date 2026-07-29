#!/usr/bin/env python3
"""안내문서 58건(docs_renamed)을 검색 가능한 마크다운 + 카탈로그로 변환한다.

형식별 전략:
  - PDF: pdftotext -layout 페이지별 추출. 텍스트가 빈약한 페이지(이미지 스캔)는
    pdftoppm으로 렌더링해 macOS Vision OCR(ko-KR)로 읽는다. 17건가량이 이미지형.
  - DOCX: python-docx로 문단·표를 문서 순서대로 추출. 표는 마크다운 표로.
  - PPTX: python-pptx 없이 zip 내 slideN.xml에서 <a:t> 텍스트를 슬라이드 순서로.
  - XLSX: openpyxl로 시트별 마크다운 표. (doc29는 디폴트옵션 FAQ 100문항 정형표)

산출물:
  out/docs/docN.md   본문. 근거 표시용 페이지/슬라이드/시트 마커 포함
  out/docs.json      카탈로그(제목·형식·분량·추출방법·미리보기)

사용:
  python parse_docs.py            # 전체
  python parse_docs.py doc11 doc1 # 특정 문서만
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "docs_renamed"
OUT = Path(__file__).resolve().parent / "out" / "docs"
CATALOG = Path(__file__).resolve().parent / "out" / "docs.json"

OCR_MIN_CHARS = 300  # 페이지 텍스트가 이보다 짧으면 이미지 섞임으로 보고 OCR 병행
OCR_DPI = 200


# ---------------------------------------------------------------- OCR (Vision)

_ocr_req = None


def ocr_image(png_path: str) -> str:
    """macOS Vision 프레임워크로 한국어 OCR. 라인 단위 텍스트를 돌려준다."""
    global _ocr_req
    import Quartz
    import Vision
    from Foundation import NSURL

    if _ocr_req is None:
        _ocr_req = Vision.VNRecognizeTextRequest.alloc().init()
        _ocr_req.setRecognitionLanguages_(["ko-KR", "en-US"])
        _ocr_req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

    url = NSURL.fileURLWithPath_(png_path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, _ = handler.performRequests_error_([_ocr_req], None)
    if not ok:
        return ""
    return "\n".join(o.topCandidates_(1)[0].string() for o in _ocr_req.results())


# ---------------------------------------------------------------- 형식별 추출

def extract_pdf(path: Path):
    """(섹션 리스트, 추출방법) 반환. 섹션 = (마커, 텍스트)."""
    r = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                       capture_output=True, text=True, check=True)
    pages = r.stdout.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    sections, used_ocr, used_text = [], False, False
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(pages, 1):
            if len(t.strip()) >= OCR_MIN_CHARS:
                sections.append((f"페이지 {i}", t.strip()))
                used_text = True
                continue
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(OCR_DPI), "-f", str(i), "-l", str(i),
                 str(path), f"{td}/pg"],
                capture_output=True, check=True)
            pngs = sorted(Path(td).glob("pg*.png"))
            body = ocr_image(str(pngs[0])) if pngs else ""
            for p in pngs:
                p.unlink()
            # OCR 결과가 원래 있던 부스러기 텍스트보다 짧으면 원본을 쓴다
            if len(body.strip()) < len(t.strip()):
                body = t.strip()
            else:
                used_ocr = True
            sections.append((f"페이지 {i}", body.strip()))
    method = "ocr" if used_ocr and not used_text else ("mixed" if used_ocr else "text")
    return sections, method


def _docx_table_md(tbl) -> str:
    rows = []
    for r in tbl.rows:
        cells = [" ".join(c.text.split()) for c in r.cells]
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) >= 2:
        n = rows[0].count("|") - 1
        rows.insert(1, "|" + "---|" * n)
    return "\n".join(rows)


def extract_docx(path: Path):
    """문단·표를 문서 순서대로. 페이지 개념이 없어 문서 전체가 한 섹션."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    parts = []
    for el in d.element.body:
        if el.tag.endswith("}p"):
            t = Paragraph(el, d).text.strip()
            if t:
                parts.append(t)
        elif el.tag.endswith("}tbl"):
            parts.append(_docx_table_md(Table(el, d)))
    return [("본문", "\n".join(parts))], "text"


def extract_pptx(path: Path):
    z = zipfile.ZipFile(path)
    slides = sorted(
        (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))
    sections = []
    for i, name in enumerate(slides, 1):
        xml = z.read(name).decode("utf-8", errors="ignore")
        texts = [t.strip() for t in re.findall(r"<a:t>([^<]*)</a:t>", xml) if t.strip()]
        sections.append((f"슬라이드 {i}", "\n".join(texts)))
    return sections, "text"


def extract_xlsx(path: Path):
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    sections = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(max_row=min(ws.max_row, 500), values_only=True):
            cells = ["" if c is None else " ".join(str(c).split()) for c in r]
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        if len(rows) >= 2:
            n = rows[0].count("|") - 1
            rows.insert(1, "|" + "---|" * n)
        sections.append((f"시트: {ws.title}", "\n".join(rows)))
    return sections, "text"


# ---------------------------------------------------------------- 제목·엔트리

NOISE_TITLE = re.compile(r"^[\d\s.•·※#*\-=~□■☑①-⑳()\[\]]+$")

# 표지가 로고·화면캡처뿐인 그래픽 문서는 첫 줄 휴리스틱으로 제목을 못 잡는다.
# 본문을 읽고 확인한 제목으로 보정한다.
TITLE_OVERRIDES = {
    "doc27": "공제회 퇴직연금 홈페이지·모바일 이용 Q&A",
    "doc28": "홈페이지·모바일 운용방법변경 Q&A",
    "doc30": "디폴트옵션 자주 묻는 질문 TOP7",
    "doc31": "디폴트옵션 안내 (대화형 홍보물)",
    "doc32": "디폴트옵션 FAQ (가입자 안내용)",
    "doc35": "실물이전제도 안내",
    "doc37": "연금 인출 가이드",
}

# 질의 유형 라우팅용 주제 태그. 제목 기준 키워드 규칙 + 애매한 문서는 수동 지정.
TOPIC_RULES = [
    ("디폴트옵션", r"디폴트옵션"),
    ("세제", r"세액공제|절세|세금|과세|소득세|종합과세|수령한도|수령연차|과세이연|재원확정|퇴직소득"),
    ("업무·절차", r"업무매뉴얼|매뉴얼|업무|지급|입금|청구|증권담보|유상청약|이용 Q&A|운용방법변경|프로세스|체크 포인트"),
    ("상품·운용", r"ETF|ETN|채권|주식|펀드|인프라|MP 구독|실물이전|운용방법"),
    ("제도", r"퇴직연금|퇴직급여|IRP|연금저축|중도인출|규약|압류|지연이자|가입|인출 가이드|연금계좌|개인연금|연금 지급"),
]
TOPIC_OVERRIDES = {
    "doc21": "업무·절차",   # IRP 연금지급 (지급 업무 안내)
    "doc22": "제도",        # 중도인출 사유·요건
    "doc46": "제도", "doc47": "제도", "doc48": "제도",
    "doc49": "제도", "doc50": "제도",  # 중도인출 사유별 안내
}


def guess_topic(doc_id: str, title: str | None) -> str:
    if doc_id in TOPIC_OVERRIDES:
        return TOPIC_OVERRIDES[doc_id]
    for name, pat in TOPIC_RULES:
        if re.search(pat, title or ""):
            return name
    return "기타"


def guess_title(sections) -> str | None:
    """첫 부분에서 제목 후보를 고른다. 로고(MIRAE ASSET 등)·표 괘선을 피해
    한글이 포함된 첫 줄을 우선하고, 없으면 아무 텍스트 줄이나 쓴다."""
    fallback = None
    for _, body in sections[:2]:
        for line in body.split("\n")[:25]:
            t = " ".join(line.replace("|", " ").split())
            if len(t) < 4 or NOISE_TITLE.match(t):
                continue
            if re.search(r"[가-힣]{2,}", t):
                return t[:80]
            if fallback is None and re.search(r"[A-Za-z]{2,}", t):
                fallback = t[:80]
    return fallback


def parse_one(stem: str) -> dict:
    path = next(p for p in BASE.glob(f"{stem}.*") if p.suffix != ".zip")
    ext = path.suffix.lower().lstrip(".")
    sections, method = {
        "pdf": extract_pdf, "docx": extract_docx,
        "pptx": extract_pptx, "xlsx": extract_xlsx,
    }[ext](path)

    title = TITLE_OVERRIDES.get(stem) or guess_title(sections)
    md = [f"# {stem} — {title or path.name}"]
    for marker, body in sections:
        md.append(f"\n## [{marker}]\n")
        md.append(body if body else "(내용 없음)")
    text = "\n".join(md)
    (OUT / f"{stem}.md").write_text(text, encoding="utf-8")

    joined = "\n".join(b for _, b in sections)
    return {
        "doc_id": stem,
        "file": f"docs_renamed/{path.name}",
        "format": ext,
        "title": title,
        "topic": guess_topic(stem, title),
        "sections": len(sections),
        "chars": len(joined),
        "extract_method": method,
        "preview": " ".join(joined.split())[:160],
        "output": f"out/docs/{stem}.md",
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stems = sys.argv[1:] or sorted(
        {p.stem for p in BASE.iterdir() if p.suffix in (".pdf", ".docx", ".pptx", ".xlsx")},
        key=lambda s: int(re.search(r"\d+", s).group()))
    results = []
    for i, stem in enumerate(stems, 1):
        try:
            rec = parse_one(stem)
        except Exception as e:
            rec = {"doc_id": stem, "error": f"{type(e).__name__}: {e}"}
        results.append(rec)
        note = rec.get("error") or f"{rec['format']}/{rec['extract_method']}  {rec['chars']:,}자  {rec['title'] or '제목 미상'}"
        print(f"[{i:2d}/{len(stems)}] {stem:6s} {note}", flush=True)

    # 일부만 재실행한 경우 기존 카탈로그에 병합한다
    if sys.argv[1:] and CATALOG.exists():
        merged = {r["doc_id"]: r for r in json.loads(CATALOG.read_text(encoding="utf-8"))}
        merged.update({r["doc_id"]: r for r in results})
        results = sorted(merged.values(),
                         key=lambda r: int(re.search(r"\d+", r["doc_id"]).group()))

    CATALOG.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {CATALOG} ({len(results)}건), 본문 {OUT}/")


if __name__ == "__main__":
    main()
