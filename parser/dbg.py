import pdfplumber, re, sys
from parse_prospectus import BASE, find_summary_page, pdftotext, CLASS_CODE, to_num
isin=sys.argv[1]; p=BASE/isin/f'R2_{isin}.pdf'
pages=pdftotext(p); sp=find_summary_page(pages)
print('summary page idx', sp)
with pdfplumber.open(str(p)) as pdf:
    for off in (0,1):
        if sp+off>=len(pdf.pages): break
        for ti,tbl in enumerate(pdf.pages[sp+off].extract_tables()):
            tbl=[[(c or '').strip() for c in r] for r in tbl]
            hit=[ri for ri,r in enumerate(tbl) if any(CLASS_CODE.search(re.sub(r'\s+','',c)) for c in r if c) and sum(1 for c in r if to_num(c) is not None)>=2]
            print(f'-- p{sp+off} t{ti} rows={len(tbl)} classrows={hit}')
            if hit or ti<3:
                for ri,r in enumerate(tbl[:14]):
                    print(f'   {"*" if ri in hit else " "}{ri}', [c.replace("\n","·")[:20] for c in r])
