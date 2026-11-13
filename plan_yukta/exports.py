"""Downloads: B2B supplier package, simplified RosettaNet-style XML, and the full plan as Excel."""
from __future__ import annotations

import io
from datetime import datetime
from xml.etree import ElementTree as ET
from xml.dom import minidom

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ARIAL = 'Arial'
HEAD = PatternFill('solid', fgColor='1F3A5F')
FROZEN = PatternFill('solid', fgColor='DCE6F2')
SLUSHY = PatternFill('solid', fgColor='FFF2CC')
LIQUID = PatternFill('solid', fgColor='E2EFDA')
COMMIT = PatternFill('solid', fgColor='FFFF00')
GREY = PatternFill('solid', fgColor='F2F2F2')
thin = Side(style='thin', color='BFBFBF')


def f(**k):
    return Font(**{'name': ARIAL, 'size': 10, **k})


def b2b_workbook(R) -> bytes:
    p, B = R['plan'], R['b2b']
    months = p.months
    wb = Workbook()
    ws = wb.active
    ws.title = 'README'
    lines = [
        ('Plan Yukta: monthly B2B package', f(bold=True, size=14)),
        (f'Plan start {months[0]}, horizon {len(months)} months, as of {p.as_of:%d %b %Y}. Generated {datetime.utcnow():%Y-%m-%d %H:%M} UTC.', f()),
        ('', f()),
        ('One sheet per supplier. For every item there are three rows:', f(bold=True)),
        ('REQUEST: what we need, from the plan (do not edit).', f()),
        ('COMMIT (yellow): the supplier enters what they can deliver in each month.', f()),
        ('GAP: COMMIT minus REQUEST. It calculates itself; negative values turn red and need escalation.', f()),
        ('', f()),
        ('Time fences, shown in the header colour of each month:', f(bold=True)),
        (f'Frozen (blue): first {p.s["Frozen months"]} month(s). Firm order: changes only by escalation.', f()),
        (f'Slushy (yellow): next {p.s["Slushy months"]} month(s). Changes within the agreed flex.', f()),
        ('Liquid (green): the rest. Forecast only, for capacity planning.', f()),
        ('', f()),
        ('All products, vendors and quantities in this demo are synthetic.', f(italic=True)),
    ]
    for i, (t, ft) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=t)
        c.font = ft
    ws.column_dimensions['A'].width = 110
    sheets = {'FAB': B['fab']}
    for r in B['osat']:
        sheets.setdefault(r['supplier'], []).append(r)
    for r in B['tester']:
        sheets.setdefault(r['supplier'], []).append(dict(r, item=r['item'], unit='testers'))
    zfill = {'Frozen': FROZEN, 'Slushy': SLUSHY, 'Liquid': LIQUID}
    for name, items in sheets.items():
        sh = wb.create_sheet(name[:31])
        head = ['Product', 'Item', 'Unit', 'Row'] + months
        sh.append(head)
        sh.append(['', '', '', 'Time fence'] + B['zones'])
        for i, h in enumerate(head, start=1):
            c = sh.cell(row=1, column=i)
            c.font = f(bold=True, color='FFFFFF')
            c.fill = HEAD
            c.alignment = Alignment(horizontal='center')
        for j, z in enumerate(B['zones']):
            c = sh.cell(row=2, column=5 + j)
            c.fill = zfill[z]
            c.font = f(bold=True)
            c.alignment = Alignment(horizontal='center')
        sh.cell(row=2, column=4).font = f(bold=True)
        row = 3
        for it in items:
            qty = it['qty'][:len(months)]
            if not any(qty):
                continue
            req_r, com_r, gap_r = row, row + 1, row + 2
            for rr, label in ((req_r, 'REQUEST'), (com_r, 'COMMIT'), (gap_r, 'GAP')):
                sh.cell(row=rr, column=1, value=it['sku']).font = f()
                sh.cell(row=rr, column=2, value=it['item']).font = f()
                sh.cell(row=rr, column=3, value=it['unit']).font = f()
                sh.cell(row=rr, column=4, value=label).font = f(bold=True)
            for j, q in enumerate(qty):
                col = 5 + j
                L = get_column_letter(col)
                c = sh.cell(row=req_r, column=col, value=round(q))
                c.font = f(color='0000FF')
                c.number_format = '#,##0'
                c2 = sh.cell(row=com_r, column=col)
                c2.fill = COMMIT
                c2.number_format = '#,##0'
                c2.font = f(color='0000FF')
                c3 = sh.cell(row=gap_r, column=col, value=f'=IF({L}{com_r}="","",{L}{com_r}-{L}{req_r})')
                c3.font = f()
                c3.number_format = '#,##0;[Red]-#,##0;0'
                c3.fill = GREY
            for col in range(1, 5 + len(months)):
                sh.cell(row=gap_r, column=col).border = Border(bottom=thin)
            row += 3
        last = get_column_letter(4 + len(months))
        if row > 3:
            sh.conditional_formatting.add(f'E3:{last}{row}', CellIsRule(operator='lessThan', formula=['0'], font=Font(name=ARIAL, color='C00000', bold=True)))
        sh.column_dimensions['A'].width = 12
        sh.column_dimensions['B'].width = 26
        sh.column_dimensions['C'].width = 11
        sh.column_dimensions['D'].width = 11
        for j in range(len(months)):
            sh.column_dimensions[get_column_letter(5 + j)].width = 11
        sh.freeze_panes = 'E3'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _xml(root) -> bytes:
    return minidom.parseString(ET.tostring(root, encoding='utf-8')).toprettyxml(indent='  ', encoding='utf-8')


