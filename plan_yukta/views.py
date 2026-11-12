"""
Page builders. Each returns a dict the generic module template renders:
  title, summary, filters, sections = [kpis | chart | table | grid | html | cols]
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from html import escape

from . import charts
from .cockpit import FLOW_ORDER, PAD, TEST_OPS, month_add
from .modules import INFO

VENDOR_NAME = lambda v: f'OSAT-{v}'


# ------------------------------------------------------------------ helpers
def K(label, value, sub='', tone=''):
    return dict(label=label, value=value, sub=sub, tone=tone)


def n0(v):
    return '–' if v is None else f'{v:,.0f}'


def short(v):
    if v is None:
        return '–'
    a = abs(v)
    if a >= 1e9:
        return f'{v / 1e9:.2f}B'
    if a >= 1e6:
        return f'{v / 1e6:.2f}M'
    if a >= 1e4:
        return f'{v / 1e3:.0f}k'
    return f'{v:,.0f}'


def money(v, nd=0):
    if v is None:
        return '–'
    a = abs(v)
    if nd == 0 and a >= 1e6:
        return f'${v / 1e6:,.2f}M'
    if nd == 0 and a >= 1e4:
        return f'${v / 1e3:,.0f}k'
    return f'${v:,.{nd}f}'


def mlabel(m):
    names = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    return f'{names[int(m[5:7]) - 1]} {m[2:4]}'


def table(title, cols, rows, note='', tid=None, limit=None, search=True, empty='Nothing to show.'):
    return {'type': 'table', 'title': title, 'note': note, 'cols': cols, 'rows': rows, 'id': tid or title.lower().replace(' ', '-'),
            'limit': limit, 'search': search, 'empty': empty}


def col(key, label, fmt='text', tone=None, align=None):
    return {'key': key, 'label': label, 'fmt': fmt, 'tone': tone,
            'align': align or ('r' if fmt not in ('text', 'badge', 'month', 'date', 'link') else 'l')}


def grid(title, months, groups, note=''):
    return {'type': 'grid', 'title': title, 'note': note, 'months': [mlabel(m) for m in months], 'groups': groups}


def cell(v, tone='', fmt='short'):
    if v is None or (isinstance(v, float) and abs(v) < 0.5 and fmt != 'pct'):
        return ('–', tone)
    if fmt == 'pct':
        return (f'{v:.0f}%', tone)
    if fmt == 'num1':
        return (f'{v:,.1f}', tone)
    if fmt == 'int':
        return (f'{v:,.0f}', tone)
    return (short(v), tone)


def util_tone(u):
    return 'bad' if u > 100.5 else 'warn' if u > 85 else 'ok' if u > 0 else ''


def chart(title, html, note=''):
    return {'type': 'chart', 'title': title, 'html': html, 'note': note}


def html(h):
    return {'type': 'html', 'html': h}


def cols2(*sections):
    return {'type': 'cols', 'items': list(sections)}


def callout(text, tone='info'):
    return html(f'<div class="callout {tone}">{text}</div>')


def apply_filters(rows, args, keys=('sku', 'vendor')):
    out = rows
    for k in keys:
        v = args.get(k)
        if v:
            out = [r for r in out if str(r.get(k)) == v]
    return out


def filter_spec(R, which=('sku', 'vendor')):
    p = R['plan']
    spec = []
    if 'sku' in which:
        spec.append(('sku', 'Product', sorted({c.sku for c in p.chains})))
    if 'vendor' in which:
        spec.append(('vendor', 'OSAT', sorted({c.vendor for c in p.chains})))
    return spec


def page(key, sections, filters=None, extra=None):
    info = INFO.get(key, {})
    d = {'key': key, 'title': info.get('title', key), 'summary': info.get('summary', ''), 'info': info,
         'sections': sections, 'filters': filters or []}
    d.update(extra or {})
    return d


# ------------------------------------------------------------------ cockpit
def home(R, args):
    p, h = R['plan'], R['home']
    months = p.months
    pk = h['load_peak']
    sections = [
        {'type': 'kpis', 'items': [
            K('Demand, next 6 months', short(h['demand6']), 'units, all products'),
            K('Customer shortfall', short(h['short']) if h['short'] > 0.5 else 'None', 'units late or short in the horizon',
              'bad' if h['short'] > 0.5 else 'ok'),
            K('Peak tester load', f'{pk[0]:.0f}%', f'OSAT-{pk[1]} {pk[2]}, {mlabel(pk[3])}' if pk[1] else '',
              util_tone(pk[0])),
            K('Wafer POs to act on', f'{len(h["po_due"])}', 'past cutoff or order now', 'warn' if h['po_due'] else 'ok'),
            K('Lots on hold', f'{len(h["holds"])}', 'not counted as supply', 'warn' if h['holds'] else 'ok'),
            K('Plan revenue', money(h['revenue']), f'{h["gm"]:.1f}% gross margin, {len(months)} months'),
            K('Data checks', f'{h["errors"]} / {h["warnings"]}', 'errors / warnings', 'bad' if h['errors'] else 'warn' if h['warnings'] else 'ok'),
        ]},
    ]
    m = args.get('month') if args.get('month') in months else months[0]
    i = months.index(m)
    t = R['flow']['totals']
    stages = [('Fab starts', short(t['fab_starts'][i]), 'wafers', 'fab'),
              ('Sort', short(t['Sort'][i]), 'wafers', 'sort'), ('Bump', short(t['Bump'][i]), 'wafers', 'bump'),
              ('Assembly', short(t['Assembly'][i]), 'units', 'assy'), ('Test 1', short(t['Test1'][i]), 'units', 'test'),
              ('Test 2', short(t['Test2'][i]), 'units', 'test'), ('Pack', short(t['Pack'][i]), 'units', 'pack'),
              ('Ship', short(t['ship'][i]), 'units', 'ship' if t['short'][i] < 0.5 else 'bad')]
    month_links = ' '.join(f'<a class="chip{" on" if mm == m else ""}" href="?month={mm}">{mlabel(mm)}</a>' for mm in months)
    sections.append(chart(f'Plan for {mlabel(m)}: starts at every step',
                          f'<div class="chips">{month_links}</div>' + charts.flow_diagram(stages),
                          'Starts in the month at each step, all products and OSATs. Fab starts feed customers about four months later.'))
    # tester heatmap
    groups = []
    rows = []
    for (v, st), a in sorted(p.alloc.items(), key=lambda kv: (TEST_OPS.index(kv[0][1]), kv[0][0])):
        cells = [cell(x['load_util'], util_tone(x['load_util']), 'pct') for x in a['summary'][:p.H]]
        rows.append({'label': f'OSAT-{v} · {st}', 'cells': cells, 'href': f'/m/testers?vendor={v}'})
    groups.append({'title': '', 'rows': rows})
    sections.append(grid('Tester load by OSAT and step', months, groups,
                         'Load before pull-in, as % of the testers available. Amber above 85%, red above 100%.'))
    # demand vs supply chart
    sections.append(chart('Demand and shipments, all products', charts.bars(
        months, [('Shipped', t['ship']), ('Short', t['short'])],
        lines=[('Demand', t['demand'])], title='Demand and shipments')))
    al = [dict(a, link=MODULE_LINK.get(a['module'], '/')) for a in h['alerts']]
    sections.append(table('Alerts', [col('severity', 'Level', 'badge'), col('module', 'Module', 'link'),
                                     col('month', 'Month', 'month'), col('sku', 'Product / resource'), col('text', 'What it means')],
                          al, tid='alerts', empty='No alerts: the plan can be made as it stands.'))
    return page('home', sections)


MODULE_LINK = {'FAB PO': '/m/fab-po', 'Substrate': '/m/substrate', 'Complete Flow': '/m/flow', 'Testing Starts': '/m/testing',
               'NPI': '/m/npi', 'Hardware': '/m/hardware'}


# ------------------------------------------------------------------ demand
def demand(R, args):
    p = R['plan']
    rows = R['demand']['rows']
    sel = args.get('sku') or None
    show = [r for r in rows if not sel or r['sku'] == sel]
    sections = []
    tot = sum(sum(r['plan'][:p.H]) for r in rows)
    sections.append({'type': 'kpis', 'items': [
        K('Plan demand', short(tot), f'units over {p.H} months'),
        K('Booked orders', short(sum(sum(r['orders'][:p.H]) for r in rows)), 'units in the horizon'),
        K('Uplift', f'{float(p.s["Demand uplift %"]):+.0f}%', 'Plan settings'),
        K('Products', str(len(rows)), ', '.join(sorted({r['strategy'] for r in rows}))),
    ]})
    for r in show:
        hm = r['hist_months']
        labels = hm + p.months
        hist = r['hist'] + [None] * p.H
        k = len(hm)
        plan = [None] * (k - 1) + ([r['hist'][-1]] if k else []) + r['plan'][:p.H]
        fc = [None] * k + [v or None for v in r['forecast'][:p.H]]
        st = [None] * k + r['stat'][:p.H]
        od = [None] * k + [v or None for v in r['orders'][:p.H]]
        acc = r['acc']
        acc_t = (f'Statistical forecast accuracy (last 6 months): WMAPE {acc["wmape"]:.1f}%, bias {acc["bias"]:+.1f}%.'
                 if acc else 'Not enough history for a statistical forecast; the customer forecast is used.')
        sections.append(chart(f'{r["sku"]} · {r["status"]} · build strategy {r["strategy"]}', charts.lines(
            labels, [('Shipped (history)', hist, False), ('Plan demand', plan, False), ('Customer forecast', fc, True),
                     ('Statistical (Holt)', st, True), ('Booked orders', od, False)], split_at=k, title=r['sku']), acc_t))
    months = p.months
    groups = []
    for r in show:
        groups.append({'title': r['sku'], 'sub': r['strategy'], 'rows': [
            {'label': 'Customer forecast', 'cells': [cell(v) for v in r['forecast'][:p.H]]},
            {'label': 'Booked orders', 'cells': [cell(v) for v in r['orders'][:p.H]]},
            {'label': 'Statistical (Holt)', 'cells': [cell(v) for v in r['stat'][:p.H]]},
            {'label': 'Plan demand', 'cells': [cell(v, 'strong') for v in r['plan'][:p.H]], 'strong': True},
            {'label': 'Order coverage', 'cells': [cell(v, '', 'pct') if v is not None else ('–', '') for v in r['order_cover'][:p.H]]},
        ]})
    sections.append(grid('Demand by month', months, groups, 'Units. Plan demand includes the demand uplift.'))
    return page('demand', sections, filters=filter_spec(R, ('sku',)))


# ------------------------------------------------------------------ M1 testing
def testing(R, args):
    p = R['plan']
    T = R['testing']
    lines = apply_filters(T['lines'], args)
    step = args.get('step')
    if step:
        lines = [l for l in lines if l['step'] == step]
    by = defaultdict(list)
    for l in lines:
        by[(l['sku'], l['vendor'], l['step'])].append(l)
    tot_ins = sum(l['ins_req'] for l in lines)
    tot_gap = sum(l['gap'] for l in lines)
    tot_pull = sum(l['pullin'] for l in lines)
    nc = sum(l['tn'] for l in lines)
    sections = [{'type': 'kpis', 'items': [
        K('Test insertions', short(tot_ins), f'units incl. retest, {p.H} months'),
        K('Pull-in', short(tot_pull), 'units built ahead with idle testers', 'warn' if tot_pull > 0.5 else ''),
        K('Short after pull-in', short(tot_gap) if tot_gap > 0.5 else 'None', 'made late (catch-up)', 'bad' if tot_gap > 0.5 else 'ok'),
        K('Non-consignee tester-months', f'{nc:,.1f}', 'OSAT testers used (higher rate)', 'warn' if nc > 0.05 else ''),
    ]}]
    # chart: test starts by vendor
    months = p.months
    series = []
    for v in sorted({l['vendor'] for l in lines}):
        series.append((f'OSAT-{v}', [sum(l['prod'] for l in lines if l['vendor'] == v and l['month'] == m) for m in months]))
    load = [sum(l['ins_req'] for l in lines if l['month'] == m) for m in months]
    sections.append(chart('Test insertions made, by OSAT', charts.bars(months, series, lines=[('Load required', load)], title='Test insertions'),
                          'Bars: insertions the testers make (including pull-in and catch-up). Line: what the plan asks for in the month.'))
    groups = []
    for (sku, v, st), ls in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])):
        ls.sort(key=lambda l: l['month'])
        u0, u1 = min(l['upm'] for l in ls), max(l['upm'] for l in ls)
        utxt = f'{u0:,.0f}' if abs(u1 - u0) < 1 else f'{ls[0]["upm"]:,.0f} → {ls[-1]["upm"]:,.0f} (override)'
        groups.append({'title': f'{sku} · OSAT-{v} · {st}', 'sub': f'share {ls[0]["share"]:.0f}% · {utxt} units per tester-month',
                       'rows': [
                           {'label': 'Test yield / retest', 'cells': [(f'{l["yield"]:.0f}% / {l["rework"]:.0f}%', '') for l in ls]},
                           {'label': 'Units per tester-month', 'cells': [cell(l['upm'], 'info' if i and abs(l['upm'] - ls[i - 1]['upm']) > 1 else '') for i, l in enumerate(ls)]},
                           {'label': 'Starts required', 'cells': [cell(l['starts_req']) for l in ls]},
                           {'label': 'Tester load (insertions)', 'cells': [cell(l['ins_req']) for l in ls]},
                           {'label': 'Consignee testers', 'cells': [cell(l['tc'], '', 'num1') for l in ls]},
                           {'label': 'Non-consignee testers', 'cells': [cell(l['tn'], 'warn' if l['tn'] > 0.05 else '', 'num1') for l in ls]},
                           {'label': 'Made', 'cells': [cell(l['prod'], 'strong') for l in ls], 'strong': True},
                           {'label': 'Pull-in (built early)', 'cells': [cell(l['pullin'], 'info' if l['pullin'] > 0.5 else '') for l in ls]},
                           {'label': 'Short (after pull-in)', 'cells': [cell(l['gap'], 'bad' if l['gap'] > 0.5 else '') for l in ls]},
                       ]})
    sections.append(grid('Testing starts and tester allocation', months, groups,
                         'Units. Testers are tester-months: 0.5 means half a tester for the month. Pull-in is made in that month for a later shortfall.'))
    if T['late']:
        lt = [dict(r, vendor=f'OSAT-{r["vendor"]}') for r in apply_filters(
            [dict(x) for x in T['late']], args)]
        sections.append(table('Needed before the plan start (inside lead time)', [
            col('sku', 'Product'), col('vendor', 'OSAT'), col('op', 'Step'), col('qty', 'Quantity', 'int'), col('first', 'Needed from', 'month')],
            lt, note='These starts should already have happened. They are made in the first month, so finished goods arrive late unless stock covers them.'))
    return page('testing', sections, filters=filter_spec(R) + [('step', 'Step', ['Test1', 'Test2'])])


def pullin(R, args):
    p = R['plan']
    rows = []
    for sku, pr in p.products.items():
        pulls = sum(sum(ch.levels[op]['alloc']['pullin'][:p.H]) for ch in p.chains if ch.sku == sku for op in ('Test1', 'Test2') if op in ch.ops)
        gaps = sum(sum(ch.levels[op]['alloc']['gap'][:p.H]) for ch in p.chains if ch.sku == sku for op in ('Test1', 'Test2') if op in ch.ops)
        cov = sum(sum(ch.levels[op]['alloc']['covered'][:p.H]) for ch in p.chains if ch.sku == sku for op in ('Test1', 'Test2') if op in ch.ops)
        from .cockpit import pullin_intensity, strategy_label, DEFAULT_WEIGHT
        inten, nc = pullin_intensity(pr.get('PullInWeight'))
        rows.append({'sku': sku, 'pull': pr['PullIn'], 'sl': pr['ServiceLevelPct'], 'max': pr['MaxPullInPct'],
                     'weight': pr.get('PullInWeight') if pr.get('PullInWeight') is not None else DEFAULT_WEIGHT,
                     'strategy': strategy_label(pr.get('PullInWeight'), pr['PullIn']), 'build': pr['BuildStrategy'], 'nc': nc,
                     'cap': min(float(pr['ServiceLevelPct']), float(pr['MaxPullInPct'])) * inten if pr['PullIn'] == 'Y' else 0,
                     'prio': pr['Priority'], 'ss': pr['SafetyStockWeeks'], 'pulled': pulls, 'covered': cov, 'left': gaps})
    sections = pullin_plan(R, args)
    sel = args.get('sku_sel') if args.get('sku_sel') in p.products else (max(rows, key=lambda r: r['pulled'] + r['left'])['sku'] if rows else None)
    preview = pullin_preview_html(R, R, sel) if sel else '<div class="callout info">Add a product in Products to set up pull-in.</div>'
    return page('pullin', sections, extra={'template': 'pullin.html', 'rows': rows, 'horizon': p.s['Pull-in horizon months'],
                                           'sel': sel, 'preview': preview, 'allow_nc': p.s['Allow non-consignee testers']},
                filters=filter_spec(R))


def pullin_plan(R, args):
    """Build-ahead production plan: what each test step makes against what it needs, the stock it builds
    ahead of a crunch, what it still owes, and finished goods against safety stock."""
    p = R['plan']
    H, months = p.H, p.months
    stock_by = {'Test1': [0.0] * H, 'Test2': [0.0] * H, 'Sort': [0.0] * H}
    owed_by = [0.0] * H
    groups = []
    for ch in p.chains:
        if (args.get('sku') and ch.sku != args['sku']) or (args.get('vendor') and ch.vendor != args['vendor']):
            continue
        for op in ('Sort', 'Test1', 'Test2'):
            if op not in ch.ops:
                continue
            lvl = ch.levels[op]
            r = lvl['alloc']
            unit = 'wafers' if op == 'Sort' else 'units'
            ahead, cum = [], 0.0
            for i in range(H):
                cum += r['prod'][i] - r['load'][i]
                rw = lvl['rw'][PAD + i] if op != 'Sort' else 0.0
                y = 1.0 if op == 'Sort' else lvl['yield'][PAD + i]
                good = max(0.0, cum) / (1 + rw) * y           # good units (or wafers) already made for later months
                ahead.append(good)
                stock_by[op][i] += good
            for i in range(H):
                owed_by[i] += r['late_left'][i] if op != 'Sort' else 0.0
            if not (sum(r['pullin'][:H]) > 0.5 or sum(r['catchup'][:H]) > 0.5):
                continue
            groups.append({'title': f'{ch.sku} · OSAT-{ch.vendor} · {op}', 'sub': f'{unit}; pull-in cap {min(float(p.products[ch.sku]["ServiceLevelPct"]), float(p.products[ch.sku]["MaxPullInPct"])):.0f}% ({"on" if p.products[ch.sku]["PullIn"] == "Y" else "off"})',
                           'rows': [
                               {'label': 'Needed (tester load)', 'cells': [cell(x) for x in r['load'][:H]]},
                               {'label': 'Made', 'cells': [cell(x, 'strong') for x in r['prod'][:H]], 'strong': True},
                               {'label': 'Of which built early (pull-in)', 'cells': [cell(x, 'info' if x > 0.5 else '') for x in r['pullin'][:H]]},
                               {'label': 'Of which made late (catch-up)', 'cells': [cell(x, 'warn' if x > 0.5 else '') for x in r['catchup'][:H]]},
                               {'label': 'Build-ahead stock after the step, end of month', 'cells': [cell(x, 'info' if x > 0.5 else '') for x in ahead]},
                               {'label': 'Still owed (behind plan)', 'cells': [cell(x, 'bad' if x > 0.5 else '') for x in r['late_left'][:H]]},
                           ]})
    fg = [0.0] * H
    ss = [0.0] * H
    dem = [0.0] * H
    for (sku, v), f in p.fg.items():
        if (args.get('sku') and sku != args['sku']) or (args.get('vendor') and v != args['vendor']):
            continue
        for i in range(H):
            fg[i] += f['fg_end'][i]
            ss[i] += f['ss'][i]
            dem[i] += f['demand'][i]
    cover = [(fg[i] / (dem[min(i + 1, H - 1)] / 4.33) if dem[min(i + 1, H - 1)] else None) for i in range(H)]
    summary = grid('Stock by process, end of month', months, [{'title': '', 'rows': [
        {'label': 'Build-ahead after Sort (wafers)', 'cells': [cell(x, 'info' if x > 0.5 else '') for x in stock_by['Sort']]},
        {'label': 'Build-ahead after Test 1 (units)', 'cells': [cell(x, 'info' if x > 0.5 else '') for x in stock_by['Test1']]},
        {'label': 'Build-ahead after Test 2 (units)', 'cells': [cell(x, 'info' if x > 0.5 else '') for x in stock_by['Test2']]},
        {'label': 'Finished goods (units)', 'cells': [cell(x, 'strong') for x in fg], 'strong': True},
        {'label': 'Safety stock target (units)', 'cells': [cell(x) for x in ss]},
        {'label': 'Finished goods cover (weeks)', 'cells': [(f'{c:.1f}' if c is not None else '–', 'warn' if c is not None and c < 1 else '') for c in cover]},
        {'label': 'Test units still owed (behind plan)', 'cells': [cell(x, 'bad' if x > 0.5 else '') for x in owed_by]},
    ]}], 'Build-ahead stock = units a test step has already made for a later month (good units, after yield). It is used up when the crunch comes.')
    ch_html = charts.bars(months, [('Build-ahead after Test 1', stock_by['Test1']), ('Build-ahead after Test 2', stock_by['Test2'])],
                          lines=[('Test units still owed', owed_by)], title='Build-ahead stock')
    out = [chart('Pull-in production plan: stock built ahead of the crunch', ch_html,
                 'Stock rises while idle testers build ahead, peaks just before the crunch, and is used up during it. The line shows units the testers still owe after it.'),
           summary]
    if groups:
        out.append(grid('Build-ahead plan by product, OSAT and step', months, groups,
                        'Only steps with pull-in or catch-up are shown. Change caps above, or capacity on Tester & Capacity Overrides.'))
    else:
        out.append(callout('No pull-in or catch-up in this plan: every test step can make its load in the month it is needed.', 'ok'))
    return out


# ------------------------------------------------------------------ M2 / M3
def assembly(R, args):
    p = R['plan']
    rows = apply_filters(R['assembly']['rows'], args)
    months = p.months
    by = defaultdict(list)
    for r in rows:
        by[(r['sku'], r['vendor'])].append(r)
    sections = [{'type': 'kpis', 'items': [
        K('Die into assembly', short(sum(r['die_in'] for r in rows)), f'units, {p.H} months'),
        K('Sorted wafers needed', short(sum(r['wafers'] for r in rows)), 'equivalent wafers'),
        K('Assembled stock & WIP used', short(sum(s['supply'] - s['left'] for s in apply_filters(R['assembly']['supply'], args))), 'units netted'),
    ]}]
    series = [(f'OSAT-{v}', [sum(r['die_in'] for r in rows if r['vendor'] == v and r['month'] == m) for m in months])
              for v in sorted({r['vendor'] for r in rows})]
    sections.append(chart('Die into assembly by OSAT', charts.bars(months, series, title='Assembly starts')))
    groups = []
    for (sku, v), ls in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        groups.append({'title': f'{sku} · OSAT-{v}', 'sub': f'{ls[0]["die_per_wafer"]:,.0f} good die per sorted wafer', 'rows': [
            {'label': 'Test starts to feed', 'cells': [cell(l['units_out_needed']) for l in ls]},
            {'label': 'Assembly yield', 'cells': [(f'{l["yield"]:.1f}%', '') for l in ls]},
            {'label': 'Die into assembly', 'cells': [cell(l['die_in'], 'strong') for l in ls], 'strong': True},
            {'label': 'Sorted wafers (equiv.)', 'cells': [cell(l['wafers'], '', 'num1') for l in ls]},
        ]})
    sections.append(grid('Assembly starts', months, groups, 'Units unless stated. Test starts are after the tester plan (pull-in and catch-up).'))
    return page('assembly', sections, filters=filter_spec(R))


def frontend(R, args):
    p = R['plan']
    rows = apply_filters(R['frontend']['rows'], args)
    months = p.months
    fab = [r for r in R['frontend']['fab'] if not args.get('sku') or r['sku'] == args.get('sku')]
    sections = [{'type': 'kpis', 'items': [
        K('Wafer sort starts', short(sum(r['Sort'] or 0 for r in rows)), 'wafers at the OSATs'),
        K('Bump starts', short(sum(r['Bump'] or 0 for r in rows)), 'wafers'),
        K('Fab wafer starts', short(sum(r['starts'] for r in fab)), f'wafers, lots of {p.lot}'),
        K('Fab WIP arriving', short(sum(r['wip'] for r in fab)), 'wafers in the horizon'),
    ]}]
    series = [(s, [sum(r['starts'] for r in fab if r['sku'] == s and r['month'] == m) for m in months]) for s in sorted({r['sku'] for r in fab})]
    need = [sum(r['need'] for r in fab if r['month'] == m) for m in months]
    sections.append(chart('Fab wafer starts by product', charts.bars(months, series, lines=[('Wafers needed at sort (by arrival month)', need)],
                                                                    ref=(float(p.s['Fab capacity wafers per month']), 'Fab capacity'), title='Fab starts'),
                          f'Starts are about {next(iter(p.fab.values()))["d_start"] if p.fab else 3} months before the wafers arrive at sort.'))
    groups = []
    for sku in sorted({r['sku'] for r in fab}):
        fs = [r for r in fab if r['sku'] == sku]
        groups.append({'title': f'{sku} · FAB', 'rows': [
            {'label': 'Wafers needed at sort', 'cells': [cell(r['need']) for r in fs]},
            {'label': 'Fab WIP arriving', 'cells': [cell(r['wip']) for r in fs]},
            {'label': 'New starts arriving', 'cells': [cell(r['outs']) for r in fs]},
            {'label': 'Wafer starts', 'cells': [cell(r['starts'], 'strong') for r in fs], 'strong': True},
            {'label': 'Wafers late (cumulative)', 'cells': [cell(r['gap'], 'bad' if r['gap'] > 0.5 else '') for r in fs]},
        ]})
    by = defaultdict(list)
    for r in rows:
        by[(r['sku'], r['vendor'])].append(r)
    for (sku, v), ls in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        rr = [{'label': 'Sort starts (wafers)', 'cells': [cell(l['Sort'], 'strong') for l in ls], 'strong': True},
              {'label': 'Probers used', 'cells': [cell(l.get('probers'), '', 'num1') for l in ls]}]
        if any(l['Bump'] is not None for l in ls):
            rr.insert(0, {'label': 'Bump starts (wafers)', 'cells': [cell(l['Bump']) for l in ls]})
        if any((l.get('sort_gap') or 0) > 0.5 for l in ls):
            rr.append({'label': 'Sort short', 'cells': [cell(l.get('sort_gap'), 'bad') for l in ls]})
        groups.append({'title': f'{sku} · OSAT-{v}', 'rows': rr})
    sections.append(grid('Front end and wafer plan', months, groups, 'Wafers.'))
    return page('frontend', sections, filters=filter_spec(R))


def flow(R, args):
    p = R['plan']
    rows = apply_filters(R['flow']['rows'], args)
    months = p.months
    by = defaultdict(list)
    for r in rows:
        by[(r['sku'], r['vendor'])].append(r)
    short_tot = sum(max([r['short'] for r in ls] + [0]) for ls in by.values())
    sections = [{'type': 'kpis', 'items': [
        K('Demand', short(sum(r['demand'] for r in rows)), 'units'),
        K('Shipped on time or late', short(sum(r['ship'] for r in rows)), 'units'),
        K('Peak shortfall', short(short_tot) if short_tot > 0.5 else 'None', 'units owed to customers', 'bad' if short_tot > 0.5 else 'ok'),
        K('Product-OSAT chains', str(len(by)), 'supply chains planned'),
    ]}]
    groups = []
    for (sku, v), ls in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        rr = [{'label': 'Demand', 'cells': [cell(l['demand']) for l in ls]},
              {'label': 'Shipped', 'cells': [cell(l['ship'], 'strong') for l in ls], 'strong': True},
              {'label': 'Short (owed)', 'cells': [cell(l['short'], 'bad' if l['short'] > 0.5 else '') for l in ls]},
              {'label': 'Finished goods, end', 'cells': [cell(l['fg_end'], 'warn' if l['fg_end'] < l['ss'] * 0.5 and l['demand'] > 0 else '') for l in ls]},
              {'label': 'Safety stock target', 'cells': [cell(l['ss']) for l in ls]},
              {'label': 'Pack output', 'cells': [cell(l['pack_out']) for l in ls]}]
        for op, lab in (('Test2', 'Test 2 starts'), ('Test1', 'Test 1 starts'), ('Assembly', 'Assembly die in'),
                        ('Bump', 'Bump wafers'), ('Sort', 'Sort wafers')):
            if any(l[op] is not None for l in ls):
                rr.append({'label': lab, 'cells': [cell(l[op], '', 'num1' if op in ('Bump', 'Sort') else 'short') for l in ls]})
        groups.append({'title': f'{sku} · OSAT-{v}', 'rows': rr})
    sections.append(grid('Complete flow, from wafer to customer', months, groups,
                         'Units, wafers for Bump and Sort. Read bottom-up for the build, top-down for the customer.'))
    return page('flow', sections, filters=filter_spec(R))


# ------------------------------------------------------------------ capacity
def testers(R, args):
    p = R['plan']
    months = p.months
    caps = [c for c in R['testing']['caps'] if (not args.get('vendor') or c['vendor'] == args['vendor'])]
    sections = []
    peak = max(caps, key=lambda c: c['load_util'], default=None)
    over = [c for c in caps if c['load_util'] > 100.5]
    sections.append({'type': 'kpis', 'items': [
        K('Peak load', f'{peak["load_util"]:.0f}%' if peak else '–', f'OSAT-{peak["vendor"]} {peak["step"]}, {mlabel(peak["month"])}' if peak else '',
          util_tone(peak['load_util']) if peak else ''),
        K('Months over 100%', str(len(over)), 'tester-step-months', 'bad' if over else 'ok'),
        K('Testers in fleet', str(sum(f['Consignee'] + f['NonConsignee'] for f in p.t['tester_fleet'])), 'consignee + non-consignee'),
        K('Buffer target', f'{float(p.s["Capacity buffer %"]):.0f}%', 'headroom wanted (Plan settings)'),
    ]})
    groups = []
    for (v, st) in sorted({(c['vendor'], c['step']) for c in caps}, key=lambda k: (TEST_OPS.index(k[1]), k[0])):
        cs = [c for c in caps if c['vendor'] == v and c['step'] == st]
        groups.append({'title': f'OSAT-{v} · {st}', 'rows': [
            {'label': 'Overrides this month', 'cells': [('; '.join(c['events']), 'ev') if c['events'] else ('', '') for c in cs]},
            {'label': 'Testers available', 'cells': [(f'{c["consignee"]}+{c["non_consignee"]}', '') for c in cs]},
            {'label': 'Testers needed', 'cells': [cell(c['needed'], '', 'num1') for c in cs]},
            {'label': 'Load %', 'cells': [cell(c['load_util'], util_tone(c['load_util']), 'pct') for c in cs], 'strong': True},
            {'label': 'Utilisation % (after pull-in)', 'cells': [cell(c['util'], util_tone(c['util']), 'pct') for c in cs]},
            {'label': 'Short', 'cells': [cell(c['gap'], 'bad' if c['gap'] > 0.5 else '') for c in cs]},
        ]})
    sections.append(grid('Tester load by month', months, groups,
                         'Available = consignee + non-consignee testers. Load % is before pull-in; utilisation after pull-in and catch-up.'))
    # throughput table
    rows = []
    for (v, sku, st), c in sorted(p.cap.items()):
        if (args.get('vendor') and v != args['vendor']) or sku not in p.products:
            continue
        upm, sec = p.upm(v, sku, st)
        rows.append({'vendor': f'OSAT-{v}', 'sku': sku, 'step': st, 'tt': c['TestTimeSec'], 'sites': c['Sites'],
                     'idx': c['IndexTimeSec'], 'oee': float(c['OEE']) * 100, 'sec': sec, 'uph': 3600 / sec if sec else 0, 'upm': upm,
                     'unit': 'wafer' if st == 'Sort' else 'unit'})
    sections.append(table('Tester throughput', [
        col('vendor', 'OSAT'), col('sku', 'Product'), col('step', 'Step'), col('tt', 'Test time (s)', 'num1'),
        col('sites', 'Sites', 'int'), col('idx', 'Index (s)', 'num1'), col('oee', 'OEE %', 'num0'),
        col('sec', 'Seconds per unit', 'num2'), col('uph', 'Per hour', 'num1'), col('upm', 'Per tester-month', 'int'), col('unit', 'Unit')],
        rows, note='Sort is per wafer: ⌈GDPW ÷ sites⌉ ÷ stepping efficiency × (test + index) + load time.'))
    return page('testers', sections, filters=[('vendor', 'OSAT', sorted({c.vendor for c in p.chains}))])


def hardware(R, args):
    p = R['plan']
    H = R['hardware']
    rows = [r for r in H['rows'] if not args.get('vendor') or r['vendor'] == args['vendor']]
    months = p.months
    groups = []
    for (v, st) in sorted({(r['vendor'], r['step']) for r in rows}, key=lambda k: (k[0], TEST_OPS.index(k[1]))):
        rs = [r for r in rows if r['vendor'] == v and r['step'] == st]
        groups.append({'title': f'OSAT-{v} · {st}', 'rows': [
            {'label': 'Consignee testers (fleet)', 'cells': [cell(r['fleet_c'], '', 'int') for r in rs]},
            {'label': 'Hardware-ready testers', 'cells': [cell(r['ready'], 'bad' if r['ready'] < r['fleet_c'] else 'ok', 'int') for r in rs], 'strong': True},
            {'label': 'Consignee used by the plan', 'cells': [cell(r['planned_c'], 'warn' if r['planned_c'] > r['ready'] + 0.05 else '', 'num1') for r in rs]},
        ]})
    gaps = [r for r in rows if r['gap'] > 0]
    sections = [{'type': 'kpis', 'items': [
        K('Tester-months without a full kit', str(sum(r['gap'] for r in rows)), 'consignee testers × months', 'warn' if gaps else 'ok'),
        K('Hardware limit in the plan', 'On' if p.hw_limit else 'Off', '"Limit testers to hardware-ready"', 'info'),
        K('Deliveries due', str(len(H['arrivals'])), 'hardware arrival overrides', 'info'),
    ]}, grid('Hardware-ready testers', months, groups,
             'Red: fewer full kits than consignee testers. Amber: the plan uses more consignee tester time than has hardware.')]
    items = [dict(i, vendor=f'OSAT-{i["Vendor"]}', ready=(int(i['InService'] or 0) // max(1, int(i['PerTester'])))) for i in H['items']
             if not args.get('vendor') or i['Vendor'] == args['vendor']]
    sections.append(table('Hardware items', [col('vendor', 'OSAT'), col('Step', 'Step'), col('HardwareType', 'Hardware'),
                                             col('PerTester', 'Per tester', 'int'), col('InService', 'In service', 'int'),
                                             col('ready', 'Testers it supports today', 'int')], items))
    arr = [dict(a, vendor=f'OSAT-{a["Vendor"]}') for a in H['arrivals'] if not args.get('vendor') or a['Vendor'] == args['vendor']]
    sections.append(table('Hardware arrivals (overrides)', [col('Month', 'Month', 'month'), col('vendor', 'OSAT'), col('Step', 'Step'),
                                                           col('HardwareType', 'Hardware'), col('Qty', 'Quantity', 'int'), col('Note', 'Note')],
                          arr, search=False, empty='No hardware deliveries entered.',
                          note='Add or change deliveries on the Tester & Capacity Overrides page.'))
    return page('hardware', sections, filters=[('vendor', 'OSAT', sorted({c.vendor for c in p.chains}))])


def ate(R, args):
    A = R['ate']
    p = R['plan']
    cases = [c for c in A['cases'] if not args.get('vendor') or c['vendor'] == args['vendor']]
    good = [c for c in cases if c['best']['npv'] > 0]
    sections = [{'type': 'kpis', 'items': [
        K('Tester price', money(A['price']), 'per new consignee tester'),
        K('Running cost', money(A['opex']), 'per tester per month'),
        K('Positive investment cases', str(len(good)), 'NPV > 0 over ' + str(A['months']) + ' months', 'ok' if good else ''),
        K('Short tester time in plan', short(sum(c['gap_units'] for c in cases)), 'units made late', 'warn' if any(c['gap_units'] > 0.5 for c in cases) else 'ok'),
    ]}]
    rows = []
    for c in cases:
        for s in c['scenarios']:
            rows.append({'res': f'OSAT-{c["vendor"]} · {c["step"]}', 'testers': s['testers'], 'moved': s['units_moved'],
                         'rec': s['gap_recovered'], 'saving': s['monthly_saving'],
                         'payback': s['payback'] if s['payback'] and s['payback'] < 1000 else None,
                         'npv': s['npv'], 'roi': s['roi'],
                         'verdict': 'INVEST' if s['npv'] > 0 else ('CAPACITY' if s['gap_recovered'] > 0.5 else 'RENT'),
                         'tone': 'ok' if s['npv'] > 0 else ('warn' if s['gap_recovered'] > 0.5 else '')})
    sections.append(table('Buy or rent: 1 to 4 new consignee testers', [
        col('res', 'OSAT · step'), col('testers', 'New testers', 'int'), col('moved', 'Units moved / month', 'int'),
        col('rec', 'Shortfall recovered / month', 'int'), col('saving', 'Net saving / month', 'money'),
        col('payback', 'Payback (months)', 'num1'), col('npv', 'NPV', 'money'), col('roi', 'ROI %', 'num0'),
        col('verdict', 'Verdict', 'badge', tone='tone')], rows,
        note='INVEST: positive NPV from rental savings. CAPACITY: does not pay back on savings, but would recover tester shortfalls. RENT: keep renting OSAT tester time.'))
    groups = []
    for c in cases:
        groups.append({'title': f'OSAT-{c["vendor"]} · {c["step"]}', 'rows': [
            {'label': 'Testers available', 'cells': [cell(s['have'], '', 'int') for s in c['slack']]},
            {'label': 'Needed incl. buffer', 'cells': [cell(s['want'], '', 'num1') for s in c['slack']]},
            {'label': 'Slack (testers)', 'cells': [(f'{s["slack"]:+.1f}', 'bad' if s['slack'] < 0 else 'ok') for s in c['slack']], 'strong': True},
        ]})
    sections.append(grid('Capacity slack against your buffer', p.months, groups))
    return page('ate', sections, filters=[('vendor', 'OSAT', sorted({c.vendor for c in p.chains}))])


def npi(R, args):
    N = R['npi']['products']
    p = R['plan']
    sections = []
    if not N:
        sections.append(callout('No product has Status = NPI. Set a product to NPI in Products (with an NPIStartDate) to plan it here.'))
    for n in N:
        rows = n['steps'] + n['qual']
        end = max([r.get('readout') or r['end'] for r in rows] + ([n['need_date']] if n['need_date'] else []))
        marks = [(p.as_of, 'today', 'now')]
        if n['need_date']:
            marks.append((n['need_date'], 'customer need', 'need'))
        sections.append({'type': 'kpis', 'items': [
            K(f'{n["sku"]} samples ready', f'{n["samples"]:%d %b %Y}', 'first lots through every step'),
            K('Qualification complete', f'{n["qual_done"]:%d %b %Y}', f'{n["passed"]} of {len(n["qual"])} milestones passed',
              'bad' if n['risk'] else 'ok'),
            K('First customer demand', mlabel(n['first_demand']) if n['first_demand'] else '–', 'from the plan demand'),
            K('Cumulative yield', f'{n["yield_cum"]:.1f}%', 'good units per gross die'),
        ]})
        if n['failed']:
            sections.append(callout(f'<b>Failed:</b> {escape(", ".join(n["failed"]))}. Qualification is not complete until the fix is re-tested: '
                                    f'add a re-test milestone (Order after the failed one) in the NPI qualification plan.', 'bad'))
        if n['need_date'] and n['qual_done'] > n['need_date']:
            late = (n['qual_done'] - n['need_date']).days
            sections.append(callout(f'<b>Risk:</b> qualification ends {late} days after customers need {n["sku"]}. Options: start production at risk, '
                                    f'compress the longest tests (HTOL / HTSL), or agree a later first shipment.', 'bad'))
        sections.append(chart(f'{n["sku"]} timeline', charts.gantt(rows, n['start'] - timedelta(days=5), end + timedelta(days=10), marks),
                              'Blue: fab. Teal: OSAT steps. Orange: qualification tests, with readouts in grey.'))
        st_tone = {'Passed': 'ok', 'Running': 'info', 'Failed': 'bad', 'Planned': ''}
        sections.append(table(f'{n["sku"]} plan', [col('status', 'Status', 'badge', tone='st_t'), col('name', 'Step / milestone'),
                                                   col('start', 'Start', 'date'), col('end', 'Finish', 'date'),
                                                   col('readout', 'Readout done', 'date'), col('slip', 'Slip days', 'int')],
                              [dict(r, readout=r.get('readout'), status=r.get('status', 'Fab' if r['kind'] == 'fab' else 'OSAT'),
                                    st_t=st_tone.get(r.get('status'), ''), slip=r.get('slip') or None) for r in rows], search=False,
                              note='Set Status and ActualEnd in the NPI qualification plan as readouts come in: later milestones re-plan from the actual date.'))
    return page('npi', sections)


# ------------------------------------------------------------------ procurement
def fab_po(R, args):
    F = R['fab_po']
    p = R['plan']
    rows = [r for r in F['rows'] if not args.get('sku') or r['sku'] == args['sku']]
    status = args.get('status')
    if status:
        rows = [r for r in rows if r['status'] == status]
    sections = [{'type': 'kpis', 'items': [
        K('PO lines', str(len(rows)), f'{sum(r["wafers"] for r in rows):,.0f} wafers'),
        K('PO value', money(sum(r['value'] for r in rows)), 'at wafer prices'),
        K('Past cutoff', str(sum(1 for r in rows if r['status'] == 'PAST CUTOFF')), 'confirm with the fab', 'bad'),
        K('Order now', str(sum(1 for r in rows if r['status'] == 'ORDER NOW')), 'after the semi-cutoff', 'warn'),
        K('Upcoming', str(sum(1 for r in rows if r['status'] == 'UPCOMING')), 'within 14 days of the semi-cutoff', 'info'),
    ]}]
    if F['expedite']:
        sections.append(table('Expedite: wafers needed inside fab lead time', [col('sku', 'Product'), col('wafers', 'Wafers', 'int'),
                                                                                col('months', 'Needed at sort in')], F['expedite'],
                              note='New starts cannot arrive in time for these. Ask the fab to expedite WIP, or allocate the shortfall.', search=False))
    sections.append(table('Wafer PO schedule', [
        col('status', 'Status', 'badge', tone='tone'), col('sku', 'Product'), col('start_month', 'Wafer start', 'month'),
        col('out_month', 'Wafers out', 'month'), col('wafers', 'Wafers', 'int'), col('lots', 'Lots', 'int'), col('price', 'Price / wafer', 'money'),
        col('value', 'Value', 'money'), col('semi', 'Reserve by', 'date'), col('cutoff', 'Order by', 'date'),
        col('days_to_cutoff', 'Days to cutoff', 'int'), col('ship_to', 'Ship to')], rows, tid='fabpo',
        note=f'As of {p.as_of:%d %b %Y}. Order by = day {p.s["Fab order cutoff day"]} of the month before the start; reserve by = day {p.s["Fab semi-cutoff day"]} two months before.'))
    sections.append(html('<div class="actions"><a class="btn ghost" href="/export/fab-po.xml">Download PO (XML)</a>'
                         '<a class="btn ghost" href="/export/fab-forecast.xml">Download wafer forecast (XML)</a></div>'))
    return page('fab-po', sections, filters=filter_spec(R, ('sku',)) + [('status', 'Status', ['PAST CUTOFF', 'ORDER NOW', 'UPCOMING', 'PLANNED'])])


def osat_po(R, args):
    O = R['osat_po']
    p = R['plan']
    rows = apply_filters([dict(r) for r in O['rows']], args)
    if args.get('month'):
        rows = [r for r in rows if r['month'] == args['month']]
    for r in rows:
        r['vendor_n'] = f'OSAT-{r["vendor"]}'
    by_v = defaultdict(float)
    for r in rows:
        by_v[r['vendor']] += r['cost']
    sections = [{'type': 'kpis', 'items': [K(f'OSAT-{v} spend', money(c), f'{p.H} months') for v, c in sorted(by_v.items())] +
                 [K('Order now', str(sum(1 for r in rows if r['status'] == 'ORDER NOW')), 'lines after the semi-cutoff', 'warn')]}]
    months = p.months
    series = [(f'OSAT-{v}', [sum(r['cost'] for r in rows if r['vendor'] == v and r['month'] == m) for m in months]) for v in sorted(by_v)]
    sections.append(chart('OSAT spend by month', charts.bars(months, series, unit=' USD', title='OSAT spend')))
    sections.append(table('OSAT work orders', [
        col('status', 'Status', 'badge', tone='tone'), col('vendor_n', 'OSAT'), col('sku', 'Product'), col('month', 'Month', 'month'),
        col('Sort', 'Sort wafers', 'int'), col('Bump', 'Bump wafers', 'int'), col('Assembly', 'Assembly units', 'int'),
        col('Test1', 'Test 1 insertions', 'int'), col('Test2', 'Test 2 insertions', 'int'), col('Pack', 'Pack units', 'int'),
        col('cost', 'Cost', 'money'), col('cutoff', 'Order by', 'date')], rows, tid='osatpo'))
    sections.append(html('<div class="actions"><a class="btn ghost" href="/export/osat-forecast.xml">Download OSAT forecast (XML)</a></div>'))
    return page('osat-po', sections, filters=filter_spec(R) + [('month', 'Month', p.months)])


def substrate(R, args):
    S = R['substrate']
    p = R['plan']
    rows = apply_filters(S['rows'], args)
    months = p.months
    by = defaultdict(list)
    for r in rows:
        by[(r['sku'], r['vendor'])].append(r)
    groups = []
    for (sku, v), rs in sorted(by.items()):
        groups.append({'title': f'{sku} · OSAT-{v} · {rs[0]["material"]}', 'rows': [
            {'label': 'Needed for assembly', 'cells': [cell(r['need']) for r in rs]},
            {'label': 'Used from stock', 'cells': [cell(r['used']) for r in rs]},
            {'label': 'Short', 'cells': [cell(r['short'], 'bad' if r['severity'] in ('CRITICAL', 'HIGH') else 'warn' if r['short'] > 0.5 else '') for r in rs], 'strong': True},
            {'label': 'Usable stock left', 'cells': [cell(r['on_hand_after']) for r in rs]},
        ]})
    sh = [r for r in rows if r['short'] > 0.5]
    sections = [{'type': 'kpis', 'items': [
        K('Months short', str(len(sh)), 'product-OSAT-months', 'bad' if sh else 'ok'),
        K('Units short', short(sum(r['short'] for r in rows)), 'assembly blocked'),
        K('Expiring unused', short(sum(e['units'] for e in S['expired'])), 'units written off', 'warn' if S['expired'] else 'ok'),
        K('Consigned used', short(sum(r['consigned'] for r in rows)), 'supplied by you'),
    ]}, grid('Material against the assembly plan', months, groups, 'Units. Batches are used first-in first-out; expired batches are skipped.')]
    if S['expired']:
        sections.append(table('Expiring unused', [col('sku', 'Product'), col('vendor', 'OSAT'), col('supplier', 'Supplier'),
                                                  col('arrival', 'Arrived', 'month'), col('expiry', 'Expires', 'month'), col('units', 'Units', 'int')],
                              S['expired'], search=False))
    return page('substrate', sections, filters=filter_spec(R))


def cross_flow(R, args):
    C = R['cross']
    p = R['plan']
    rows = [dict(r, moved_h=sum(r['moved'][:p.H]) if r['moved'] else 0, ok='OK' if r['valid'] else 'CHECK',
                 tone='ok' if r['valid'] else 'warn') for r in C['rows']]
    sections = [{'type': 'kpis', 'items': [
        K('Active rules', str(sum(1 for r in rows if r['Status'] == 'Active'))),
        K('Units moved', short(sum(r['moved_h'] for r in rows)), f'{p.H} months'),
        K('Logistics cost', money(sum(r['cost'] for r in rows))),
        K('Rule problems', str(len(C['issues']) + sum(1 for r in rows if not r['valid'])), '', 'bad' if C['issues'] else 'ok'),
    ]}]
    if C['issues']:
        sections.append(callout('<br>'.join(escape(i) for i in C['issues']), 'bad'))
    sections.append(callout('Cross-flow is shown as an overlay: the quantities and cost the rules imply on the current plan. '
                            'The tester plan does not yet move the load between OSATs.', 'info'))
    sections.append(table('Rules and impact', [
        col('ok', 'Check', 'badge', tone='tone'), col('SKU', 'Product'), col('AfterOperation', 'After step'), col('FromVendor', 'From'),
        col('ToVendor', 'To'), col('Percent', '%', 'num0'), col('TransitDays', 'Transit days', 'int'), col('Status', 'Status'),
        col('moved_h', 'Units moved', 'int'), col('cost', 'Logistics cost', 'money')], rows, search=False))
    mx = C['matrix']
    vs = sorted({a for a, _ in mx} | {b for _, b in mx} | set(p.vendors))
    mrows = [dict(frm=f'OSAT-{a}', **{b: mx.get((a, b), 0) for b in vs}) for a in vs]
    sections.append(table('Vendor-to-vendor matrix (units moved)', [col('frm', 'From \\ To')] + [col(b, f'OSAT-{b}', 'int') for b in vs],
                          mrows, search=False))
    return page('cross-flow', sections)


def b2b(R, args):
    B = R['b2b']
    p = R['plan']
    months = p.months
    zones = B['zones']
    groups = []
    gfab = {'title': 'FAB · wafer starts', 'rows': [{'label': r['sku'], 'cells': [cell(v) for v in r['qty']]} for r in B['fab']]}
    groups.append(gfab)
    for sup in sorted({r['supplier'] for r in B['osat']}):
        rs = [r for r in B['osat'] if r['supplier'] == sup and (not args.get('sku') or r['sku'] == args['sku'])]
        groups.append({'title': sup, 'rows': [{'label': f'{r["sku"]} · {r["item"]} ({r["unit"]})', 'cells': [cell(v) for v in r['qty'][:p.H]]} for r in rs]})
    groups.append({'title': 'Testers needed (integer)', 'rows': [{'label': f'{r["supplier"]} · {r["item"].replace(" testers needed", "")}',
                                                                  'cells': [cell(v, '', 'int') for v in r['qty']]} for r in B['tester']]})
    zone_row = {'title': 'Time fence', 'rows': [{'label': 'Zone', 'cells': [(z, 'z-' + z.lower()) for z in zones]}]}
    cal = [('Working day 1-3', 'Refresh demand: customer forecasts, orders, shipment history.'),
           ('Day 4', 'S&OP sign-off of the demand plan and allocations.'),
           ('Day 5', 'Run Plan Yukta: tester plan, wafer plan, ATP. Save a snapshot.'),
           ('Day 6', 'Send the fab its rolling wafer-start forecast; the frozen month is a firm PO (forecast and PO messages).'),
           ('Day 7', 'Send each OSAT its loading forecast and work orders, with testers needed.'),
           ('Day 10', 'Suppliers return their commits in the COMMIT rows.'),
           ('Day 12', 'Compare COMMIT with REQUEST (GAP rows), escalate gaps, re-run the plan with the commits.'),
           ('Daily', 'Receive WIP and shipment reports; update OSAT WIP and Fab WIP.')]
    sections = [{'type': 'kpis', 'items': [
        K('Frozen months', str(p.s['Frozen months']), 'firm orders'), K('Slushy months', str(p.s['Slushy months']), 'within agreed flex'),
        K('Suppliers', str(1 + len({r['supplier'] for r in B['osat']})), 'fab + OSATs')]},
        html('<div class="actions"><a class="btn" href="/export/b2b.xlsx">Download B2B package (.xlsx)</a>'
             '<a class="btn ghost" href="/export/fab-forecast.xml">Fab forecast XML</a>'
             '<a class="btn ghost" href="/export/osat-forecast.xml">OSAT forecast XML</a></div>'),
        grid('Supplier requests by month', months, [zone_row] + groups),
        table('Monthly B2B workflow', [col('when', 'When'), col('what', 'What happens')],
              [{'when': a, 'what': b} for a, b in cal], search=False)]
    return page('b2b', sections, filters=filter_spec(R, ('sku',)))


# ------------------------------------------------------------------ analytics
def pva(R, args):
    P = R['pva']
    rows = [dict(r, tone=('bad' if (r['attainment'] or 100) < 90 else 'warn' if (r['attainment'] or 100) < 97 else 'ok'),
                 att_t=f'{r["attainment"]:.1f}%' if r['attainment'] is not None else 'no plan') for r in P['rows']]
    if args.get('vendor'):
        rows = [r for r in rows if r['Vendor'] == args['vendor']]
    tot_p = sum(r['planned'] or 0 for r in rows)
    tot_a = sum(float(r['ActualUnits']) for r in rows)
    sections = [{'type': 'kpis', 'items': [
        K('Attainment', f'{tot_a / tot_p * 100:.1f}%' if tot_p else '–', 'actual ÷ plan, all rows', 'ok' if tot_p and tot_a / tot_p > .97 else 'warn'),
        K('Units missed', short(max(0, tot_p - tot_a))),
        K('Disruptions', str(sum(1 for r in rows if r['Disruption'] != 'None')), 'rows with a reported cause'),
    ] + [K(f'OSAT-{v["vendor"]} reliability', f'{v["score"]:.1f}', f'attain {v["attainment"]:.0f}% · OEE {v["oee"]:.0f}%') for v in P['vendors']]}]
    months = sorted({r['Month'] for r in rows})
    series = [(f'OSAT-{v}', [sum(float(r['ActualUnits']) for r in rows if r['Vendor'] == v and r['Month'] == m and r['Operation'] == 'Pack') for m in months])
              for v in sorted({r['Vendor'] for r in rows})]
    planl = [sum(r['planned'] or 0 for r in rows if r['Month'] == m and r['Operation'] == 'Pack') for m in months]
    if months:
        sections.append(chart('Pack output: actual by OSAT against the frozen plan', charts.bars(months, series, lines=[('Plan', planl)], title='Plan vs actual')))
    sections.append(table('Recovery actions', [col('month', 'Month', 'month'), col('vendor', 'OSAT'), col('sku', 'Product'), col('op', 'Step'),
                                               col('attainment', 'Attainment %', 'num1'), col('gap', 'Units missed', 'int'),
                                               col('cause', 'Cause'), col('action', 'Recommended action')],
                          [a for a in P['actions'] if not args.get('vendor') or a['vendor'] == args['vendor']], search=False,
                          empty='Every row is at 95% of plan or better.'))
    sections.append(table('Plan vs actual detail', [col('att_t', 'Attainment', 'badge', tone='tone'), col('Month', 'Month', 'month'),
                                                    col('Vendor', 'OSAT'), col('SKU', 'Product'), col('Operation', 'Step'),
                                                    col('planned', 'Planned', 'int'), col('ActualUnits', 'Actual', 'int'),
                                                    col('oee', 'OEE %', 'num1'), col('AvailabilityPct', 'Avail. %', 'num1'),
                                                    col('PerformancePct', 'Perf. %', 'num1'), col('QualityPct', 'Quality %', 'num1'),
                                                    col('DisruptionDays', 'Disruption days', 'num1'), col('Disruption', 'Disruption')], rows))
    return page('pva', sections, filters=[('vendor', 'OSAT', sorted({r['Vendor'] for r in P['rows']}))])


def cost(R, args):
    Cc = R['cost']
    p = R['plan']
    spend = apply_filters([dict(r) for r in Cc['spend']], args)
    tot = sum(r['cost'] for r in spend)
    by_proc = defaultdict(float)
    for r in spend:
        by_proc[r['process']] += r['cost']
    sections = [{'type': 'kpis', 'items': [K('Total spend', money(tot), f'{p.H} months')] +
                 [K(k, money(v), f'{v / tot * 100:.0f}% of spend' if tot else '') for k, v in sorted(by_proc.items(), key=lambda kv: -kv[1])][:5]}]
    months = p.months
    procs = ['Fab'] + FLOW_ORDER
    series = [(pr, [sum(r['cost'] for r in spend if r['process'] == pr and r['month'] == m) for m in months]) for pr in procs if by_proc.get(pr)]
    sections.append(chart('Spend by process', charts.bars(months, series, unit=' USD', title='Spend')))
    std = [dict(r, vendor_n=('All' if r['vendor'] == '*' else f'OSAT-{r["vendor"]}')) for r in Cc['std']]
    std = apply_filters(std, args)
    sections.append(table('Standard cost per good unit', [col('sku', 'Product'), col('vendor_n', 'OSAT'), col('gupw', 'Good units / wafer', 'int'),
                                                          col('Fab', 'Wafer', 'money4'), col('Sort', 'Sort', 'money4'), col('Bump', 'Bump', 'money4'),
                                                          col('Assembly', 'Assembly', 'money4'), col('Test1', 'Test 1', 'money4'),
                                                          col('Test2', 'Test 2', 'money4'), col('Pack', 'Pack', 'money4'),
                                                          col('total', 'Total', 'money4')], std, search=False,
                          note='Each step\'s price divided by the yields from that step to finished goods; test steps include retest.'))
    agg = defaultdict(lambda: {'qty': 0.0, 'cost': 0.0})
    for r in spend:
        k = (r['vendor'], r['process'], r['sku'], r['unit'])
        agg[k]['qty'] += r['qty']
        agg[k]['cost'] += r['cost']
    rows = [{'vendor': 'FAB' if v == 'FAB' else f'OSAT-{v}', 'process': pr, 'sku': s, 'unit': u, 'qty': d['qty'], 'cost': d['cost'],
             'rate': d['cost'] / d['qty'] if d['qty'] else 0} for (v, pr, s, u), d in sorted(agg.items())]
    sections.append(table('Spend by supplier, process and product', [col('vendor', 'Supplier'), col('process', 'Process'), col('sku', 'Product'),
                                                                     col('qty', 'Quantity', 'int'), col('unit', 'Unit'), col('rate', 'Avg. price', 'money4'),
                                                                     col('cost', 'Spend', 'money')], rows))
    return page('cost', sections, filters=filter_spec(R))


def pnl(R, args):
    P = R['pnl']
    p = R['plan']
    try:
        yl = max(-50.0, min(100.0, float(args.get('yield_loss') or 0)))
    except ValueError:
        yl = 0.0
    rows = [dict(r, cogs=r['cogs'] * (1 + yl / 100)) for r in P['rows']]
    rows = [r for r in rows if not args.get('sku') or r['sku'] == args['sku']]
    if args.get('customer'):
        rows = [r for r in rows if r['customer'] == args['customer']]
    for r in rows:
        r['gm'] = r['revenue'] - r['cogs']
        r['gmp'] = r['gm'] / r['revenue'] * 100 if r['revenue'] else 0
    rev = sum(r['revenue'] for r in rows)
    cg = sum(r['cogs'] for r in rows)
    lost = [l for l in P['lost'] if not args.get('sku') or l['sku'] == args['sku']]
    sections = [{'type': 'kpis', 'items': [
        K('Revenue', money(rev), f'{p.H} months, planned shipments'), K('COGS', money(cg), f'standard cost{f" +{yl:.0f}% yield loss" if yl else ""}'),
        K('Gross margin', money(rev - cg), f'{(rev - cg) / rev * 100:.1f}%' if rev else '', 'ok' if rev - cg > 0 else 'bad'),
        K('Revenue lost to shortfalls', money(sum(l['revenue'] for l in lost)) if lost else 'None', 'supply short of demand', 'bad' if lost else 'ok'),
    ]}]
    sections.append(html(f'<form class="inline-form" method="get"><input type="hidden" name="sku" value="{escape(args.get("sku") or "")}">'
                         f'<label>Yield-loss sensitivity <input type="number" name="yield_loss" value="{yl:g}" step="1" min="-50" max="100"> %</label>'
                         f'<button class="btn ghost" type="submit">Apply</button></form>'))
    months = p.months
    series = [(s, [sum(r['gm'] for r in rows if r['sku'] == s and r['month'] == m) for m in months]) for s in sorted({r['sku'] for r in rows})]
    sections.append(chart('Gross margin by product', charts.bars(months, [(n, [max(0, v) for v in vs]) for n, vs in series], unit=' USD',
                                                                 lines=[('Revenue', [sum(r['revenue'] for r in rows if r['month'] == m) for m in months])],
                                                                 title='Gross margin')))

    def agg(key):
        d = defaultdict(lambda: {'units': 0.0, 'revenue': 0.0, 'cogs': 0.0})
        for r in rows:
            x = d[r[key]]
            x['units'] += r['units']
            x['revenue'] += r['revenue']
            x['cogs'] += r['cogs']
        out = []
        for k, x in sorted(d.items(), key=lambda kv: -(kv[1]['revenue'] - kv[1]['cogs'])):
            gm = x['revenue'] - x['cogs']
            out.append(dict(name=k, units=x['units'], revenue=x['revenue'], cogs=x['cogs'], gm=gm,
                            gmp=gm / x['revenue'] * 100 if x['revenue'] else 0, flag='LOSS' if gm < 0 else 'OK', tone='bad' if gm < 0 else 'ok',
                            asp=x['revenue'] / x['units'] if x['units'] else 0, unit_cost=x['cogs'] / x['units'] if x['units'] else 0))
        return out
    c = [col('flag', '', 'badge', tone='tone'), col('name', 'Name'), col('units', 'Units', 'int'), col('asp', 'ASP', 'money4'),
         col('unit_cost', 'Unit cost', 'money4'), col('revenue', 'Revenue', 'money'), col('cogs', 'COGS', 'money'), col('gm', 'Gross margin', 'money'),
         col('gmp', 'GM %', 'num1')]
    sections.append(cols2(table('By product', c, agg('sku'), search=False), table('By customer', c, agg('customer'), search=False)))
    if lost:
        sections.append(table('Revenue lost to supply shortfalls', [col('sku', 'Product'), col('units', 'Units short', 'int'),
                                                                     col('revenue', 'Revenue', 'money'), col('margin', 'Margin', 'money')], lost, search=False))
    return page('pnl', sections, filters=filter_spec(R, ('sku',)) + [('customer', 'Customer', sorted({r['customer'] for r in P['rows']}))])


def snapshots(R, args, ws):
    p = R['plan']
    snaps = ws.get('snapshots', [])
    from .cockpit import plan_snapshot_data
    cur = plan_snapshot_data(R)
    sel = args.get('snap')
    s = next((x for x in snaps if x['id'] == sel), snaps[-1] if snaps else None)
    rows = []
    if s:
        old = s['data']
        keys = sorted(set(cur) | set(old))
        for k in keys:
            sku, m = k.split('|')
            a, b = old.get(k, {}), cur.get(k, {})
            for metric, label in (('demand', 'Demand'), ('Test1', 'Test 1 starts'), ('wafer_starts', 'Wafer starts'), ('ship', 'Shipped'), ('short', 'Short')):
                va, vb = a.get(metric, 0) or 0, b.get(metric, 0) or 0
                if abs(vb - va) > 0.5:
                    rows.append({'sku': sku, 'month': m, 'metric': label, 'snap': va, 'now': vb, 'delta': vb - va,
                                 'pct': (vb - va) / va * 100 if va else None, 'tone': 'up' if vb > va else 'down'})
    return page('snapshots', [], extra={'template': 'snapshots.html', 'snaps': snaps, 'sel': s, 'rows': rows})


# ------------------------------------------------------------------ overrides (USP)
OVERRIDE_TABLES = ('fleet_changes', 'hardware_arrivals', 'capacity_overrides', 'yield_overrides')


def overrides(R, Rb, args, ws):
    """Tester & capacity overrides: entry points plus the plan with and without them."""
    p, pb = R['plan'], Rb['plan']
    t = ws['tables']
    keys = sorted(p.alloc, key=lambda k: (k[0], TEST_OPS.index(k[1])))
    if not keys:
        return page('overrides', [], extra={'template': 'overrides.html', 'kpis': [K('Nothing to plan', '–', 'add products and test times first', 'warn')],
                                            'chart': '<p class="muted">No tester steps are planned yet.</p>', 'timeline': None, 'impact': [], 'cust': [],
                                            'sel': '', 'keys': [], 'forms': override_forms(R, ws), 'apply': p.apply, 'hw_limit': p.hw_limit})
    sel = args.get('res')
    if sel not in [f'{v}|{s}' for v, s in keys]:
        sel = max(keys, key=lambda k: max(x['load_util'] for x in p.alloc[k]['summary'][:p.H]))
        sel = f'{sel[0]}|{sel[1]}'
    sv, ss = sel.split('|')
    a, ab = p.alloc[(sv, ss)]['summary'][:p.H], pb.alloc.get((sv, ss), {'summary': [None] * p.H})['summary'][:p.H]
    hw = p.hw_ready.get((sv, ss))
    months = p.months

    def tot(alloc, key, H):
        return sum(x[key] for k in alloc for x in alloc[k]['summary'][:H])
    short_now, short_base = R['home']['short'], Rb['home']['short']
    gap_now, gap_base = tot(p.alloc, 'gap', p.H), tot(pb.alloc, 'gap', p.H)
    left_now = sum(p.alloc[k]['summary'][p.H - 1]['late_left'] for k in p.alloc)
    left_base = sum(pb.alloc[k]['summary'][p.H - 1]['late_left'] for k in pb.alloc)
    cap_now = sum(x['total'] for k in p.alloc for x in p.alloc[k]['summary'][:p.H])
    cap_base = sum(x['total'] for k in pb.alloc for x in pb.alloc[k]['summary'][:p.H])
    lost_now = sum(l['revenue'] for l in R['pnl']['lost'])
    lost_base = sum(l['revenue'] for l in Rb['pnl']['lost'])
    counts = {k: len(t.get(k, [])) for k in OVERRIDE_TABLES}
    kp = [
        K('Overrides entered', str(sum(counts.values())), f'{counts["fleet_changes"]} tester · {counts["hardware_arrivals"]} hardware · '
          f'{counts["capacity_overrides"]} test time · {counts["yield_overrides"]} yield', 'info'),
        K('Customer shortfall', f'{short(short_now) if short_now > 0.5 else "None"}', f'without overrides: {short(short_base) if short_base > 0.5 else "none"}',
          'bad' if short_now > 0.5 else 'ok'),
        K('Test units made late', short(gap_now) if gap_now > 0.5 else 'None', f'without overrides: {short(gap_base)}', 'warn' if gap_now > 0.5 else 'ok'),
        K('Still owed at horizon end', short(left_now) if left_now > 0.5 else 'None', f'without overrides: {short(left_base)}', 'bad' if left_now > 0.5 else 'ok'),
        K('Tester capacity added', f'{cap_now - cap_base:+,.0f}', 'tester-months over the horizon, all OSATs'),
        K('Revenue protected', money(max(0.0, lost_base - lost_now)), 'lost revenue avoided by the overrides', 'ok' if lost_base - lost_now > 0.5 else ''),
    ]
    if not p.apply:
        kp.insert(0, K('Overrides are OFF', 'Baseline', 'every module is planning without overrides', 'warn'))
    # capacity timeline chart for the selected OSAT and step
    cons = [x['consignee'] for x in a]
    ncon = [x['non_consignee'] for x in a]
    need = [x['needed'] for x in a]
    base_tot = [x['total'] if x else 0 for x in ab]
    chart_html = charts.bars(months, [('Consignee testers', cons), ('Non-consignee testers', ncon)],
                             lines=[('Testers needed (load)', need), ('Testers without overrides', base_tot)],
                             title='Tester capacity timeline')
    rows = [
        {'label': 'Overrides this month', 'cells': [('; '.join(x['events']) if x['events'] else '', 'ev' if x['events'] else '') for x in a]},
        {'label': 'Testers without overrides', 'cells': [(f'{x["consignee"]}+{x["non_consignee"]}' if x else '–', '') for x in ab]},
        {'label': 'Testers with overrides', 'cells': [(f'{x["consignee"]}+{x["non_consignee"]}', 'info' if b and x['total'] != b['total'] else '') for x, b in zip(a, ab)], 'strong': True},
    ]
    if hw:
        rows.append({'label': 'Consignee testers with a full hardware kit', 'cells': [cell(hw[i], 'bad' if hw[i] < a[i]['fleet_consignee'] else 'ok', 'int') for i in range(p.H)]})
    rows += [
        {'label': 'Testers needed (load)', 'cells': [cell(x['needed'], '', 'num1') for x in a]},
        {'label': 'Load % without overrides', 'cells': [cell(x['load_util'], util_tone(x['load_util']), 'pct') if x else ('–', '') for x in ab]},
        {'label': 'Load % with overrides', 'cells': [cell(x['load_util'], util_tone(x['load_util']), 'pct') for x in a], 'strong': True},
        {'label': 'Pull-in built (with overrides)', 'cells': [cell(x['pullin'], 'info' if x['pullin'] > 0.5 else '') for x in a]},
        {'label': 'Made late, without overrides', 'cells': [cell(x['gap'], 'bad' if x['gap'] > 0.5 else '') if x else ('–', '') for x in ab]},
        {'label': 'Made late, with overrides', 'cells': [cell(x['gap'], 'bad' if x['gap'] > 0.5 else '') for x in a]},
        {'label': 'Still owed, with overrides', 'cells': [cell(x['late_left'], 'warn' if x['late_left'] > 0.5 else '') for x in a]},
    ]
    per_sku = []
    for sku in sorted(p.alloc[(sv, ss)]['upm']):
        u = p.alloc[(sv, ss)]['upm'][sku][:p.H]
        per_sku.append({'label': f'{sku}: units per tester-month', 'cells': [cell(v, 'info' if i and abs(v - u[i - 1]) > 1 else '') for i, v in enumerate(u)]})
    timeline = grid(f'OSAT-{sv} · {ss}: capacity with and without overrides', months,
                    [{'title': '', 'rows': rows}, {'title': 'Throughput (changes with test-time, sites and OEE overrides)', 'rows': per_sku}],
                    'Testers shown as consignee + non-consignee. Blue cells: changed by an override.')
    impact = []
    for k in keys:
        s_now, s_b = p.alloc[k]['summary'][:p.H], pb.alloc.get(k, {'summary': []})['summary'][:p.H]
        impact.append({'res': f'OSAT-{k[0]} · {k[1]}', 'key': f'{k[0]}|{k[1]}',
                       'cap_b': sum(x['total'] for x in s_b), 'cap_n': sum(x['total'] for x in s_now),
                       'peak_b': max([x['load_util'] for x in s_b] or [0]), 'peak_n': max(x['load_util'] for x in s_now),
                       'gap_b': sum(x['gap'] for x in s_b), 'gap_n': sum(x['gap'] for x in s_now),
                       'pull_b': sum(x['pullin'] for x in s_b), 'pull_n': sum(x['pullin'] for x in s_now),
                       'changes': sum(len(x['events']) for x in s_now)})
    cust = []
    for sku in sorted(p.products):
        sn = sum(max(fg['short'][:p.H]) for (s_, v), fg in p.fg.items() if s_ == sku)
        sb = sum(max(fg['short'][:p.H]) for (s_, v), fg in pb.fg.items() if s_ == sku)
        if sn > 0.5 or sb > 0.5:
            cust.append({'sku': sku, 'base': sb, 'now': sn, 'delta': sn - sb})
    forms = override_forms(R, ws)
    return page('overrides', [], extra={'template': 'overrides.html', 'kpis': kp, 'chart': chart_html, 'timeline': timeline,
                                        'impact': impact, 'cust': cust, 'sel': sel, 'keys': [f'{v}|{s}' for v, s in keys],
                                        'forms': forms, 'apply': p.apply, 'hw_limit': p.hw_limit})


def override_forms(R, ws):
    p = R['plan']
    t = ws['tables']
    vendors = sorted({r['Vendor'] for r in t['vendors']})
    skus = sorted(p.products)
    months = p.months_x
    hw_types = sorted({r['HardwareType'] for r in t['hardware']})
    cur = {}
    for (v, sku, st), c in p.cap.items():
        cur[f'{v}|{sku}|{st}'] = {k: c[k] for k in ('TestTimeSec', 'Sites', 'IndexTimeSec', 'OEE')}
    flow = {f'{r["SKU"]}|{r["Operation"]}': {'Yield': r['Yield'], 'ReworkRate': r['ReworkRate']} for r in t['process_flow']}
    return {'vendors': vendors, 'skus': skus, 'months': months, 'hw_types': hw_types, 'current': cur, 'flow': flow,
            'rows': {k: list(enumerate(t.get(k, []))) for k in OVERRIDE_TABLES}}


# ------------------------------------------------------------------ pull-in strategy live preview
def sku_pullin_stats(R, sku):
    p = R['plan']
    H = p.H
    gap, pull, catch, load = [0.0] * H, [0.0] * H, [0.0] * H, [0.0] * H
    for ch in p.chains:
        if ch.sku != sku:
            continue
        for op in ('Test1', 'Test2'):
            if op in ch.ops:
                a = ch.levels[op]['alloc']
                for i in range(H):
                    gap[i] += a['gap'][i]
                    pull[i] += a['pullin'][i]
                    catch[i] += a['catchup'][i]
                    load[i] += a['load'][i]
    dem, ship, shortv, fc = [0.0] * H, [0.0] * H, [0.0] * H, list(p.fc.get(sku, [0.0] * p.HX)[:H])
    for (s, v), f in p.fg.items():
        if s == sku:
            for i in range(H):
                dem[i] += f['demand'][i]
                ship[i] += f['ship'][i]
                shortv[i] += f['short'][i]
    on_time = [d - max(0.0, sh - (shortv[i - 1] if i else 0.0)) for i, (d, sh) in enumerate(zip(dem, shortv))]
    # build-ahead stock at test = cumulative (made - needed) when positive
    made = [0.0] * H
    for ch in p.chains:
        if ch.sku == sku:
            for op in ('Test1', 'Test2'):
                if op in ch.ops:
                    a = ch.levels[op]['alloc']
                    c = 0.0
                    for i in range(H):
                        c += a['prod'][i] - a['load'][i]
                        made[i] += max(0.0, c)
    tot_dem = sum(dem)
    return {'gap': gap, 'pull': pull, 'catch': catch, 'load': load, 'dem': dem, 'ship': ship, 'short': shortv, 'fc': fc,
            'ahead': made, 'gap_total': sum(gap), 'pull_total': sum(pull), 'peak_ahead': max(made) if made else 0,
            'achieve': (sum(ship) / tot_dem * 100) if tot_dem else 100.0,
            'on_time': (sum(min(d, o) for d, o in zip(dem, on_time)) / tot_dem * 100) if tot_dem else 100.0,
            'short_peak': max(shortv) if shortv else 0.0}


def pullin_preview_html(R_saved, R_new, sku):
    from .cockpit import strategy_label, pullin_intensity
    a, b = sku_pullin_stats(R_saved, sku), sku_pullin_stats(R_new, sku)
    p = R_new['plan']
    pr = p.products[sku]
    lab = strategy_label(pr.get('PullInWeight'), pr['PullIn'])
    inten, nc = pullin_intensity(pr.get('PullInWeight'))
    eff = (min(float(pr['ServiceLevelPct']), float(pr['MaxPullInPct'])) * inten) if pr['PullIn'] == 'Y' and lab != 'Avoid' else 0

    def delta(x, y, unit='', pct=False, good_up=True):
        d = y - x
        if abs(d) < (0.05 if pct else 0.5):
            return '<span class="muted">same as saved</span>'
        tone = 'ok' if (d > 0) == good_up else 'bad'
        txt = f'{d:+.1f} pts' if pct else f'{"+" if d > 0 else "−"}{short(abs(d))}{unit}'
        return f'<span style="color:var(--{tone})">{txt} vs saved</span>'
    tones = {'Aggressive': 'bad', 'Moderate': 'warn', 'Conservative': 'ok', 'Neutral': 'info', 'Avoid': ''}
    k = [
        ('Strategy', lab, f'{eff:.0f}% of a shortfall may be built early{"; may use non-consignee testers" if nc and eff else ""}', tones.get(lab, '')),
        ('Total gap', short(b['gap_total']) if b['gap_total'] > 0.5 else 'None', delta(a['gap_total'], b['gap_total'], good_up=False), 'bad' if b['gap_total'] > 0.5 else 'ok'),
        ('Pull-in production', short(b['pull_total']) if b['pull_total'] > 0.5 else 'None', delta(a['pull_total'], b['pull_total']), 'info'),
        ('Forecast achievement', f'{b["on_time"]:.1f}%', 'on time · ' + delta(a['on_time'], b['on_time'], pct=True), 'ok' if b['on_time'] > 99.5 else 'warn'),
        ('Peak build-ahead stock', short(b['peak_ahead']) if b['peak_ahead'] > 0.5 else 'None', 'cash tied up · ' + delta(a['peak_ahead'], b['peak_ahead'], good_up=False), 'warn' if b['peak_ahead'] > 0.5 else ''),
        ('Customers short (peak)', short(b['short_peak']) if b['short_peak'] > 0.5 else 'None', delta(a['short_peak'], b['short_peak'], good_up=False), 'bad' if b['short_peak'] > 0.5 else 'ok'),
    ]
    kh = '<div class="kpis">' + ''.join(f'<div class="kpi {t}"><div class="label">{escape(l)}</div><div class="value">{escape(v)}</div><div class="sub">{s}</div></div>'
                                          for l, v, s, t in k) + '</div>'
    months = p.months
    c1 = charts.bars(months, [('Pull-in production', b['pull']), ('Gap (made late)', b['gap'])],
                     lines=[('Build-ahead stock', b['ahead'])], stacked=False, title='Gap and pull-in')
    cum = lambda xs: [sum(xs[:i + 1]) for i in range(len(xs))]
    c2 = charts.lines(months, [('Cumulative demand', cum(b['dem']), False), ('Cumulative shipped', cum(b['ship']), False),
                               ('Cumulative customer forecast', cum(b['fc']), True)], title='Cumulative')
    return (kh + f'<div class="cols"><section class="panel"><h2>{escape(sku)}: gap vs pull-in production</h2>'
            f'<p class="sub">Test units across all OSATs. Bars: built early, made late. Line: stock built ahead.</p>{c1}</section>'
            f'<section class="panel"><h2>{escape(sku)}: cumulative demand vs shipments</h2><p class="sub">Shipped below demand = customers short.</p>{c2}</section></div>')


# ------------------------------------------------------------------ dashboards
def _idle(p, v, st, i):
    a = p.alloc.get((v, st))
    if not a:
        return 0.0
    x = a['summary'][i]
    return max(0.0, x['total'] - x['used'])


def m1_dashboard(R, args):
    """Module 1 analytics dashboard: gaps, pull-in, cumulative achievement, vendor split, root cause, recovery plan."""
    p = R['plan']
    H, months = p.H, p.months
    fs, fv, fstep = args.get('sku'), args.get('vendor'), args.get('step')
    lines = [l for l in R['testing']['lines'] if (not fs or l['sku'] == fs) and (not fv or l['vendor'] == fv) and (not fstep or l['step'] == fstep)]
    load = sum(l['ins_req'] for l in lines)
    made = sum(l['prod'] for l in lines)
    gap = sum(l['gap'] for l in lines)
    pull = sum(l['pullin'] for l in lines)
    nc_t = sum(l['tn'] for l in lines)
    all_t = sum(l['tc'] + l['tn'] for l in lines) or 1
    dem = [0.0] * H
    ship = [0.0] * H
    shortv = [0.0] * H
    fc = [0.0] * H
    for (sku, v), f in p.fg.items():
        if (fs and sku != fs) or (fv and v != fv):
            continue
        for i in range(H):
            dem[i] += f['demand'][i]
            ship[i] += f['ship'][i]
            shortv[i] += f['short'][i]
    for sku in p.products:
        if not fs or sku == fs:
            share = sum(ch.share for ch in p.chains if ch.sku == sku and (not fv or ch.vendor == fv))
            for i in range(H):
                fc[i] += p.fc.get(sku, [0.0] * p.HX)[i] * share
    tot_dem = sum(dem) or 1
    ontime = sum(d - max(0.0, s - (shortv[i - 1] if i else 0)) for i, (d, s) in enumerate(zip(dem, shortv))) / tot_dem * 100
    sections = [{'type': 'kpis', 'items': [
        K('Test load', short(load), 'insertions incl. retest'),
        K('Made', short(made), f'{made / load * 100:.1f}% of load' if load else ''),
        K('Gap (made late)', short(gap) if gap > 0.5 else 'None', 'after pull-in', 'bad' if gap > 0.5 else 'ok'),
        K('Pull-in production', short(pull) if pull > 0.5 else 'None', f'{pull / (pull + gap) * 100:.0f}% of the crunch covered early' if pull + gap > 0.5 else '', 'info'),
        K('Forecast achievement', f'{ontime:.1f}%', 'demand shipped on time', 'ok' if ontime > 99.5 else 'warn'),
        K('Non-consignee share', f'{nc_t / all_t * 100:.0f}%', 'of tester-months used', 'warn' if nc_t / all_t > .1 else ''),
    ]}]
    by_v = defaultdict(float)
    for l in lines:
        by_v[f'OSAT-{l["vendor"]}'] += l['prod']
    by_s = defaultdict(float)
    for l in lines:
        by_s[l['sku']] += l['prod']
    sections.append(cols2(chart('Production by OSAT', charts.donut(sorted(by_v.items()), 'Production by OSAT')),
                          chart('Production by product', charts.donut(sorted(by_s.items(), key=lambda kv: -kv[1]), 'Production by product'))))
    g_m = [sum(l['gap'] for l in lines if l['month'] == m) for m in months]
    p_m = [sum(l['pullin'] for l in lines if l['month'] == m) for m in months]
    c_m = [sum(l['covered'] for l in lines if l['month'] == m) for m in months]
    sections.append(chart('Gap and pull-in by month', charts.bars(months, [('Pull-in production (made early)', p_m), ('Gap (made late)', g_m)],
                                                                 lines=[('Shortfall covered by pull-in', c_m)], stacked=False, title='Gap and pull-in'),
                          'Pull-in bars sit in the months the testers build ahead; the line shows the later months that stock covers.'))
    cum = lambda xs: [sum(xs[:i + 1]) for i in range(len(xs))]
    sections.append(chart('Cumulative forecast, demand and production', charts.lines(
        months, [('Cumulative customer forecast', cum(fc), True), ('Cumulative demand', cum(dem), False), ('Cumulative shipped', cum(ship), False)],
        title='Cumulative'), 'Shipped below demand means customers are short; above forecast means booked orders exceed the forecast.'))
    vend = sorted({l['vendor'] for l in lines})
    sections.append(chart('Tester-months used by OSAT', charts.bars(months, [(f'OSAT-{v}', [sum(l['tc'] + l['tn'] for l in lines if l['vendor'] == v and l['month'] == m) for m in months]) for v in vend],
                                                                    lines=[('Tester-months available', [sum(x['total'] for (vv, st), a in p.alloc.items() if vv in vend and st != 'Sort' and (not fstep or st == fstep) for x in a['summary'][i:i + 1]) for i in range(H)])],
                                                                    title='Testers used')))
    # root cause and recovery plan
    res_gap = defaultdict(float)
    sku_gap = defaultdict(float)
    for l in lines:
        res_gap[(l['vendor'], l['step'])] += l['gap']
        sku_gap[l['sku']] += l['gap']
    insights = []
    if gap <= 0.5:
        insights.append('<b>No test shortfall.</b> Every final-test step can make its load in the month it is needed' +
                        (f', with {short(pull)} units built ahead by pull-in.' if pull > 0.5 else '.'))
    else:
        top = sorted(res_gap.items(), key=lambda kv: -kv[1])
        (tv, ts), tg = top[0]
        gm = [x['month'] for x in p.alloc[(tv, ts)]['summary'][:H] if x['gap'] > 0.5]
        pk = max(p.alloc[(tv, ts)]['summary'][:H], key=lambda x: x['load_util'])
        insights.append(f'<b>{tg / gap * 100:.0f}% of the shortfall is at OSAT-{tv} {ts}</b>, in {", ".join(mlabel(m) for m in gm[:4])}{"…" if len(gm) > 4 else ""}; '
                        f'load peaks at {pk["load_util"]:.0f}% in {mlabel(pk["month"])} ({pk["needed"]:.1f} testers needed, {pk["total"]} available).')
        drv = sorted(sku_gap.items(), key=lambda kv: -kv[1])
        insights.append('<b>Products short:</b> ' + ', '.join(f'{s} {short(g)}' for s, g in drv if g > 0.5) +
                        '. Lower-priority products lose testers first (priority on Products / Pull-in Setup).')
        ramp = []
        for s in p.products:
            d = p.dem.get(s, [0] * H)
            if d[0] > 0 and max(d[:H]) > 1.2 * d[0]:
                ramp.append(f'{s} +{(max(d[:H]) / d[0] - 1) * 100:.0f}%')
        if ramp:
            insights.append('<b>Demand driver:</b> ramp from the first month to the peak: ' + ', '.join(ramp) + '.')
        insights.append(f'<b>Pull-in</b> covered {pull / (pull + gap) * 100:.0f}% of the crunch early; the rest is made late (catch-up). '
                        'Raise the pull-in weight or cap on Pull-in Setup, or add capacity on Tester & Capacity Overrides.')
        if not p.allow_nc:
            insights.append('<b>Non-consignee testers are switched off</b> in Plan settings; allowing them adds OSAT capacity at a higher rate.')
    sections.append(html('<section class="panel"><h2>Gap analysis &amp; insights</h2><ul class="insights">' + ''.join(f'<li>{x}</li>' for x in insights) + '</ul></section>'))
    plan_rows = []
    for i, m in enumerate(months):
        gm_ = [l for l in lines if l['month'] == m and l['gap'] > 0.5]
        g = sum(l['gap'] for l in gm_)
        pu = sum(l['pullin'] for l in lines if l['month'] == m)
        if g <= 0.5 and pu <= 0.5:
            continue
        if g > 0.5:
            worst = max(gm_, key=lambda l: l['gap'])
            v, st, sku = worst['vendor'], worst['step'], worst['sku']
            alt = []
            for ch in p.chains:
                if ch.sku == sku and ch.vendor != v and st in ch.ops:
                    idle = _idle(p, ch.vendor, st, i)
                    if idle > 0.2:
                        u = p.upm(ch.vendor, sku, st, i)[0]
                        alt.append((idle * u, ch.vendor, idle))
            alt.sort(reverse=True)
            if alt and alt[0][0] >= 0.3 * worst['gap']:
                act = f'Move {short(min(worst["gap"], alt[0][0]))} {sku} units to OSAT-{alt[0][1]} {st} ({alt[0][2]:.1f} testers idle there)'
            else:
                need_t = worst['gap'] / worst['upm'] if worst['upm'] else 0
                act = f'Add {max(1, round(need_t + 0.49))} tester(s) at OSAT-{v} {st} from {mlabel(m)} (enter it on Overrides), or allow non-consignee time'
            driver = f'OSAT-{v} {st} · {sku}'
        else:
            act, driver = 'Spare tester time builds ahead for a later crunch', 'Pull-in month'
        plan_rows.append({'month': m, 'gap': g, 'pull': pu, 'net': pu - g, 'driver': driver, 'action': act, 'tone': 'bad' if g > 0.5 else 'info',
                          'kind': 'GAP' if g > 0.5 else 'PULL-IN'})
    sections.append(table('Monthly gap breakdown & recovery plan', [
        col('kind', '', 'badge', tone='tone'), col('month', 'Month', 'month'), col('gap', 'Gap', 'int'), col('pull', 'Pull-in', 'int'),
        col('net', 'Net (pull-in − gap)', 'int'), col('driver', 'Primary driver'), col('action', 'Recommended action')],
        plan_rows, search=False, empty='No gap and no pull-in in any month.'))
    opt = []
    for sku in sorted(p.products):
        chs = [ch for ch in p.chains if ch.sku == sku]
        if len(chs) < 2 or (fs and sku != fs):
            continue
        g_by = {ch.vendor: sum(ch.levels['Test1']['alloc']['gap'][:H]) for ch in chs if 'Test1' in ch.ops}
        if sum(g_by.values()) <= 0.5:
            continue
        gap_months = [i for i in range(H) if sum(ch.levels['Test1']['alloc']['gap'][i] for ch in chs if 'Test1' in ch.ops) > 0.5]
        idle_units = {ch.vendor: (0.0 if g_by.get(ch.vendor, 0) > 0.5 else
                                  sum(_idle(p, ch.vendor, 'Test1', i) * p.upm(ch.vendor, sku, 'Test1', i)[0] for i in gap_months)) for ch in chs}
        tot_load = sum(sum(ch.levels['Test1']['alloc']['load'][:H]) for ch in chs) or 1
        for ch in chs:
            v = ch.vendor
            ld = sum(ch.levels['Test1']['alloc']['load'][:H])
            move = -g_by.get(v, 0) + (sum(g_by.values()) * idle_units[v] / (sum(idle_units[x] for x in idle_units if g_by.get(x, 0) <= 0.5) or 1)
                                       if g_by.get(v, 0) <= 0.5 else 0)
            new_share = max(0.0, (ld + move) / tot_load * 100)
            opt.append({'sku': sku, 'vendor': f'OSAT-{v}', 'now': ch.share * 100, 'gap': g_by.get(v, 0), 'idle': idle_units[v],
                        'suggest': new_share, 'delta': new_share - ch.share * 100})
    sections.append(table('Vendor split optimisation (Test 1)', [
        col('sku', 'Product'), col('vendor', 'OSAT'), col('now', 'Share now %', 'num1'), col('gap', 'Gap there', 'int'),
        col('idle', 'Idle there in the short months (units)', 'int'), col('suggest', 'Suggested share %', 'num1'), col('delta', 'Change (pts)', 'num1')],
        opt, search=False, note='Moves the shortfall to OSATs with idle tester capacity for that product. Change shares in OSAT vendors (all products) to apply it.',
        empty='No product has a gap that another qualified OSAT could absorb.'))
    return page('m1-dashboard', sections, filters=filter_spec(R) + [('step', 'Step', ['Test1', 'Test2'])])


def flow_dashboard(R, args):
    p = R['plan']
    H, months = p.H, p.months
    rows = apply_filters(R['flow']['rows'], args)
    proc = args.get('process')
    unit_ops = ['Assembly', 'Test1', 'Test2', 'Pack']
    out_tot = sum(r['pack_out'] for r in rows)
    act_proc = [op for op in FLOW_ORDER if any((r[op] or 0) > 0.5 for r in rows)]
    sections = [{'type': 'kpis', 'items': [
        K('Total output', short(out_tot), 'units out of Pack'),
        K('Shipped', short(sum(r['ship'] for r in rows)), f'of {short(sum(r["demand"] for r in rows))} demand'),
        K('Active processes', str(len(act_proc)), ', '.join(act_proc)),
        K('Products', str(len({r['sku'] for r in rows}))),
        K('Active OSATs', str(len({r['vendor'] for r in rows}))),
        K('Fab wafer starts', short(sum(R['flow']['totals']['fab_starts'])), 'wafers, all products'),
    ]}]
    by_v = defaultdict(float)
    by_s = defaultdict(float)
    for r in rows:
        by_v[f'OSAT-{r["vendor"]}'] += r['pack_out']
        by_s[r['sku']] += r['pack_out']
    sections.append(cols2(chart('Output share by OSAT', charts.donut(sorted(by_v.items()), 'Output by OSAT')),
                          chart('Output by product', charts.donut(sorted(by_s.items(), key=lambda kv: -kv[1]), 'Output by product'))))
    ops = [proc] if proc in unit_ops else unit_ops
    sections.append(chart('Starts by process and month (units)', charts.bars(
        months, [(op, [sum((r[op] or 0) for r in rows if r['month'] == m) for m in months]) for op in ops], stacked=False,
        lines=[('Demand', [sum(r['demand'] for r in rows if r['month'] == m) for m in months])], title='Starts by process')))
    wops = [proc] if proc in ('Sort', 'Bump') else ['Sort', 'Bump']
    sections.append(chart('Wafer starts at the OSATs (wafers)', charts.bars(
        months, [(op, [sum((r[op] or 0) for r in rows if r['month'] == m) for m in months]) for op in wops], stacked=False,
        lines=[('Fab wafer starts', R['flow']['totals']['fab_starts'])], title='Wafers')))
    ptot = [{'process': op, 'qty': sum((r[op] or 0) for r in rows), 'unit': 'wafers' if op in ('Sort', 'Bump') else 'units'} for op in FLOW_ORDER]
    stot = []
    for sku in sorted({r['sku'] for r in rows}):
        rs = [r for r in rows if r['sku'] == sku]
        d = sum(r['demand'] for r in rs)
        stot.append({'sku': sku, 'demand': d, 'out': sum(r['pack_out'] for r in rs), 'ship': sum(r['ship'] for r in rs),
                     'short': max([sum(r['short'] for r in rs if r['month'] == m) for m in months] + [0]),
                     'fill': sum(r['ship'] for r in rs) / d * 100 if d else 100})
    sections.append(cols2(table('Totals by process', [col('process', 'Process'), col('qty', 'Starts', 'int'), col('unit', 'Unit')], ptot, search=False),
                          table('Totals by product', [col('sku', 'Product'), col('demand', 'Demand', 'int'), col('out', 'Pack output', 'int'),
                                                      col('ship', 'Shipped', 'int'), col('short', 'Peak short', 'int'), col('fill', 'Fill %', 'num1')], stot, search=False)))
    return page('flow-dashboard', sections, filters=filter_spec(R) + [('process', 'Process', FLOW_ORDER)])


# ------------------------------------------------------------------ vendors, customers, test data, inventory
def _e(v):
    return escape('' if v is None else str(v))


def _grade_tone(g):
    return {'A': 'ok', 'B': 'info', 'C': 'warn', 'D': 'bad'}.get(g, '')


def _chips(name, opts, sel, args, anchor=''):
    keep = {k: v for k, v in args.items() if k not in (name, 'msg', 'err')}
    q = lambda v: '&'.join(f'{escape(k)}={escape(str(x))}' for k, x in list(keep.items()) + [(name, v)])
    return '<div class="chips">' + ''.join(
        f'<a class="chip {"on" if str(v) == str(sel) else ""}" href="?{q(v)}{anchor}">{_e(lbl)}</a>' for v, lbl in opts) + '</div>'


def vendor_qbr(R, args):
    from . import insights as I
    p = R['plan']
    period = args.get('period') or 'L3'
    Q = I.qbr_view(p, R, period)
    S = Q['scores']
    W_ = Q['weights']
    sel = args.get('vendor') or ''
    months_txt = (f'{mlabel(Q["months"][0])} – {mlabel(Q["months"][-1])}' if Q['months'] else 'no actuals yet')
    sections = [html('<div class="panel-head"><span class="muted small">Review period</span>'
                     + _chips('period', Q['periods'], period, args) + '</div>')]
    best = S[0] if S else None
    open_iss = [i for i in Q['issues'] if i['Status'] != 'Closed']
    sections.append({'type': 'kpis', 'items': [
        K('Top-ranked OSAT', f'OSAT-{best["vendor"]}' if best else '–', f'score {best["total"]:.1f} · grade {best["grade"]}' if best else '', 'ok'),
        K('Lowest score', f'OSAT-{S[-1]["vendor"]} · {S[-1]["total"]:.1f}' if S else '–', f'grade {S[-1]["grade"]}' if S else '',
          _grade_tone(S[-1]['grade']) if S else ''),
        K('Open issues', str(len(open_iss)), f'{sum(1 for i in open_iss if i["overdue"])} overdue · '
                                              f'{sum(1 for i in open_iss if i["Severity"] == "Critical")} critical',
          'bad' if any(i['overdue'] for i in open_iss) else 'ok'),
        K('Review period', months_txt, f'{len(Q["months"])} months of actuals and test data'),
    ]})
    # ranking table with category scores
    rows = []
    for d in S:
        r = {'rank': d['rank'], 'vendor': f'OSAT-{d["vendor"]}', 'grade': d['grade'], 'g_t': _grade_tone(d['grade']), 'total': d['total'],
             'open': d['open'], 'overdue': d['overdue']}
        for c in I.CATS:
            r[c] = d['scores'][c]
        rows.append(r)
    wtxt = ' · '.join(f'{c} {W_[c][0]:.0f}%' for c in I.CATS)
    sections.append(table('Vendor ranking', [col('rank', '#', 'int'), col('vendor', 'OSAT'), col('grade', 'Grade', 'badge', tone='g_t'),
                                             col('total', 'Score', 'num1')] + [col(c, c, 'num0') for c in I.CATS] +
                          [col('open', 'Open issues', 'int'), col('overdue', 'Overdue', 'int')], rows, search=False,
                          note=f'Weights: {wtxt}. Each category scores 100 at or above its target and loses {I.POINTS_PER_PCT} points per % below it. '
                               f'Grades: A ≥ 90, B ≥ 80, C ≥ 70, D below. Change weights and targets in QBR scorecard weights.'))
    if Q['trend_months'] and S:
        series = [(f'OSAT-{v}', Q['trend'][v], False) for v in sorted(Q['trend'])]
        lo_ = min([x for v in Q['trend'].values() for x in v] + [100])
        sections.append(chart('Score by month', charts.lines(Q['trend_months'], series, vmin=max(0, int(lo_ // 5) * 5 - 5), dec=0, title='QBR score'),
                              'Quality and delivery from each month\'s actuals; cost, capacity and responsiveness as of today.'))
    # measures behind the scores
    meas = []
    for d in S:
        v = d['values']
        meas.append({'vendor': f'OSAT-{d["vendor"]}', 'yr': d['yield_ratio'], 'qp': d['quality_pct'], 'del': v['Delivery'], 'cost': v['Cost'],
                     'ci': d['cost_items'], 'cap': v['Capacity'], 'late': d['cap_late'], 'close': d['avg_close'], 'iss': d['issues']})
    sections.append(table('What the scores are made of', [col('vendor', 'OSAT'), col('yr', 'Test yield vs plan %', 'num1'),
                                                          col('qp', 'Reported quality %', 'num1'), col('del', 'Delivered vs plan %', 'num1'),
                                                          col('cost', 'Price index', 'num1'), col('ci', 'Items compared', 'int'),
                                                          col('cap', 'Forward load on time %', 'num1'), col('late', 'Units late', 'int'),
                                                          col('close', 'Avg days to close', 'num1'), col('iss', 'Issues logged', 'int')],
                          meas, search=False,
                          note='Quality = average of test yield ÷ planned yield (Post-Silicon data) and reported quality % (Vendor actuals). '
                               'Price index = lowest quote ÷ this OSAT\'s quote for the same step and product, averaged. '
                               'Capacity looks forward: share of the planned test load made in its month or pulled in ahead.'))
    if Q['actions']:
        sections.append(table('Agenda for the QBR', [col('vendor', 'OSAT'), col('category', 'Category'), col('score', 'Score', 'num0'),
                                                     col('why', 'Why'), col('action', 'Ask the vendor')],
                              [dict(a, vendor=f'OSAT-{a["vendor"]}') for a in sorted(Q['actions'], key=lambda a: a['score'])], search=False))
    # issues log
    vend_opts = sorted({*p.vendors, 'FAB'})
    iss = [i for i in Q['issues'] if not sel or i['Vendor'] == sel]
    st = args.get('status') or ''
    if st:
        iss = [i for i in iss if (i['Status'] != 'Closed') == (st == 'open')]
    iss.sort(key=lambda i: (i['Status'] == 'Closed', {'Critical': 0, 'Major': 1, 'Minor': 2}.get(i['Severity'], 3), str(i['Opened'])))
    trs = []
    for i in iss:
        tone = 'ok' if i['Status'] == 'Closed' else ('bad' if i['overdue'] or i['Severity'] == 'Critical' else 'warn')
        status = i['Status'] + (' · overdue' if i['overdue'] else '')
        btn = '' if i['Status'] == 'Closed' else (
            f'<form method="post" action="/qbr/issue/close" class="closeform"><input type="hidden" name="id" value="{_e(i["IssueID"])}">'
            f'<input name="root" placeholder="Root cause" maxlength="160" value="{_e(i.get("RootCause"))}" aria-label="Root cause">'
            f'<button class="btn sm" type="submit">Close</button></form>')
        trs.append(f'<tr><td class="nw">{_e(i["IssueID"])}</td><td>{"FAB" if i["Vendor"] == "FAB" else "OSAT-" + _e(i["Vendor"])}</td>'
                   f'<td><span class="badge {tone}">{_e(status)}</span></td><td><span class="badge {"bad" if i["Severity"] == "Critical" else "warn" if i["Severity"] == "Major" else "info"}">{_e(i["Severity"])}</span></td>'
                   f'<td>{_e(i["Category"])}</td><td class="wrap">{_e(i["Title"])}</td><td>{_e(i.get("SKU"))}</td>'
                   f'<td class="nw">{_e(i["Opened"])}</td><td class="nw">{_e(i.get("Due"))}</td>'
                   f'<td class="r nw">{i["days_to_close"] if i["days_to_close"] is not None else (str(i["age"]) + " open" if i["age"] is not None else "")}</td>'
                   f'<td class="wrap small">{_e(i.get("RootCause"))}{" → " if i.get("RootCause") and i.get("Action") else ""}{_e(i.get("Action"))}</td>'
                   f'<td>{btn}</td></tr>')
    filt = ('<div class="panel-head"><h2>Issues log</h2><div class="chips">'
            + ''.join(f'<a class="chip {"on" if sel == v else ""}" href="?period={_e(period)}&vendor={_e(v)}&status={_e(st)}#issues">'
                      f'{"FAB" if v == "FAB" else "OSAT-" + _e(v)}</a>' for v in vend_opts)
            + f'<a class="chip {"on" if not sel else ""}" href="?period={_e(period)}&status={_e(st)}#issues">All</a>'
            + f'<a class="chip {"on" if st == "open" else ""}" href="?period={_e(period)}&vendor={_e(sel)}&status=open#issues">Open only</a>'
            + f'<a class="chip {"on" if st == "closed" else ""}" href="?period={_e(period)}&vendor={_e(sel)}&status=closed#issues">Closed</a></div></div>')
    today = p.as_of
    vend_html = ''.join(f'<option value="{_e(v)}">{"FAB" if v == "FAB" else "OSAT-" + _e(v)}</option>' for v in vend_opts)
    form = (f'<details class="addform"><summary class="btn ghost sm">+ Log a new issue</summary>'
            f'<form method="post" action="/qbr/issue/add" class="formgrid" style="margin-top:12px">'
            f'<label>Supplier<select name="Vendor">{vend_html}</select></label>'
            f'<label>Category<select name="Category">{"".join(f"<option>{c}</option>" for c in ["Quality", "Delivery", "Capacity", "Cost", "Communication"])}</select></label>'
            f'<label>Severity<select name="Severity"><option>Major</option><option>Critical</option><option>Minor</option></select></label>'
            f'<label>Product<select name="SKU"><option value="">(all)</option>{"".join(f"<option>{_e(s)}</option>" for s in p.products)}</select></label>'
            f'<label>Opened<input type="date" name="Opened" value="{today:%Y-%m-%d}"></label>'
            f'<label>Due<input type="date" name="Due" value="{today + timedelta(days=14):%Y-%m-%d}"></label>'
            f'<label style="grid-column:span 2">What happened<input name="Title" maxlength="160" required placeholder="e.g. Final test 1 yield drop on two lots"></label>'
            f'<label>Owner<input name="Owner" maxlength="60"></label>'
            f'<label style="grid-column:span 2">Containment / action<input name="Action" maxlength="200"></label>'
            f'<div><button class="btn" type="submit">Add issue</button></div></form></details>')
    sections.append(html(f'<section class="panel" id="issues">{filt}<p class="sub">8D-style log. Days to close and open, overdue or critical issues feed the '
                         f'Responsiveness score. Edit every field in the <a href="/data/vendor_issues">Vendor issues log</a> table.</p>{form}'
                         f'<div class="tablewrap tall" style="margin-top:12px"><table><thead><tr><th>ID</th><th>Supplier</th><th>Status</th><th>Severity</th>'
                         f'<th>Category</th><th>Issue</th><th>Product</th><th>Opened</th><th>Due</th><th class="r">Days</th><th>Root cause → action</th><th></th></tr></thead>'
                         f'<tbody>{"".join(trs) or "<tr><td colspan=12 class=muted>No issues.</td></tr>"}</tbody></table></div></section>'))
    packs = ''.join(f'<a class="btn ghost sm" href="/export/qbr-{_e(d["vendor"])}.xlsx?period={_e(period)}">QBR pack · OSAT-{_e(d["vendor"])}</a>' for d in S)
    sections.insert(1, html(f'<div class="actions">{packs}<span class="muted small">Excel pack per vendor: scorecard, measures, agenda and issues, ready to send before the review.</span></div>'))
    return page('vendor-qbr', sections)


def customers(R, args):
    from . import insights as I
    p = R['plan']
    C_ = I.customer_view(p, R)
    cs = C_['customers']
    tone = {'Excellent': 'ok', 'Good': 'info', 'Fair': 'warn', 'Risk': 'bad'}
    at_risk = sum(c['at_risk_qty'] for c in cs)
    at_rev = sum(c['at_risk_rev'] for c in cs)
    worst = min((c for c in cs if c['score'] is not None), key=lambda c: c['score'], default=None)
    sections = [{'type': 'kpis', 'items': [
        K('Customers rated', str(sum(1 for c in cs if c['score'] is not None)), f'{len(C_["history"])} agreed orders since {mlabel(C_["months"][0])}' if C_['months'] else ''),
        K('Agreed orders taken as agreed', f'{sum(c["accept_pct"] * c["agreed"] for c in cs) / (sum(c["agreed"] for c in cs) or 1):.1f}%', 'by quantity, incl. pull-ins'),
        K('Lowest rating', f'{worst["customer"]}' if worst else '–', f'{worst["score"]:.0f} · {worst["rating"]}' if worst else '', tone.get(worst['rating'], '') if worst else ''),
        K('Open orders at risk', short(at_risk), f'{money(at_rev)} revenue likely to move or drop', 'warn' if at_risk else 'ok'),
    ]}]
    rows = [dict(c, r_t=tone.get(c['rating'], '')) for c in cs]
    sections.append(table('Customer rating', [col('customer', 'Customer'), col('rating', 'Rating', 'badge', tone='r_t'), col('score', 'Score', 'num1'),
                                              col('orders', 'Agreed orders', 'int'), col('accept_pct', 'Taken as agreed %', 'num1'),
                                              col('push_pct', 'Pushed out %', 'num1'), col('cancel_pct', 'Cancelled %', 'num1'),
                                              col('reduce_pct', 'Reduced %', 'num1'), col('pullin_n', 'Pull-ins', 'int'),
                                              col('avg_push_months', 'Avg push (months)', 'num1')], rows, search=False,
                          note='Score = 100 − (pushed-out % × 0.6 + cancelled % × 1.0 + reduced % × 0.8), all by agreed quantity. '
                               'Excellent ≥ 95, Good ≥ 85, Fair ≥ 70, Risk below. Pull-ins are counted but not penalised.'))
    names = [c['customer'] for c in cs]
    outs = ['Accepted', 'Pulled in', 'Pushed out', 'Reduced', 'Cancelled']
    hist = C_['history']
    series = [(o, [sum(float(r['AgreedQty']) for r in hist if r['Customer'] == n and r['Outcome'] == o) for n in names]) for o in outs]
    if names:
        sections.append(cols2(chart('What happened to agreed quantity', charts.bars(names, series, title='Outcome by customer')),
                              chart('Open orders: likely as agreed vs at risk',
                                    charts.bars(names, [('Likely as agreed', [c['risk_adj_qty'] for c in cs]), ('At risk', [c['at_risk_qty'] for c in cs])],
                                                title='Risk-adjusted open orders'),
                                    'Open orders × each customer\'s history of taking orders as agreed.')))
    sections.append(table('Open orders, risk-adjusted', [col('customer', 'Customer'), col('rating', 'Rating', 'badge', tone='r_t'),
                                                         col('open_qty', 'Open order units', 'int'), col('risk_adj_qty', 'Likely as agreed', 'int'),
                                                         col('at_risk_qty', 'At risk', 'int'), col('open_rev', 'Open revenue', 'money'),
                                                         col('at_risk_rev', 'Revenue at risk', 'money'), col('policy', 'Commit policy')], rows, search=False,
                          note='Use it when committing scarce tester time or long-lead wafers: build ahead for Excellent customers, '
                               'ask Fair and Risk customers for firm or NCNR orders first.'))
    cust = args.get('customer') or ''
    hrows = [dict(r, o_t=('ok' if r['Outcome'] in ('Accepted', 'Pulled in') else 'bad' if r['Outcome'] == 'Cancelled' else 'warn'))
             for r in hist if not cust or r['Customer'] == cust]
    sections.append(table('Agreed-order history', [col('OrderID', 'Order'), col('Customer', 'Customer'), col('SKU', 'Product'),
                                                   col('AgreedMonth', 'Agreed month', 'month'), col('AgreedQty', 'Agreed qty', 'int'),
                                                   col('Outcome', 'Outcome', 'badge', tone='o_t'), col('ActualMonth', 'Actual month', 'month'),
                                                   col('ActualQty', 'Actual qty', 'int'), col('Reason', 'Reason')], hrows,
                          note='Edit or upload in the Agreed-order history table.'))
    return page('customers', sections, filters=[('customer', 'Customer', names)])


def postsilicon(R, args, token=None, base_url=''):
    from . import insights as I
    p = R['plan']
    P = I.postsilicon_view(p, args.get('sku'), args.get('step') or 'Test1', args.get('vendor') or None)
    if not P['sku']:
        return page('postsilicon', [callout('No test results yet. Upload lot results to Test results (lot / wafer), or send them to the test-data API below.')]
                    + [_api_panel(token, base_url)])
    lots = P['lots']
    py = P['plan_y']
    sections = [html('<div class="panel-head"><span class="muted small">Product</span>' + _chips('sku', [(s, s) for s in P['skus']], P['sku'], args)
                     + '<span class="muted small">Step</span>' + _chips('step', [(s, s) for s in P['steps']], P['step'], args)
                     + '<span class="muted small">OSAT</span>' + _chips('vendor', [('', 'All')] + [(v, f'OSAT-{v}') for v in sorted({l["vendor"] for l in I.lots_of(p, P["sku"], P["step"])})], P['vendor'] or '', args)
                     + '</div>')]
    below = [l for l in lots if l['flag'] == 'Below LCL']
    tested = sum(l['tested'] for l in lots)
    yall = sum(l['passed'] for l in lots) / tested * 100 if tested else 0
    sections.append({'type': 'kpis', 'items': [
        K(f'{P["sku"]} {P["step"]} yield', f'{yall:.2f}%', f'{len(lots)} lots · {short(tested)} {"wafers" if P["step"] == "Sort" else "units"} tested'),
        K('Plan yield', f'{py * 100:.1f}%' if py else '–', f'{(yall - py * 100):+.2f} pts actual vs plan' if py else '',
          'ok' if py and yall >= py * 100 - 0.5 else 'warn'),
        K('Control limits', f'{P["lcl"] * 100:.1f}% – {P["ucl"] * 100:.1f}%' if P['lcl'] is not None else '–', f'median ± {P["k"]:.0f} robust σ'),
        K('Alerts', str(len(P['alerts'])), f'{len(below)} lots below LCL', 'bad' if P['alerts'] else 'ok'),
    ]})
    if lots:
        labs = [l['date'] for l in lots]
        ys = [l['yield'] * 100 for l in lots]
        ser = [('Lot yield', ys, False), ('Median', [P['mean'] * 100] * len(lots), True), ('LCL', [P['lcl'] * 100] * len(lots), True),
               ('UCL', [P['ucl'] * 100] * len(lots), True)]
        if py:
            ser.append(('Plan', [py * 100] * len(lots), False))
        lo = min(ys + [P['lcl'] * 100, (py or 1) * 100]) - 1
        sections.append(chart(f'{P["sku"]} {P["step"]} lot yield (control chart)',
                              charts.lines(labs, ser, vmin=max(0, lo), dec=1, unit='%', xlab=lambda d: d[5:], title='Lot yield'),
                              'Each dot is a lot, in test-date order. Limits use the median and a robust sigma (1.4826 × MAD), so an excursion does not widen its own limits.'))
    al = [dict(a, k_t=('bad' if a['kind'] != 'Tester outlier' else 'warn')) for a in P['alerts']]
    sections.append(table('Alerts', [col('kind', 'Alert', 'badge', tone='k_t'), col('vendor', 'OSAT'), col('lot', 'Lot'), col('date', 'Tested'),
                                     col('tester', 'Tester'), col('yield', 'Yield %', 'num1'), col('signature', 'What the data says')],
                          al, search=False, empty='No lot below the lower control limit and no tester outlier.'))
    # actions: use actual yield / bins in the plan
    acts = []
    for v in P['vendors']:
        if v['trailing'] is None or not py:
            continue
        py_v = p.yld(P['sku'], v['vendor'], P['step'], PAD)        # what the plan uses in its first month (after overrides)
        later = [o for o in p.overrides.get((P['sku'], v['vendor'], P['step']), []) if o['EffectiveMonth'] > p.start]
        later_txt = ''.join(f'; plan changes to {float(o["Yield"]) * 100:.1f}% from {mlabel(o["EffectiveMonth"])}' for o in later[:2])
        diff = (v['trailing'] - py_v) * 100
        if abs(diff) >= 1.0:
            acts.append(f'<form method="post" action="/postsilicon/use-yield" class="actrow"><input type="hidden" name="sku" value="{_e(P["sku"])}">'
                        f'<input type="hidden" name="vendor" value="{_e(v["vendor"])}"><input type="hidden" name="step" value="{_e(P["step"])}">'
                        f'<input type="hidden" name="yield" value="{v["trailing"]:.4f}">'
                        f'<span>OSAT-{_e(v["vendor"])}: last {v["n_trailing"]} lots <b>{v["trailing"] * 100:.1f}%</b>, plan uses {py_v * 100:.1f}% in {mlabel(p.start)} '
                        f'({diff:+.1f} pts){_e(later_txt)}</span>'
                        f'<button class="btn sm" type="submit">Use {v["trailing"] * 100:.1f}% in the plan from {mlabel(p.start)}</button></form>')
    bs = [b for b in P['bin_split'] if b['delta'] is not None]
    if bs and max(abs(b['delta']) for b in bs) >= 1.0:
        acts.append(f'<form method="post" action="/postsilicon/use-bins" class="actrow"><input type="hidden" name="sku" value="{_e(P["sku"])}">'
                    f'<input type="hidden" name="step" value="{_e(P["step"])}"><span>Bin split differs from plan by up to '
                    f'{max(abs(b["delta"]) for b in bs):.1f} pts</span><button class="btn sm" type="submit">Update {_e(P["sku"])} bin splits from actuals</button></form>')
    sections.append(html('<section class="panel"><h2>Feed the plan</h2><p class="sub">Turn what the test data shows into the plan: a yield override from the trailing '
                         'five-lot mean (start counts, tester load and wafer starts all re-plan), or bin splits from the actual pass-bin mix (ATP and P&amp;L by bin).</p>'
                         + (''.join(acts) or '<p class="muted small">Actual yields and bin splits are within 1 point of the plan: nothing to change.</p>')
                         + '</section>'))
    vrows = [dict(v, vendor=f'OSAT-{v["vendor"]}', trailing=(v['trailing'] * 100 if v['trailing'] is not None else None)) for v in P['vendors']]
    trows = [dict(t, vendor=f'OSAT-{t["vendor"]}', f_t=('warn' if t['flag'] != 'OK' else 'ok')) for t in P['testers']]
    sections.append(cols2(table('By OSAT', [col('vendor', 'OSAT'), col('lots', 'Lots', 'int'), col('tested', 'Tested', 'int'),
                                             col('yield', 'Yield %', 'num2'), col('vs_plan', 'vs plan (pts)', 'num2'),
                                             col('trailing', 'Last 5 lots %', 'num2')], vrows, search=False),
                          table('By tester', [col('vendor', 'OSAT'), col('tester', 'Tester'), col('lots', 'Lots', 'int'), col('yield', 'Yield %', 'num2'),
                                              col('vs_others', 'vs other testers (pts)', 'num2'), col('flag', 'Flag', 'badge', tone='f_t')],
                                trows, search=False, note='Outlier = 1.5 pts or more below the rest of the OSAT over 3+ lots. '
                                                          'Lots with their own failure signature are left out so a lot problem is not blamed on a tester.')))
    if P['pareto']:
        pl = [r['bin'] + ' ' + r['desc'] for r in P['pareto']]
        sections.append(cols2(
            chart('Fail-bin Pareto', charts.bars(pl, [('Units', [r['count'] for r in P['pareto']])], title='Fail bins'),
                  ' · '.join(f'{r["bin"]} {r["share"]:.0f}% (cum. {r["cum"]:.0f}%)' for r in P['pareto'])),
            table('Pass-bin split: actual vs plan', [col('bin', 'Bin'), col('desc', 'Grade'), col('actual', 'Actual %', 'num1'),
                                                     col('plan', 'Plan %', 'num1'), col('delta', 'Difference (pts)', 'num1')],
                  P['bin_split'], search=False, note='Plan = Bin splits table. ATP and revenue by bin use the plan split.')))
    if P['months']:
        lim = py * 100 - 1.5 if py else None
        g = [{'title': 'Yield % by test month',
              'rows': [{'label': f'OSAT-{v}', 'cells': [((f'{x:.1f}%' if x is not None else '–'),
                                                         ('' if x is None else 'bad' if lim and x < lim else 'ok')) for x in P['monthly'][v]]}
                       for v in sorted(P['monthly'])]}]
        sections.append(grid('Monthly yield', P['months'], g, f'Red: more than 1.5 pts below the plan yield of {py * 100:.1f}%.' if py else ''))
    lrows = [dict(l, yield_p=l['yield'] * 100, vendor=f'OSAT-{l["vendor"]}', f_t=('bad' if l['flag'] == 'Below LCL' else 'warn' if l['flag'] != 'OK' else 'ok'))
             for l in reversed(lots)]
    sections.append(table('Lots', [col('flag', 'Flag', 'badge', tone='f_t'), col('date', 'Tested'), col('lot', 'Lot'), col('vendor', 'OSAT'),
                                   col('tester', 'Tester'), col('tested', 'Tested', 'int'), col('passed', 'Passed', 'int'),
                                   col('yield_p', 'Yield %', 'num2'), col('vs_plan', 'vs plan (pts)', 'num2')], lrows, limit=60))
    sections.append(_api_panel(token, base_url))
    return page('postsilicon', sections)


def _api_panel(token, base_url):
    tok = escape(token or '<token>')
    url = escape((base_url or '').rstrip('/') + '/api/v1/test-results')
    body = ('{"results": [{"TestDate": "2026-11-09", "Vendor": "A", "SKU": "ORION", "Step": "Test1", "LotID": "LOT1001", '
            '"WaferID": "-", "TesterID": "T7-A01", "Tested": 90000, "Passed": 83000}],\n  "bins": [{"Step": "Test1", "LotID": "LOT1001", '
            '"Bin": "HB5", "Count": 4100, "Pass": "N", "Description": "Continuity / open-short"}]}')
    return html(f'<section class="panel" id="api"><h2>Test-data API</h2>'
                f'<p class="sub">Push lot results from your yield-analytics or test-data tool (an export job from a commercial yield-analytics platform, '
                f'an OSAT MES feed, or a script over STDF summaries) straight into this workspace. Rows with the same Step + LotID + WaferID '
                f'(results) or Step + LotID + Bin (bins) replace the old row; everything is validated like an upload. '
                f'This is a generic JSON endpoint; there is no vendor-specific connector.</p>'
                f'<pre class="code">curl -X POST {url} \\\n  -H "Authorization: Bearer {tok}" \\\n  -H "Content-Type: application/json" \\\n'
                f'  -d \'{escape(body)}\'</pre>'
                f'<p class="muted small">The token is tied to this browser\'s workspace (it ends when the workspace expires). GET the same URL with the token to read back a count. '
                f'Up to 5,000 rows per call. Answer: <code>{{"results_added": n, "bins_added": n, "errors": [...]}}</code>.</p></section>')


def inventory(R, args):
    from . import insights as I
    p = R['plan']
    V = I.inventory_view(p, R)
    P_ = V['products']
    tot = sum(x['value'] for x in P_)
    exc = sum(x['excess_value'] for x in P_)
    obs = sum(x['obsolete_value'] for x in P_)
    hold = sum(x['hold_value'] for x in P_)
    sections = [{'type': 'kpis', 'items': [
        K('Inventory value', money(tot), 'WIP and finished goods at standard cost'),
        K('Excess', money(exc), f'above {V["weeks"]:.0f} weeks of demand + cycle time', 'warn' if exc else 'ok'),
        K('Obsolete risk', money(obs), f'date code older than {V["obs_months"]:.0f} months', 'bad' if obs else 'ok'),
        K('On hold', money(hold), 'lots with State = HOLD', 'warn' if hold else 'ok'),
    ]}]
    rows = [dict(x, dos_t=('–' if x['dos'] is None else ('no demand' if x['dos'] == float('inf') else f'{x["dos"]:.0f}')),
                 d_t=('bad' if x['excess'] > 0 and x['obsolete_value'] > 0 else 'warn' if x['excess'] > 0 else 'ok')) for x in P_ if x['inv'] > 0 or x['demand3'] > 0]
    sections.append(table('Inventory health by product', [col('sku', 'Product'), col('status', 'Status'), col('fg', 'FG units', 'int'),
                                                          col('wip', 'WIP (FG-equivalent)', 'int'), col('demand3', 'Demand / month', 'int'),
                                                          col('dos_t', 'Days of supply', 'badge', tone='d_t'), col('value', 'Value', 'money'),
                                                          col('excess', f'Excess units', 'int'), col('excess_value', 'Excess value', 'money'),
                                                          col('obsolete_value', 'Obsolete-risk value', 'money')], rows, search=False,
                          note='WIP is converted to the finished units it should still yield. Days of supply walk the plan demand month by month. '
                               'Excess = finished + WIP above the demand of the next threshold weeks plus the product\'s cycle time (WIP still has to flow), '
                               'valued at standard cost (finished goods first).'))
    skus = [x['sku'] for x in P_ if x['value'] > 0]
    stages = ['Sort', 'Bump', 'DieBank', 'Assembly', 'Test1', 'Test2', 'Pack', 'FG']
    ser = [(s, [V['stage'].get((k, s), 0) for k in skus]) for s in stages if any(V['stage'].get((k, s), 0) for k in skus)]
    order = ['0-3 months', '3-6 months', '6-12 months', '12+ months', 'Obsolete risk', 'No date code']
    ag = [(a, V['aging'][a]) for a in order if V['aging'].get(a)]
    if skus:
        sections.append(cols2(chart('Value by stage', charts.bars(skus, ser, unit=' USD', title='Inventory value by stage')),
                              chart('Aging by date code', charts.donut(ag, title='Aging', unit=' USD'), 'Value by age of the lot date code (YYWW).')))
    acts = []
    for x in P_:
        if x['obsolete_value'] > 0:
            acts.append({'sku': x['sku'], 'what': f'{short(x["obsolete_qty"])} units ({money(x["obsolete_value"])}) are older than {V["obs_months"]:.0f} months',
                         'action': 'Offer to the last-time-buy customer at a discount, check re-qualification of the date code, or reserve and scrap.'})
        if x['excess'] > 0:
            acts.append({'sku': x['sku'], 'what': f'{short(x["excess"])} units ({money(x["excess_value"])}) above {V["weeks"]:.0f} weeks of demand',
                         'action': ('Stop new wafer starts for this product until stock falls below the threshold; check FAB PO Schedule.'
                                    if x['status'] != 'EOL' else 'EOL: cancel open wafer and OSAT orders, sell down the stock, then set a scrap date.')})
    sections.append(table('Actions', [col('sku', 'Product'), col('what', 'Finding'), col('action', 'Action')], acts, search=False,
                          empty='No excess or obsolete stock.'))
    lots = apply_filters([dict(l, vendor_n=f'OSAT-{l["vendor"]}', a_t=('bad' if l['aging'] == 'Obsolete risk' else 'warn' if l['aging'] in ('12+ months', '6-12 months') else 'ok'))
                          for l in V['lots']], args)
    lots.sort(key=lambda l: -(l['age'] or 0))
    sections.append(table('Lots', [col('aging', 'Age', 'badge', tone='a_t'), col('lot', 'Lot'), col('vendor_n', 'OSAT'), col('sku', 'Product'),
                                   col('stage', 'Stage'), col('state', 'State'), col('qty', 'Qty', 'int'), col('unit', 'Unit'),
                                   col('fg_eq', 'FG-equivalent', 'int'), col('complete', 'Cost complete %', 'num0'), col('value', 'Value', 'money'),
                                   col('datecode', 'Date code')], lots, limit=80))
    return page('inventory', sections, filters=filter_spec(R))
