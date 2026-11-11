"""
Build the Plan Yukta pilot Excel workbook.

Input sheets (yellow headers) take the user's data. Grey "(calc)" columns and
the Summary sheet are live Excel formulas, so the workbook works on its own.
The web app reads the same workbook and adds what formulas cannot do well:
OSAT de-duplication with file history, ambiguous part-name resolution and
lot lead times.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT = 'Arial'
INPUT_FILL = PatternFill('solid', fgColor='FFF2CC')   # yellow: user fills these
CALC_FILL = PatternFill('solid', fgColor='E7E6E6')    # grey: formulas, do not edit
HEAD_FILL = PatternFill('solid', fgColor='1F3A5F')
EXAMPLE_FONT = Font(name=FONT, size=10, italic=True, color='7F7F7F')
THIN = Side(style='thin', color='BFBFBF')
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MAX_PRODUCTS = 20
OPS = [('SORT', 'Sort (CP) wafers'), ('BUMP', 'Bump wafers'), ('ASSEMBLY', 'Assembly dies'),
       ('TESTING', 'Testing (FT) dies'), ('PACKING', 'Packing dies')]


def _font(**kw):
    base = dict(name=FONT, size=10)
    base.update(kw)
    return Font(**base)


def _header(ws, row, headers, calc_from=None, widths=None):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        is_calc = calc_from is not None and i >= calc_from
        c.font = _font(bold=True, color='000000' if not is_calc else '404040')
        c.fill = CALC_FILL if is_calc else INPUT_FILL
        c.border = BOX
        c.alignment = Alignment(wrap_text=True, vertical='center')
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 30


def _write_rows(ws, start_row, rows, date_cols=(), example=False):
    for r_off, values in enumerate(rows):
        for c, v in enumerate(values, start=1):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            cell = ws.cell(row=start_row + r_off, column=c, value=v)
            cell.font = EXAMPLE_FONT if example else _font(color='0000FF')
            if c in date_cols:
                cell.number_format = 'yyyy-mm-dd hh:mm' if c == 1 and ws.title == 'OSAT_WIP' else 'yyyy-mm-dd'


def _fill_formulas(ws, first, last, formulas: dict, fmt: dict | None = None):
    """formulas: {column_letter: template with {r} for the row number}."""
    for r in range(first, last + 1):
        for col, f in formulas.items():
            cell = ws[f'{col}{r}']
            cell.value = f.format(r=r)
            cell.font = _font()
            if fmt and col in fmt:
                cell.number_format = fmt[col]


def build_workbook(data: dict | None, path: str, formula_rows: int | None = None):
    """data=None writes the blank template with one example row per sheet."""
    example = data is None
    wb = Workbook()

    # ---------------------------------------------------------------- README
    ws = wb.active
    ws.title = 'README'
    ws.column_dimensions['A'].width = 110
    lines = [
        ('Plan Yukta pilot workbook', _font(size=16, bold=True, color='1F3A5F')),
        ('Supply-chain visibility for fabless semiconductor products: fab WIP, fab shipments, OSAT WIP by operation, E&O and a gross-die capacity check.', _font()),
        ('', None),
        ('How to use it', _font(size=12, bold=True)),
        ('1. Settings: set the as-of date and thresholds (yellow cells).', _font()),
        ('2. Products: one row per master product, with gross die per wafer (GDW).', _font()),
        ('3. Name_Map: every name your fab and OSAT use for each product. SOURCE is FAB or OSAT. One OSAT name may map to several products (e.g. a bare family name); the web app resolves it through fab lot numbers.', _font()),
        ('4. Fab_WIP, Fab_Shipments, OSAT_WIP: paste your reports under the headers. Common vendor headings such as "Lot ID", "Customer Product" or "Shipped Quantity" are accepted by the web app.', _font()),
        ('5. OSAT_WIP holds one or more daily snapshots stacked together, marked by SNAPSHOT_DATE. More history gives better de-duplication and lead times.', _font()),
        ('6. Summary recalculates in Excel. For de-duplicated OSAT figures, resolved part names and lot lead times, upload this file to the Plan Yukta web app.', _font()),
        ('', None),
        ('Cell colours', _font(size=12, bold=True)),
        ('Yellow header = input column you fill in. Grey header = formula column, do not edit. Blue text = your data. Grey italic row = example to overwrite or delete.', _font()),
        (f'Formula columns are pre-filled for {formula_rows or 5000} rows per sheet. If you paste more, copy the last formula row down.', _font()),
        ('', None),
        ('Excel versus the web app', _font(size=12, bold=True)),
        ('Excel Summary: OSAT quantities from the latest snapshot as reported, ambiguous OSAT names shown as AMBIGUOUS.', _font()),
        ('Web app: removes duplicate wafer rows the OSAT report double counts (transfer rows, finished rows, stale Sort rows), using snapshot history, and lists every row it removed with the reason.', _font()),
        ('', None),
        ('Your data stays yours: the web app processes the upload in memory and does not store it.', _font(italic=True)),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        if font:
            c.font = font
        c.alignment = Alignment(wrap_text=True)

    # ----------------------------------------------------------------- Guide
    ws = wb.create_sheet('Guide')
    ws.column_dimensions['A'].width = 34
    ws.column_dimensions['B'].width = 90
    ws['A1'] = 'What Plan Yukta does for you'
    ws['A1'].font = _font(size=16, bold=True, color='1F3A5F')
    guide = [
        ('Question', 'Where you see the answer'),
        ('Where is my material right now?', 'Summary: fab WIP wafers, then Sort and Bump wafers, then Assembly, Testing and Packing dies, one row per product.'),
        ('Which foundry lots will be late?', 'Summary "Late fab lots"; the lots are in Fab_WIP where "Slip days (calc)" is above 0.'),
        ('Is anything ageing or downgraded?', 'Summary "Excess & obsolete"; the rows are in OSAT_WIP where "E&O (calc)" = 1.'),
        ('Do the numbers add up?', 'Summary "Capacity check": active WIP in dies against wafers shipped x gross die per wafer.'),
        ('Can I trust the OSAT numbers?', 'Upload this workbook to the web app: it removes rows the OSAT report counts twice and lists each one with the reason.'),
        ('How long do my lots take?', 'Web app "Lot lead time": process and wait days per stage for every mother lot.'),
    ]
    for r, (q, a) in enumerate(guide, start=3):
        qa = ws.cell(row=r, column=1, value=q); ab = ws.cell(row=r, column=2, value=a)
        bold = r == 3
        for c in (qa, ab):
            c.font = _font(bold=bold, color='FFFFFF' if bold else '000000')
            c.alignment = Alignment(wrap_text=True, vertical='top')
            c.border = BOX
            if bold:
                c.fill = HEAD_FILL
    start = 3 + len(guide) + 1
    ws.cell(row=start, column=1, value='Things to try in this workbook').font = _font(size=12, bold=True)
    tries = [
        ('Settings → Capacity tolerance', 'Raise it from 1.05 to 1.60 and watch the Summary capacity column. A loose tolerance can hide a real missing shipment.'),
        ('Settings → E&O bin baseline', 'Change BIN1 to BIN3. Downgraded bins stop counting as E&O; only aged stock remains.'),
        ('Settings → As-of date + E&O age', 'Move the date a year ahead and set the age to 6 months to see how today\'s WIP turns into ageing risk.'),
        ('Fab_Shipments', 'Delete a shipment row. Wafers shipped falls and the capacity check may flag the product.'),
        ('Products', 'Change a gross die per wafer value and see the capacity figures move.'),
        ('Then', 'Upload the workbook to the web app to compare the de-duplicated figures and the removed-row audit.'),
    ]
    for r, (where, what) in enumerate(tries, start=start + 1):
        ws.cell(row=r, column=1, value=where).font = _font(bold=True)
        ws.cell(row=r, column=2, value=what).font = _font()
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical='top')
    ws.cell(row=start + len(tries) + 2, column=1,
            value='Plan Yukta reconciles what suppliers report today. It does not forecast demand or plan wafer starts.').font = _font(italic=True, color='595959')

    # -------------------------------------------------------------- Settings
    ws = wb.create_sheet('Settings')
    _header(ws, 1, ['Setting', 'Value', 'Notes'], widths=[34, 16, 80])
    ws['C1'].fill = INPUT_FILL
    as_of = data['as_of'] if data else None
    rows = [
        ('As-of date', as_of if as_of else '=TODAY()', 'Date the plan is run for. E&O ages and lead times are measured to this date.'),
        ('E&O age threshold (months)', 24, 'Stock with a YYWW date code older than this is excess/obsolete. Months count as 30 days (dashboard rule).'),
        ('E&O bin baseline', 'BIN1', 'Rows binned above this bin (e.g. BIN2, BIN3) count as E&O.'),
        ('Capacity tolerance', 1.05, 'Allowed headroom when comparing active WIP with shipped wafers x GDW.'),
        ('E&O cutoff date (calc)', '=B2-30*B3', 'Formula: as-of date minus months x 30.'),
        ('Baseline bin number (calc)', '=IFERROR(VALUE(SUBSTITUTE(UPPER(B4),"BIN","")),1)', 'Formula: the number in the baseline bin.'),
    ]
    for i, (k, v, note) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=k).font = _font(bold=True)
        cell = ws.cell(row=i, column=2, value=v)
        calc = '(calc)' in k
        cell.font = _font(color='000000' if calc or str(v).startswith('=') else '0000FF')
        cell.fill = CALC_FILL if calc else INPUT_FILL
        cell.border = BOX
        ws.cell(row=i, column=3, value=note).font = _font(color='595959')
    ws['B2'].number_format = 'yyyy-mm-dd'
    ws['B6'].number_format = 'yyyy-mm-dd'
    ws['B5'].number_format = '0.00'

    # -------------------------------------------------------------- Products
    ws = wb.create_sheet('Products')
    _header(ws, 1, ['MASTER_PRODUCT', 'GROSS_DIE_PER_WAFER', 'NOTES'], widths=[22, 22, 50])
    ws['A1'].comment = Comment('One row per product you plan. Up to 20 products appear on Summary.', 'Plan Yukta')
    ws['B1'].comment = Comment('Gross die per wafer. Used to convert wafers to die for the capacity check.', 'Plan Yukta')
    if data:
        prods = data['product_map'].drop_duplicates('MASTER_PRODUCT')
        _write_rows(ws, 2, [(p, g, None) for p, g in zip(prods['MASTER_PRODUCT'], prods['GROSS_DIE_PER_WAFER'])])
    else:
        _write_rows(ws, 2, [('NOVA A0', 8500, 'Example row: overwrite with your product')], example=True)

    # -------------------------------------------------------------- Name_Map
    ws = wb.create_sheet('Name_Map')
    _header(ws, 1, ['NAME', 'SOURCE', 'MASTER_PRODUCT', 'KEY (calc)'], calc_from=4, widths=[24, 10, 22, 26])
    dv = DataValidation(type='list', formula1='"FAB,OSAT"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add('B2:B500')
    if data:
        pm = data['product_map']
        name_rows = []
        for _, r in pm.iterrows():
            if pd.notna(r['FAB_PRODUCT']):
                name_rows.append((r['FAB_PRODUCT'], 'FAB', r['MASTER_PRODUCT']))
            if pd.notna(r['OSAT_PARTNAME']):
                name_rows.append((r['OSAT_PARTNAME'], 'OSAT', r['MASTER_PRODUCT']))
        name_rows = list(dict.fromkeys(name_rows))
        _write_rows(ws, 2, name_rows)
    else:
        _write_rows(ws, 2, [('NV1000A0', 'FAB', 'NOVA A0'), ('NV1000A0-P1', 'OSAT', 'NOVA A0')], example=True)
    _fill_formulas(ws, 2, 500, {'D': '=IF(A{r}="","",UPPER(TRIM(B{r}))&"|"&UPPER(TRIM(A{r})))'})
    for r in range(2, 501):
        ws[f'D{r}'].fill = CALC_FILL

    def lookup(name_cell, source):
        key = f'"{source}|"&UPPER(TRIM({name_cell}))'
        return (f'IF(COUNTIF(Name_Map!$D:$D,{key})=0,"UNMAPPED",'
                f'IF(COUNTIF(Name_Map!$D:$D,{key})>1,"AMBIGUOUS",'
                f'INDEX(Name_Map!$C:$C,MATCH({key},Name_Map!$D:$D,0))))')

    # --------------------------------------------------------------- Fab_WIP
    ws = wb.create_sheet('Fab_WIP')
    _header(ws, 1, ['Fab Product', 'Fab Lot ID', 'Current Stage', 'Current Qty', 'Wafer Start Date',
                    'Committed Date', 'Projected Out Date', 'MASTER_PRODUCT (calc)', 'WIP wafers (calc)',
                    'Slip days (calc)'], calc_from=8, widths=[16, 14, 15, 12, 15, 15, 17, 22, 14, 13])
    ws['C1'].comment = Comment('Rows with stage SHIPPED are excluded from fab WIP (they are counted in Fab_Shipments).', 'Plan Yukta')
    ws['D1'].comment = Comment('Wafers currently in the lot.', 'Plan Yukta')
    cols = ['Fab Product', 'Fab Lot ID', 'Current Stage', 'Current Qty', 'Wafer Start Date', 'Committed Date', 'Projected Out Date']
    if data:
        n_fab = len(data['fab_wip'])
        _write_rows(ws, 2, data['fab_wip'][cols].itertuples(index=False), date_cols=(5, 6, 7))
    else:
        n_fab = 1
        _write_rows(ws, 2, [('NV1000A0', 'XN0001.1', 'METAL3', 12, date(2026, 9, 1), date(2026, 12, 1), date(2026, 12, 4))],
                    date_cols=(5, 6, 7), example=True)
    last = max(formula_rows or 5000, n_fab + 1)
    _fill_formulas(ws, 2, last, {
        'H': '=IF(A{r}="","",' + lookup('A{r}', 'FAB') + ')',
        'I': '=IF(A{r}="","",IF(UPPER(TRIM(C{r}))="SHIPPED",0,N(D{r})))',
        'J': '=IF(OR(A{r}="",F{r}="",G{r}=""),"",IF(UPPER(TRIM(C{r}))="SHIPPED","",G{r}-F{r}))',
    })

    # --------------------------------------------------------- Fab_Shipments
    ws = wb.create_sheet('Fab_Shipments')
    _header(ws, 1, ['Ship Date', 'Fab Product', 'Fab Lot ID', 'UM', 'Ship Qty', 'MASTER_PRODUCT (calc)',
                    'Wafers shipped (calc)'], calc_from=6, widths=[13, 16, 14, 8, 10, 22, 16])
    ws['D1'].comment = Comment('Unit of measure. Only WF (wafer) lines count as shipped wafers.', 'Plan Yukta')
    if data:
        n_ship = len(data['fab_ship'])
        _write_rows(ws, 2, data['fab_ship'][['Ship Date', 'Fab Product', 'Fab Lot ID', 'UM', 'Ship Qty']]
                    .itertuples(index=False), date_cols=(1,))
    else:
        n_ship = 1
        _write_rows(ws, 2, [(date(2026, 10, 20), 'NV1000A0', 'XN0001.1', 'WF', 12)], date_cols=(1,), example=True)
    last = max(formula_rows or 5000, n_ship + 1)
    _fill_formulas(ws, 2, last, {
        'F': '=IF(B{r}="","",' + lookup('B{r}', 'FAB') + ')',
        'G': '=IF(B{r}="","",IF(UPPER(TRIM(D{r}))="WF",N(E{r}),0))',
    })

    # -------------------------------------------------------------- OSAT_WIP
    ws = wb.create_sheet('OSAT_WIP')
    osat_cols = ['SNAPSHOT_DATE', 'MAIN', 'OPER', 'STATE', 'PARTNAME', 'C_LOT_NUMBER', 'WAFER_QTY',
                 'DIE_QTY', 'WAFER_ID', 'DATECODE', 'LOCATION']
    _header(ws, 1, osat_cols + ['LATEST (calc)', 'OPERATION (calc)', 'MASTER_PRODUCT (calc)', 'QTY (calc)',
                                'DATECODE WEEK (calc)', 'BIN NO. (calc)', 'E&O (calc)'],
            calc_from=12, widths=[17, 7, 7, 10, 16, 16, 10, 10, 12, 10, 10, 9, 13, 21, 11, 13, 9, 8])
    notes = {
        'A1': 'Date/time of the OSAT report. Stack several daily reports; the latest one is the current WIP.',
        'B1': 'Main operation: CP (sort), BUMP, ASSY, FT.',
        'C1': 'Sub-operation. FT with OPER = IP is Packing.',
        'D1': 'WAIT / PROCESS / HOLD / TRANSFER / FINISH.',
        'F1': 'Customer lot. The first 6 characters are the mother lot.',
        'I1': 'Wafer IDs as the OSAT reports them, e.g. 1,2,3.',
        'J1': 'YYWW date code, e.g. 2541.',
        'K1': 'Bin / location, e.g. BIN1, GOOD, BIN3. BIN1 or GOOD on FT counts as Packing.',
    }
    for cell, text in notes.items():
        ws[cell].comment = Comment(text, 'Plan Yukta')
    if data:
        n_osat = len(data['osat_wip'])
        _write_rows(ws, 2, data['osat_wip'][osat_cols].itertuples(index=False), date_cols=(1,))
    else:
        n_osat = 1
        _write_rows(ws, 2, [(pd.Timestamp('2026-11-02 08:00'), 'ASSY', 'DA', 'PROCESS', 'NV1000A0-P1',
                             'XN0001.01.EA', 6, 48450, '1,2,3,4,5,6', '2543', None)], date_cols=(1,), example=True)
    last = max(formula_rows or 5000, n_osat + 1)
    _fill_formulas(ws, 2, last, {
        'L': '=IF(A{r}="","",IF(A{r}=MAX($A:$A),1,0))',
        'M': ('=IF(B{r}="","",IF(UPPER(TRIM(B{r}))="CP","SORT",IF(UPPER(TRIM(B{r}))="BUMP","BUMP",'
              'IF(UPPER(TRIM(B{r}))="ASSY","ASSEMBLY",IF(UPPER(TRIM(B{r}))="FT",'
              'IF(OR(UPPER(TRIM(C{r}))="IP",UPPER(SUBSTITUTE(K{r}," ",""))="BIN1",'
              'UPPER(SUBSTITUTE(K{r}," ",""))="GOOD"),"PACKING","TESTING"),"OTHER")))))'),
        'N': '=IF(E{r}="","",' + lookup('E{r}', 'OSAT') + ')',
        'O': '=IF(M{r}="","",IF(OR(M{r}="SORT",M{r}="BUMP"),N(G{r}),N(H{r})))',
        'P': ('=IF(LEN(TRIM(J{r}))<4,"",IFERROR(DATE(2000+VALUE(LEFT(RIGHT(TRIM(J{r}),4),2)),1,4)'
              '-WEEKDAY(DATE(2000+VALUE(LEFT(RIGHT(TRIM(J{r}),4),2)),1,4),3)+7*(VALUE(RIGHT(TRIM(J{r}),2))-1),""))'),
        'Q': '=IF(LEFT(UPPER(TRIM(K{r})),3)="BIN",IFERROR(VALUE(MID(TRIM(K{r}),4,5)),""),"")',
        'R': ('=IF(M{r}="","",IF(OR(AND(P{r}<>"",N(P{r})<Settings!$B$6),'
              'AND(Q{r}<>"",N(Q{r})>Settings!$B$7)),1,0))'),
    }, fmt={'P': 'yyyy-mm-dd'})

    # --------------------------------------------------------------- Summary
    ws = wb.create_sheet('Summary', 1)
    ws['A1'] = 'Plan Yukta summary'
    ws['A1'].font = _font(size=14, bold=True, color='1F3A5F')
    ws['A2'] = '="As of "&TEXT(Settings!B2,"yyyy-mm-dd")&"   |   latest OSAT snapshot "&TEXT(MAX(OSAT_WIP!A:A),"yyyy-mm-dd hh:mm")'
    ws['A2'].font = _font(color='595959')
    heads = ['Product', 'GDW', 'Fab WIP wafers', 'Late fab lots', 'Wafers shipped from fab'] + \
            [label for _, label in OPS] + ['Active die equivalent', 'Capacity (dies)', 'Capacity check']
    for i, h in enumerate(heads, start=1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = _font(bold=True, color='FFFFFF')
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center')
        c.border = BOX
    ws.row_dimensions[4].height = 42
    widths = [16, 9, 11, 9, 12, 11, 10, 12, 12, 11, 14, 14, 26]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    first = 5
    for i in range(MAX_PRODUCTS):
        r = first + i
        p = f'A{r}'
        osat = lambda op: (f'=IF({p}="","",SUMIFS(OSAT_WIP!$O:$O,OSAT_WIP!$N:$N,{p},'
                           f'OSAT_WIP!$M:$M,"{op}",OSAT_WIP!$L:$L,1))')
        f = {
            'A': f'=IF(Products!A{i + 2}="","",Products!A{i + 2})',
            'B': f'=IF({p}="","",IFERROR(INDEX(Products!$B:$B,MATCH({p},Products!$A:$A,0)),""))',
            'C': f'=IF({p}="","",SUMIFS(Fab_WIP!$I:$I,Fab_WIP!$H:$H,{p}))',
            'D': f'=IF({p}="","",COUNTIFS(Fab_WIP!$H:$H,{p},Fab_WIP!$J:$J,">0"))',
            'E': f'=IF({p}="","",SUMIFS(Fab_Shipments!$G:$G,Fab_Shipments!$F:$F,{p}))',
            'F': osat('SORT'), 'G': osat('BUMP'), 'H': osat('ASSEMBLY'), 'I': osat('TESTING'), 'J': osat('PACKING'),
            'K': f'=IF(OR({p}="",N(B{r})=0),"",(F{r}+G{r})*B{r}+H{r}+I{r}+J{r})',
            'L': f'=IF(OR({p}="",N(B{r})=0),"",E{r}*B{r}*Settings!$B$5)',
            'M': (f'=IF({p}="","",IF(N(B{r})=0,"No GDW on Products",IF(E{r}=0,"No fab shipments",'
                  f'IF(K{r}>L{r},"OVER CAPACITY","OK"))))'),
        }
        for col, formula in f.items():
            cell = ws[f'{col}{r}']
            cell.value = formula
            cell.font = _font()
            cell.border = BOX
            if col in 'CDEFGHIJKL':
                cell.number_format = '#,##0;(#,##0);-'
            if col == 'B':
                cell.number_format = '#,##0'
    last_p = first + MAX_PRODUCTS - 1

    # Rows the formulas could not map
    r = last_p + 1
    for label in ('AMBIGUOUS', 'UNMAPPED'):
        ws[f'A{r}'] = label
        ws[f'A{r}'].font = _font(italic=True, color='C00000')
        for col, op in zip('FGHIJ', [o for o, _ in OPS]):
            ws[f'{col}{r}'] = f'=SUMIFS(OSAT_WIP!$O:$O,OSAT_WIP!$N:$N,"{label}",OSAT_WIP!$M:$M,"{op}",OSAT_WIP!$L:$L,1)'
            ws[f'{col}{r}'].number_format = '#,##0;(#,##0);-'
            ws[f'{col}{r}'].font = _font(italic=True)
        r += 1
    tot = r
    ws[f'A{tot}'] = 'Total'
    ws[f'A{tot}'].font = _font(bold=True)
    for col in 'CDEFGHIJ':
        ws[f'{col}{tot}'] = f'=SUM({col}{first}:{col}{tot - 1})'
        ws[f'{col}{tot}'].font = _font(bold=True)
        ws[f'{col}{tot}'].number_format = '#,##0;(#,##0);-'
        ws[f'{col}{tot}'].border = Border(top=Side(style='medium'))

    note = tot + 2
    ws[f'A{note}'] = ('OSAT columns use the latest snapshot as reported. Ambiguous part names and wafers the OSAT '
                      'report lists twice are not corrected here; upload this workbook to the web app for '
                      'de-duplicated quantities and the removed-row audit.')
    ws[f'A{note}'].font = _font(italic=True, color='595959')
    ws[f'A{note}'].alignment = Alignment(wrap_text=True, vertical='top')
    ws.merge_cells(f'A{note}:M{note}')
    ws.row_dimensions[note].height = 30

    eo = note + 2
    ws[f'A{eo}'] = 'Excess & obsolete in the latest snapshot'
    ws[f'A{eo}'].font = _font(size=12, bold=True, color='1F3A5F')
    for i, h in enumerate(['Operation', 'Rows', 'Quantity', 'Unit'], start=1):
        c = ws.cell(row=eo + 1, column=i, value=h)
        c.font = _font(bold=True, color='FFFFFF')
        c.fill = HEAD_FILL
    for j, (op, label) in enumerate(OPS):
        r = eo + 2 + j
        ws[f'A{r}'] = label.rsplit(' ', 1)[0]
        ws[f'B{r}'] = f'=COUNTIFS(OSAT_WIP!$L:$L,1,OSAT_WIP!$M:$M,"{op}",OSAT_WIP!$R:$R,1)'
        ws[f'C{r}'] = f'=SUMIFS(OSAT_WIP!$O:$O,OSAT_WIP!$L:$L,1,OSAT_WIP!$M:$M,"{op}",OSAT_WIP!$R:$R,1)'
        ws[f'D{r}'] = label.rsplit(' ', 1)[1]
        ws[f'C{r}'].number_format = '#,##0;(#,##0);-'
        for col in 'ABCD':
            ws[f'{col}{r}'].font = _font()
    ws.freeze_panes = 'B5'

    wb.save(path)
    return path