def _header(root, kind, partner):
    h = ET.SubElement(root, 'MessageHeader')
    ET.SubElement(h, 'MessageType').text = kind
    ET.SubElement(h, 'Note').text = 'Simplified RosettaNet-style message for illustration; not a certified PIP schema.'
    ET.SubElement(h, 'Sender').text = 'PLAN-YUKTA-DEMO'
    ET.SubElement(h, 'Receiver').text = partner
    ET.SubElement(h, 'Created').text = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def fab_forecast_xml(R) -> bytes:
    p, B = R['plan'], R['b2b']
    root = ET.Element('ForecastNotification', {'style': 'PIP 4A3-like'})
    _header(root, 'Forecast', 'FAB')
    for it in B['fab']:
        li = ET.SubElement(root, 'ProductForecast', {'product': it['sku'], 'unit': 'wafer'})
        for m, q, z in zip(p.months, it['qty'], B['zones']):
            ET.SubElement(li, 'Period', {'month': m, 'fence': z}).text = str(round(q))
    return _xml(root)


def fab_po_xml(R) -> bytes:
    p = R['plan']
    root = ET.Element('PurchaseOrderRequest', {'style': 'PIP 3A4-like'})
    _header(root, 'PurchaseOrder', 'FAB')
    for i, r in enumerate([r for r in R['fab_po']['rows'] if r['status'] != 'PLANNED'], start=1):
        li = ET.SubElement(root, 'OrderLine', {'line': str(i)})
        for k, v in (('Product', r['sku']), ('WaferStartMonth', r['start_month']), ('Quantity', round(r['wafers'])),
                     ('Lots', r['lots']), ('UnitPriceUSD', f'{r["price"]:.2f}'), ('OrderBy', str(r['cutoff'])), ('Status', r['status'])):
            ET.SubElement(li, k).text = str(v)
    return _xml(root)


def osat_forecast_xml(R) -> bytes:
    p, B = R['plan'], R['b2b']
    root = ET.Element('ForecastNotification', {'style': 'PIP 4A3-like'})
    _header(root, 'Forecast', 'OSAT')
    for it in B['osat']:
        li = ET.SubElement(root, 'ItemForecast', {'supplier': it['supplier'], 'product': it['sku'], 'process': it['item'], 'unit': it['unit']})
        for m, q, z in zip(p.months, it['qty'], B['zones']):
            ET.SubElement(li, 'Period', {'month': m, 'fence': z}).text = str(round(q))
    return _xml(root)


