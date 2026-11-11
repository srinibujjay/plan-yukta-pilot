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
