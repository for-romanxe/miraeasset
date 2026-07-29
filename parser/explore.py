import pdfplumber, sys, re, glob, os
BASE='/Users/for_romanxe/Downloads/data/2.연금/투자설명서'
for isin in sys.argv[1:]:
    p=f'{BASE}/{isin}/R2_{isin}.pdf'
    with pdfplumber.open(p) as pdf:
        # 요약정보 페이지 찾기
        hit=None
        for i,pg in enumerate(pdf.pages[:15]):
            t=pg.extract_text() or ''
            if re.search(r'[<\[]?요약정보[>\]]?', t) and '분류' in t:
                hit=i; break
        print(f'\n########## {isin}  요약정보 page={hit} (총 {len(pdf.pages)}p)')
        if hit is None: continue
        pg=pdf.pages[hit]
        for ti,tbl in enumerate(pg.extract_tables()):
            print(f'  --- table[{ti}] {len(tbl)}행 ---')
            for row in tbl[:12]:
                cells=[(c or '').replace('\n','·')[:22] for c in row]
                print('   ', cells)