def plan_workbook(R) -> bytes:
    """Every module's main table in one workbook."""
    import pandas as pd
    p = R['plan']
    buf = io.BytesIO()
    sheets = {
        'Complete_Flow': pd.DataFrame(R['flow']['rows']),
        'Testing_Starts': pd.DataFrame(R['testing']['lines']),
        'Tester_Capacity': pd.DataFrame(R['testing']['caps']),
        'Assembly': pd.DataFrame(R['assembly']['rows']),
        'Front_End': pd.DataFrame(R['frontend']['rows']),
        'Fab_Wafers': pd.DataFrame(R['frontend']['fab']),
        'FAB_PO': pd.DataFrame(R['fab_po']['rows']),
        'OSAT_PO': pd.DataFrame(R['osat_po']['rows']),
        'Substrate': pd.DataFrame(R['substrate']['rows']),
        'Std_Cost': pd.DataFrame(R['cost']['std']),
        'Spend': pd.DataFrame(R['cost']['spend']),
        'PnL': pd.DataFrame(R['pnl']['rows']),
        'Alerts': pd.DataFrame(R['home']['alerts']),
        'Data_Checks': pd.DataFrame(R['checks']['items']),
    }
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        pd.DataFrame([('Plan start', p.start), ('Horizon months', p.H), ('As-of date', str(p.as_of)),
                      ('Generated (UTC)', datetime.utcnow().strftime('%Y-%m-%d %H:%M'))], columns=['Item', 'Value']).to_excel(xw, sheet_name='Run_Info', index=False)
        for name, df in sheets.items():
            if df.empty:
                df = pd.DataFrame({'note': ['Nothing to show']})
            for c in df.columns:
                if df[c].dtype == float:
                    df[c] = df[c].round(2)
            df.to_excel(xw, sheet_name=name, index=False)
        for wsx in xw.book.worksheets:
            for c in wsx[1]:
                c.font = Font(name=ARIAL, bold=True, color='FFFFFF')
                c.fill = HEAD
            for colc in wsx.columns:
                width = max(len(str(c.value or '')) for c in list(colc)[:200])
                wsx.column_dimensions[colc[0].column_letter].width = min(max(9, width + 2), 50)
            wsx.freeze_panes = 'A2'
    return buf.getvalue()


def qbr_workbook(R, vendor, period='L3') -> bytes:
    """QBR pack for one OSAT: scorecard (weighted total as a live formula), measures, agenda and issues."""
    from . import insights as I
    p = R['plan']
    Q = I.qbr_view(p, R, period)
    d = next(x for x in Q['scores'] if x['vendor'] == vendor)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Scorecard'
    hdr = lambda c: (setattr(c, 'font', f(bold=True, color='FFFFFF')), setattr(c, 'fill', HEAD))
    ws['A1'] = f'Quarterly business review: OSAT-{vendor}'
    ws['A1'].font = f(bold=True, size=14)
    per = f'{Q["months"][0]} to {Q["months"][-1]}' if Q['months'] else 'no actuals'
    ws['A2'] = f'Period {per} · rank {d["rank"]} of {len(Q["scores"])} · as of {p.as_of:%d %b %Y}. Synthetic demo data.'
    ws['A2'].font = f(italic=True)
    ws['A3'] = 'Blue cells are inputs (weights, targets, category scores from Plan Yukta). The total and grade recalculate if you change them.'
    ws['A3'].font = f(size=9, color='595959')
    heads = ['Category', 'Measure', 'Target', 'Weight %', 'Score (0-100)', 'Weighted']
    for j, h in enumerate(heads, start=1):
        hdr(ws.cell(row=5, column=j, value=h))
    blue = f(color='0000FF')
    unit = {'Quality': '% of plan / reported', 'Delivery': '% of frozen plan', 'Cost': 'price index', 'Capacity': '% load on time',
            'Responsiveness': 'avg days to close'}
    for i, c in enumerate(I.CATS):
        r = 6 + i
        w, tgt = Q['weights'][c]
        val = d['values'][c]
        ws.cell(row=r, column=1, value=c).font = f()
        m = ws.cell(row=r, column=2, value=round(val, 2) if val is not None else None)
        m.font = f()
        m.number_format = '0.0'
        ws.cell(row=r, column=3, value=tgt).font = blue
        ws.cell(row=r, column=4, value=w).font = blue
        sc = ws.cell(row=r, column=5, value=round(d['scores'][c], 2) if d['scores'][c] is not None else None)
        sc.font = blue
        sc.number_format = '0.0'
        wc = ws.cell(row=r, column=6, value=f'=IF(E{r}="",0,E{r}*D{r})')
        wc.font = f()
        wc.number_format = '0.0'
        ws.cell(row=r, column=7, value=unit[c]).font = f(size=9, color='595959')
    last = 6 + len(I.CATS) - 1
    tr = last + 1
    ws.cell(row=tr, column=1, value='Total').font = f(bold=True)
    t = ws.cell(row=tr, column=5, value=f'=IFERROR(SUM(F6:F{last})/SUMPRODUCT((E6:E{last}<>"")*D6:D{last}),0)')
    t.font = f(bold=True)
    t.number_format = '0.0'
    ws.cell(row=tr + 1, column=1, value='Grade').font = f(bold=True)
    ws.cell(row=tr + 1, column=5, value=f'=IF(E{tr}>=90,"A",IF(E{tr}>=80,"B",IF(E{tr}>=70,"C","D")))').font = f(bold=True)
    ws.cell(row=tr + 3, column=1, value='Scoring: 100 at or above target, minus 5 points per % below. Responsiveness: minus 3 points per day over target, '
                                         '10 per overdue issue and 15 per open critical issue.').font = f(size=9, color='595959')
    for col_, w in zip('ABCDEFG', (18, 14, 10, 10, 14, 11, 22)):
        ws.column_dimensions[col_].width = w

    ag = wb.create_sheet('Agenda')
    for j, h in enumerate(['Category', 'Score', 'Why', 'Ask the vendor'], start=1):
        hdr(ag.cell(row=1, column=j, value=h))
    acts = [a for a in Q['actions'] if a['vendor'] == vendor]
    for i, a in enumerate(acts, start=2):
        for j, v in enumerate([a['category'], round(a['score'], 1), a['why'], a['action']], start=1):
            ag.cell(row=i, column=j, value=v).font = f()
    if not acts:
        ag.cell(row=2, column=1, value='Every category is at 90 or above.').font = f(italic=True)
    for col_, w in zip('ABCD', (16, 8, 40, 80)):
        ag.column_dimensions[col_].width = w

    tr_ = wb.create_sheet('Trend')
    for j, h in enumerate(['Month', 'Score'], start=1):
        hdr(tr_.cell(row=1, column=j, value=h))
    for i, (m, v) in enumerate(zip(Q['trend_months'], Q['trend'].get(vendor, [])), start=2):
        tr_.cell(row=i, column=1, value=m).font = f()
        c = tr_.cell(row=i, column=2, value=round(v, 1))
        c.font = f()

    iss = wb.create_sheet('Issues')
    cols = ['IssueID', 'Opened', 'Category', 'Severity', 'Title', 'SKU', 'Owner', 'Due', 'Status', 'Closed', 'days_to_close', 'RootCause', 'Action']
    heads = ['Issue', 'Opened', 'Category', 'Severity', 'Issue', 'Product', 'Owner', 'Due', 'Status', 'Closed', 'Days to close', 'Root cause', 'Action']
    for j, h in enumerate(heads, start=1):
        hdr(iss.cell(row=1, column=j, value=h))
    rows = [i for i in Q['issues'] if i['Vendor'] == vendor]
    red = PatternFill('solid', fgColor='FDE2E1')
    for i, r in enumerate(rows, start=2):
        for j, k in enumerate(cols, start=1):
            v = r.get(k)
            c = iss.cell(row=i, column=j, value=str(v) if k in ('Opened', 'Due', 'Closed') and v else v)
            c.font = f()
            c.alignment = Alignment(wrap_text=k in ('Title', 'RootCause', 'Action'), vertical='top')
            if r['overdue']:
                c.fill = red
    for col_, w in zip('ABCDEFGHIJKLM', (10, 11, 13, 9, 44, 9, 16, 11, 11, 11, 9, 30, 40)):
        iss.column_dimensions[col_].width = w
    iss.freeze_panes = 'A2'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def board_pack_workbook(ws, R=None) -> bytes:
    from .integrations import board_pack
    pk = board_pack(ws, R)
    wb = Workbook()
    sh = wb.active
    sh.title = 'Summary'
    sh['A1'] = pk['title']
    sh['A1'].font = f(bold=True, size=14)
    sh['A2'] = 'Generated by Plan Yukta. Synthetic demo data unless your own tables are loaded.'
    sh['A2'].font = f(italic=True, size=9, color='595959')
    k = pk['kpis']
    facts = [('Active projects', k['projects']), ('Committed', k['committed']), ('Proposed', k['proposed']),
             ('Committed value $M', round(k['value_committed'])), ('Capacity used next 12 months %', round(k['util12'], 1)),
             ('Red projects', k['red']), ('Amber projects', k['amber']), ('Dependency conflicts', k['dep_conflicts']),
             ('Over target capacity, FTE-months', round(k['overload_fte_m'], 1))]
    for i, (a, b) in enumerate(facts, start=4):
        sh.cell(row=i, column=1, value=a).font = f()
        sh.cell(row=i, column=2, value=b).font = f(bold=True)
    r0 = 5 + len(facts)
    sh.cell(row=r0, column=1, value='Executive brief').font = f(bold=True)
    for j, (lab, key) in enumerate((('Situation', 'S'), ('Complication', 'C'), ('Question', 'Q'), ('Answer', 'A')), start=r0 + 1):
        c = sh.cell(row=j, column=1, value=f'{lab}: {pk["brief"][key]}')
        c.font = f()
        c.alignment = Alignment(wrap_text=True, vertical='top')
        sh.merge_cells(start_row=j, start_column=1, end_row=j, end_column=6)
        sh.row_dimensions[j].height = 48
    r0 += 6
    sh.cell(row=r0, column=1, value='Headlines').font = f(bold=True)
    for i, s in enumerate(pk['summary'], start=r0 + 1):
        c = sh.cell(row=i, column=1, value='• ' + s)
        c.font = f()
        c.alignment = Alignment(wrap_text=True, vertical='top')
        sh.merge_cells(start_row=i, start_column=1, end_row=i, end_column=6)
        sh.row_dimensions[i].height = 32
    sh.column_dimensions['A'].width = 38
    sh.column_dimensions['B'].width = 14
    for name, key in (('Gate decisions', 'gates'), ('Capacity asks', 'asks'), ('Portfolio', 'portfolio'), ('Risks', 'risks'), ('Decisions', 'decisions')):
        rows = pk[key]
        w = wb.create_sheet(name)
        if not rows:
            w['A1'] = 'None.'
            continue
        cols = list(rows[0])
        for j, c in enumerate(cols, start=1):
            cell = w.cell(row=1, column=j, value=c)
            cell.font = f(bold=True, color='FFFFFF')
            cell.fill = HEAD
            w.column_dimensions[cell.column_letter].width = max(10, min(48, max(len(str(c)), *(len(str(r[c] or '')) for r in rows)) + 2))
        for i, r in enumerate(rows, start=2):
            for j, c in enumerate(cols, start=1):
                cell = w.cell(row=i, column=j, value=r[c])
                cell.font = f()
                cell.alignment = Alignment(wrap_text=len(str(r[c] or '')) > 50, vertical='top')
        w.freeze_panes = 'A2'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
