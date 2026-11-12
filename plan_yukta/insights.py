"""
Vendor QBR scorecard, customer rating, post-silicon (test data) analysis and inventory health.

All four read the same workspace tables as the planning engine and the plan results (R).
Formulas are documented in CALCULATIONS.md, sections 16-19.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .cockpit import PAD, TEST_OPS, WAFER_OPS, month_add, to_date

CATS = ['Quality', 'Delivery', 'Cost', 'Capacity', 'Responsiveness']
DEFAULT_WEIGHTS = {'Quality': (30, 99.5), 'Delivery': (30, 98), 'Cost': (15, 100), 'Capacity': (15, 99.9), 'Responsiveness': (10, 14)}
POINTS_PER_PCT = 5          # score points lost per percentage point below target
POINTS_PER_DAY = 3          # responsiveness: points lost per day over the target close time
PEN_OVERDUE, PEN_CRITICAL = 10, 15


def grade(score):
    return 'A' if score >= 90 else 'B' if score >= 80 else 'C' if score >= 70 else 'D'


def _pct_score(value, target):
    if value is None:
        return None
    if value >= target:
        return 100.0
    return max(0.0, 100.0 - POINTS_PER_PCT * (target - value))


def _quarter(m):
    return f'{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}'


def qbr_periods(p):
    months = sorted({r['Month'] for r in p.t['actuals']} | {str(r['TestDate'])[:7] for r in p.t['test_results']})
    opts = [('L3', 'Last 3 months')] + [(q, q) for q in sorted({_quarter(m) for m in months}, reverse=True)]
    return months, opts


def _period_months(all_months, period):
    if not all_months:
        return []
    if period and period != 'L3' and '-Q' in period:
        return [m for m in all_months if _quarter(m) == period]
    last = all_months[-1]
    return [m for m in all_months if m > month_add(last, -3)]


def weights(p):
    w = {c: DEFAULT_WEIGHTS[c] for c in CATS}
    rows = p.t.get('qbr_weights') or []
    if rows:
        w = {c: (0.0, DEFAULT_WEIGHTS[c][1]) for c in CATS}
        for r in rows:
            if r['Category'] in w:
                w[r['Category']] = (float(r['WeightPct']), float(r['Target']))
    return w


def _cost_index(p):
    """Per vendor: average of (lowest quoted price ÷ this vendor's price) x 100 over items two or more vendors quote."""
    quotes = defaultdict(dict)
    for r in p.t['osat_costs']:
        if r['Vendor'] in p.vendors and float(r['CostUSD'] or 0) > 0:
            quotes[(r['Operation'], r['SKU'])][r['Vendor']] = float(r['CostUSD'])
    for r in p.t['tester_capacity']:
        if r['Vendor'] in p.vendors and float(r['CostConsigneeUSD'] or 0) > 0:
            quotes[(r['Step'], r['SKU'])][r['Vendor']] = float(r['CostConsigneeUSD'])
    idx = defaultdict(list)
    for item, q in quotes.items():
        if len(q) < 2:
            continue
        lo = min(q.values())
        for v, price in q.items():
            idx[v].append(lo / price * 100)
    return {v: (sum(x) / len(x) if x else None, len(x)) for v, x in idx.items()}


def _capacity(p):
    """Per vendor: share of the planned test load in the horizon made in its month or pulled in ahead (not late)."""
    out = {}
    for v in p.vendors:
        load = gap = 0.0
        for (vv, step), a in p.alloc.items():
            if vv != v:
                continue
            for k, r in a['res'].items():
                load += sum(r['load'][:p.H])
                gap += sum(r['gap'][:p.H])
        out[v] = ((load - gap) / load * 100 if load > 0 else None, load, gap)
    return out


def _issue_rows(p):
    rows = []
    for r in p.t.get('vendor_issues', []):
        o, c, due = to_date(r.get('Opened')), to_date(r.get('Closed')), to_date(r.get('Due'))
        closed = r['Status'] == 'Closed'
        days = (c - o).days if (closed and c and o) else None
        age = (p.as_of - o).days if (o and not closed) else None
        overdue = bool(not closed and due and due < p.as_of)
        rows.append(dict(r, days_to_close=days, age=age, overdue=overdue, opened_m=str(r.get('Opened') or '')[:7]))
    return rows


def vendor_scores(p, months, R=None, issues=None):
    """Scorecard for each enabled OSAT over the given months."""
    W = weights(p)
    issues = issues if issues is not None else _issue_rows(p)
    ms = set(months)
    flow_y = {(sku, op): float(r['Yield']) for sku, ops in p.flow.items() for op, r in ops.items()}
    # quality: test yield vs plan
    yq = defaultdict(lambda: [0.0, 0.0])
    for r in p.t['test_results']:
        if str(r['TestDate'])[:7] in ms and (r['SKU'], r['Step']) in flow_y and float(r['Tested'] or 0) > 0:
            yq[r['Vendor']][0] += float(r['Passed'])
            yq[r['Vendor']][1] += float(r['Tested']) * flow_y[(r['SKU'], r['Step'])]
    qp = defaultdict(list)
    dl = defaultdict(lambda: [0.0, 0.0])
    snap = {(r['Month'], r['Vendor'], r['SKU'], r['Operation']): float(r['PlannedUnits']) for r in p.t['plan_snapshot']}
    for r in p.t['actuals']:
        if r['Month'] not in ms:
            continue
        qp[r['Vendor']].append(float(r['QualityPct']))
        plan = snap.get((r['Month'], r['Vendor'], r['SKU'], r['Operation']))
        if plan:
            dl[r['Vendor']][0] += min(float(r['ActualUnits']), plan)
            dl[r['Vendor']][1] += plan
    cost = _cost_index(p)
    cap = _capacity(p)
    out = []
    for v in sorted(p.vendors):
        parts = []
        yr = yq[v][0] / yq[v][1] * 100 if yq[v][1] else None
        if yr is not None:
            parts.append(min(yr, 100.0))
        if qp[v]:
            parts.append(sum(qp[v]) / len(qp[v]))
        val = {'Quality': sum(parts) / len(parts) if parts else None,
               'Delivery': dl[v][0] / dl[v][1] * 100 if dl[v][1] else None,
               'Cost': cost.get(v, (None, 0))[0],
               'Capacity': cap.get(v, (None,))[0]}
        vi = [i for i in issues if i['Vendor'] == v]
        closed = [i['days_to_close'] for i in vi if i['days_to_close'] is not None and (not ms or str(i.get('Closed'))[:7] <= max(ms))]
        avg_close = sum(closed) / len(closed) if closed else None
        overdue = sum(1 for i in vi if i['overdue'])
        crit = sum(1 for i in vi if i['Status'] != 'Closed' and i['Severity'] == 'Critical')
        val['Responsiveness'] = avg_close
        sc = {}
        for c in CATS:
            w, tgt = W[c]
            if c == 'Responsiveness':
                base = 100.0 if avg_close is None or avg_close <= tgt else max(0.0, 100.0 - POINTS_PER_DAY * (avg_close - tgt))
                sc[c] = max(0.0, base - PEN_OVERDUE * overdue - PEN_CRITICAL * crit)
            else:
                sc[c] = _pct_score(val[c], tgt)
        tw = sum(W[c][0] for c in CATS if sc[c] is not None)
        total = sum(sc[c] * W[c][0] for c in CATS if sc[c] is not None) / tw if tw else 0.0
        open_n = sum(1 for i in vi if i['Status'] != 'Closed')
        out.append({'vendor': v, 'name': p.vendors[v].get('Name') or f'OSAT-{v}', 'values': val, 'scores': sc, 'total': total,
                    'grade': grade(total), 'yield_ratio': yr, 'quality_pct': (sum(qp[v]) / len(qp[v]) if qp[v] else None),
                    'cost_items': cost.get(v, (None, 0))[1], 'cap_load': cap.get(v, (None, 0, 0))[1], 'cap_late': cap.get(v, (None, 0, 0))[2],
                    'avg_close': avg_close, 'overdue': overdue, 'critical_open': crit, 'open': open_n, 'issues': len(vi)})
    out.sort(key=lambda d: -d['total'])
    for i, d in enumerate(out):
        d['rank'] = i + 1
    return out


def qbr_view(p, R, period='L3'):
    all_m, opts = qbr_periods(p)
    months = _period_months(all_m, period)
    issues = _issue_rows(p)
    scores = vendor_scores(p, months, R, issues)
    act_months = sorted({r['Month'] for r in p.t['actuals']})
    trend = {d['vendor']: [] for d in scores}
    for m in act_months:
        for d in vendor_scores(p, [m], R, issues):
            trend.setdefault(d['vendor'], []).append(d['total'])
    actions = []
    for d in scores:
        sc, val = d['scores'], d['values']
        W = weights(p)
        for c in CATS:
            if sc[c] is not None and sc[c] < 90 and W[c][0] > 0:
                why = {'Quality': f'test yield {d["yield_ratio"]:.1f}% of plan' if d['yield_ratio'] is not None else 'quality below target',
                       'Delivery': f'{val["Delivery"]:.1f}% of the frozen plan delivered' if val['Delivery'] is not None else '',
                       'Cost': f'price index {val["Cost"]:.0f} (100 = lowest quote)' if val['Cost'] is not None else '',
                       'Capacity': f'{val["Capacity"]:.1f}% of forward test load on time' if val['Capacity'] is not None else '',
                       'Responsiveness': (f'{d["avg_close"]:.0f} days to close' if d['avg_close'] is not None else 'no closed issues')
                                         + (f', {d["overdue"]} overdue' if d['overdue'] else '')
                                         + (f', {d["critical_open"]} critical open' if d['critical_open'] else '')}[c]
                todo = {'Quality': 'Ask for an 8D on the lowest-yield lots and a yield improvement plan with dates; see Post-Silicon Analysis.',
                        'Delivery': 'Review the root causes in Plan vs Actual and agree a recovery schedule.',
                        'Cost': 'Benchmark the quote against the lowest vendor and negotiate against next year\'s volume.',
                        'Capacity': 'Agree extra tester time (or a tester arrival) before the short months; see Tester & Capacity Overrides.',
                        'Responsiveness': 'Agree owners and due dates for open issues; escalate overdue critical issues.'}[c]
                actions.append({'vendor': d['vendor'], 'category': c, 'score': sc[c], 'why': why, 'action': todo})
    return {'months': months, 'period': period, 'periods': opts, 'scores': scores, 'trend': trend, 'trend_months': act_months,
            'issues': issues, 'actions': actions, 'weights': weights(p)}


# ------------------------------------------------------------------ customers
def _rating(score):
    return 'Excellent' if score >= 95 else 'Good' if score >= 85 else 'Fair' if score >= 70 else 'Risk'


COMMIT_POLICY = {'Excellent': 'Commit the full order; build ahead is safe.',
                 'Good': 'Commit; review the order with the customer every month.',
                 'Fair': 'Ask for a firm PO before building beyond the frozen months.',
                 'Risk': 'Build to firm PO only; ask for NCNR terms or a deposit on long-lead wafers.'}


def customer_view(p, R):
    hist = defaultdict(list)
    for r in p.t['order_history']:
        hist[r['Customer']].append(r)
    open_q = defaultdict(float)
    open_rev = defaultdict(float)
    price = {(r['SKU'], r['Customer']): float(r['ASPUSD']) for r in p.t['pricing']}
    for r in p.t['orders']:
        if r['Status'] != 'Cancelled' and r['Month'] >= p.start:
            open_q[r['Customer']] += float(r['Qty'])
            asp = price.get((r['SKU'], r['Customer']), price.get((r['SKU'], '*'), 0.0))
            open_rev[r['Customer']] += float(r['Qty']) * asp
    out = []
    for c in sorted(set(hist) | set(open_q)):
        rows = hist.get(c, [])
        agreed = sum(float(r['AgreedQty']) for r in rows) or 0.0
        by = defaultdict(float)
        n = defaultdict(int)
        for r in rows:
            by[r['Outcome']] += float(r['AgreedQty'])
            n[r['Outcome']] += 1
        red_qty = sum(float(r['AgreedQty']) - float(r['ActualQty'] or 0) for r in rows if r['Outcome'] == 'Reduced')
        pct = (lambda q: q / agreed * 100 if agreed else 0.0)
        push, cancel, red = pct(by['Pushed out']), pct(by['Cancelled']), pct(red_qty)
        accept = pct(by['Accepted'] + by['Pulled in'])
        score = max(0.0, 100 - (push * 0.6 + cancel * 1.0 + red * 0.8)) if agreed else None
        rating = _rating(score) if score is not None else 'No history'
        on_time_share = max(0.0, 1 - (push + cancel + red) / 100) if agreed else 1.0
        oq = open_q.get(c, 0.0)
        pushed_ok = [r for r in rows if r['Outcome'] == 'Pushed out' and r.get('ActualMonth')]
        avg_push = (sum(max(0, (int(r['ActualMonth'][:4]) * 12 + int(r['ActualMonth'][5:7])) - (int(r['AgreedMonth'][:4]) * 12 + int(r['AgreedMonth'][5:7])))
                        for r in pushed_ok) / len(pushed_ok)) if pushed_ok else None
        out.append({'customer': c, 'orders': len(rows), 'agreed': agreed, 'accept_pct': accept, 'push_pct': push, 'cancel_pct': cancel,
                    'reduce_pct': red, 'pullin_n': n['Pulled in'], 'push_n': n['Pushed out'], 'cancel_n': n['Cancelled'],
                    'reduce_n': n['Reduced'], 'score': score, 'rating': rating, 'policy': COMMIT_POLICY.get(rating, 'Collect order history first.'),
                    'open_qty': oq, 'open_rev': open_rev.get(c, 0.0), 'risk_adj_qty': oq * on_time_share,
                    'at_risk_qty': oq * (1 - on_time_share), 'at_risk_rev': open_rev.get(c, 0.0) * (1 - on_time_share),
                    'avg_push_months': avg_push})
    out.sort(key=lambda d: -(d['score'] if d['score'] is not None else -1))
    months = sorted({r['AgreedMonth'] for r in p.t['order_history']})
    return {'customers': out, 'months': months, 'history': p.t['order_history']}


# ------------------------------------------------------------------ post-silicon
def _robust(vals):
    if not vals:
        return None, None
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    sd = 1.4826 * mad
    if sd <= 0 and len(vals) > 1:
        sd = statistics.pstdev(vals)
    return med, sd


def lots_of(p, sku=None, step=None, vendor=None):
    agg = {}
    for r in p.t['test_results']:
        if (sku and r['SKU'] != sku) or (step and r['Step'] != step) or (vendor and r['Vendor'] != vendor):
            continue
        k = (r['Step'], r['LotID'])
        d = agg.setdefault(k, {'step': r['Step'], 'lot': r['LotID'], 'sku': r['SKU'], 'vendor': r['Vendor'], 'date': str(r['TestDate']),
                               'tested': 0.0, 'passed': 0.0, 'testers': set(), 'wafers': 0})
        d['tested'] += float(r['Tested'] or 0)
        d['passed'] += float(r['Passed'] or 0)
        d['wafers'] += 1
        if r.get('TesterID'):
            d['testers'].add(r['TesterID'])
        d['date'] = min(d['date'], str(r['TestDate']))
    out = []
    for d in agg.values():
        if d['tested'] > 0:
            d['yield'] = d['passed'] / d['tested']
            d['tester'] = ', '.join(sorted(d['testers']))
            out.append(d)
    out.sort(key=lambda d: (d['date'], d['lot']))
    return out


def postsilicon_view(p, sku=None, step='Test1', vendor=None):
    k_sigma = float(p.s.get('SPC sigma', 3))
    skus = sorted({r['SKU'] for r in p.t['test_results']})
    steps = sorted({r['Step'] for r in p.t['test_results']}, key=lambda s: ['Sort', 'Test1', 'Test2'].index(s) if s in ('Sort', 'Test1', 'Test2') else 9)
    if not sku or sku not in skus:
        sku = skus[0] if skus else None
        if 'ORION' in skus:
            sku = 'ORION'
    if step not in steps and steps:
        step = 'Test1' if 'Test1' in steps else steps[0]
    lots = lots_of(p, sku, step, vendor)
    plan_y = float(p.flow[sku][step]['Yield']) if sku in p.flow and step in p.flow[sku] else None
    mean, sd = _robust([l['yield'] for l in lots])
    ucl = min(1.0, mean + k_sigma * sd) if mean is not None else None
    lcl = max(0.0, mean - k_sigma * sd) if mean is not None else None
    for l in lots:
        l['flag'] = 'Below LCL' if lcl is not None and l['yield'] < lcl else ('Below plan' if plan_y and l['yield'] < plan_y - 0.01 else 'OK')
        l['vs_plan'] = (l['yield'] - plan_y) * 100 if plan_y else None
    # bins
    lot_ids = {l['lot'] for l in lots}
    fails = defaultdict(float)
    passes = defaultdict(float)
    desc = {}
    lot_fail_mix = defaultdict(lambda: defaultdict(float))
    for r in p.t['test_bins']:
        if r['Step'] != step or r['LotID'] not in lot_ids:
            continue
        c = float(r['Count'] or 0)
        desc[r['Bin']] = r.get('Description') or ''
        if r['Pass'] == 'Y':
            passes[r['Bin']] += c
        else:
            fails[r['Bin']] += c
            lot_fail_mix[r['LotID']][r['Bin']] += c
    tot_f = sum(fails.values())
    norm = {b: c / tot_f for b, c in fails.items()} if tot_f else {}

    def signature(lot):
        mix = lot_fail_mix.get(lot, {})
        tf = sum(mix.values())
        if not tf:
            return None, 0.0
        b, c = max(mix.items(), key=lambda kv: kv[1] / tf - norm.get(kv[0], 0))
        return b, (c / tf - norm.get(b, 0)) * 100

    for l in lots:
        l['sig_bin'], l['sig_dev'] = signature(l['lot'])
        l['sig_exc'] = l['flag'] == 'Below LCL' and l['sig_dev'] >= 15
    # vendor and tester comparison
    by_v = defaultdict(lambda: [0.0, 0.0, 0])
    by_t = defaultdict(lambda: [0.0, 0.0, 0])
    for l in lots:
        by_v[l['vendor']][0] += l['passed']
        by_v[l['vendor']][1] += l['tested']
        by_v[l['vendor']][2] += 1
    base_v = defaultdict(lambda: [0.0, 0.0])     # vendor totals without signature excursions, for the tester comparison
    for l in lots:
        if l['sig_exc']:          # a lot with its own failure signature is a lot problem, not a tester problem
            continue
        base_v[l['vendor']][0] += l['passed']
        base_v[l['vendor']][1] += l['tested']
        for t in l['testers'] or {'-'}:
            by_t[(l['vendor'], t)][0] += l['passed']
            by_t[(l['vendor'], t)][1] += l['tested']
            by_t[(l['vendor'], t)][2] += 1
    vendors = []
    for v, (ps, ts, n) in sorted(by_v.items()):
        recent = [l['yield'] for l in lots if l['vendor'] == v][-5:]
        vendors.append({'vendor': v, 'lots': n, 'tested': ts, 'yield': ps / ts * 100 if ts else None,
                        'vs_plan': (ps / ts - plan_y) * 100 if ts and plan_y else None,
                        'trailing': sum(recent) / len(recent) if recent else None, 'n_trailing': len(recent)})
    testers = []
    for (v, t), (ps, ts, n) in sorted(by_t.items()):
        oth_p, oth_t = base_v[v][0] - ps, base_v[v][1] - ts
        oth = oth_p / oth_t if oth_t > 0 else None
        delta = (ps / ts - oth) * 100 if (ts and oth is not None) else None
        flag = 'Outlier' if (delta is not None and delta < -1.5 and n >= 3) else 'OK'
        testers.append({'vendor': v, 'tester': t, 'lots': n, 'tested': ts, 'yield': ps / ts * 100 if ts else None,
                        'vs_others': delta, 'flag': flag})
    pareto, cum = [], 0.0
    for b, c in sorted(fails.items(), key=lambda kv: -kv[1]):
        cum += c
        pareto.append({'bin': b, 'desc': desc.get(b, ''), 'count': c, 'share': c / tot_f * 100 if tot_f else 0,
                       'cum': cum / tot_f * 100 if tot_f else 0})
    tot_p = sum(passes.values())
    plan_bins = dict(p.bins.get(sku, []))
    bin_split = [{'bin': b, 'desc': desc.get(b, ''), 'actual': passes.get(b, 0) / tot_p * 100 if tot_p else None,
                  'plan': plan_bins.get(b, 0) * 100 if b in plan_bins else None}
                 for b in sorted(set(passes) | set(plan_bins))]
    for r in bin_split:
        d_ = (r['actual'] - r['plan']) if (r['actual'] is not None and r['plan'] is not None) else None
        r['delta'] = (0.0 if d_ is not None and abs(d_) < 0.05 else d_)
    # alerts: lots below LCL with their dominant failure mode against the normal mix
    alerts = []
    bad_testers = {(t['vendor'], t['tester']) for t in testers if t['flag'] == 'Outlier'}
    for l in lots:
        if l['flag'] != 'Below LCL':
            continue
        b = l['sig_bin']
        bt = [t for t in l['testers'] if (l['vendor'], t) in bad_testers]
        if bt and not l['sig_exc']:
            txt = f'tested on {bt[0]}, a tester that runs below the others at OSAT-{l["vendor"]}: retest a sample on another tester'
        elif b and l['sig_dev'] >= 15:
            mix = lot_fail_mix[l['lot']]
            txt = (f'{b} {desc.get(b, "")} is {mix[b] / sum(mix.values()) * 100:.0f}% of fails (normally {norm.get(b, 0) * 100:.0f}%): '
                   f'a single failure mode, look for a hardware or assembly cause')
        elif b:
            txt = 'fail mix is normal: the loss is spread over every fail bin, which points to a process or material shift'
        else:
            txt = 'no bin data for this lot'
        alerts.append({'lot': l['lot'], 'vendor': l['vendor'], 'date': l['date'], 'tester': l['tester'], 'yield': l['yield'] * 100,
                       'signature': txt, 'kind': 'Lot below LCL'})
    for v in vendors:
        if v['trailing'] is not None and plan_y and v['n_trailing'] >= 3 and (v['trailing'] - plan_y) * 100 < -2:
            alerts.append({'lot': f'last {v["n_trailing"]} lots', 'vendor': v['vendor'], 'date': '', 'tester': '', 'yield': v['trailing'] * 100,
                           'kind': 'Sustained shift',
                           'signature': f'the last {v["n_trailing"]} lots average {v["trailing"] * 100:.1f}% against a plan of {plan_y * 100:.1f}%: '
                                        f'check the plan yield (Process flow or a Yield override) and use the actual yield in the plan below.'})
    for t in testers:
        if t['flag'] == 'Outlier':
            alerts.append({'lot': '-', 'vendor': t['vendor'], 'date': '', 'tester': t['tester'], 'yield': t['yield'], 'kind': 'Tester outlier',
                           'signature': f'tester runs {abs(t["vs_others"]):.1f} pts below the other testers at OSAT-{t["vendor"]} '
                                        f'over {t["lots"]} lots: check calibration, load board and contactors'})
    # monthly yield by vendor
    months = sorted({l['date'][:7] for l in lots})
    monthly = {}
    for v in sorted(by_v):
        row = []
        for m in months:
            ls = [l for l in lots if l['vendor'] == v and l['date'][:7] == m]
            ts = sum(l['tested'] for l in ls)
            row.append(sum(l['passed'] for l in ls) / ts * 100 if ts else None)
        monthly[v] = row
    return {'sku': sku, 'step': step, 'vendor': vendor, 'skus': skus, 'steps': steps, 'lots': lots, 'plan_y': plan_y,
            'mean': mean, 'sd': sd, 'ucl': ucl, 'lcl': lcl, 'k': k_sigma, 'vendors': vendors, 'testers': testers,
            'pareto': pareto, 'bin_split': bin_split, 'alerts': alerts, 'months': months, 'monthly': monthly,
            'n_results': len(p.t['test_results'])}


# ------------------------------------------------------------------ inventory health
def _datecode(dc):
    """YYWW date code -> Monday of that ISO week (None if not a date code)."""
    s = str(dc or '').strip()
    if len(s) != 4 or not s.isdigit():
        return None
    yy, ww = int(s[:2]), int(s[2:])
    if not 1 <= ww <= 53:
        return None
    try:
        return date.fromisocalendar(2000 + yy, min(ww, 52), 1)
    except ValueError:
        return None


def inventory_view(p, R):
    weeks = float(p.s.get('Excess threshold weeks', 13))
    obs_m = float(p.s.get('Obsolete age months', 18))
    std_rows = {(r['sku'], r['vendor']): r for r in R['cost']['std']}
    by_sku_std = defaultdict(list)
    for r in R['cost']['std']:
        by_sku_std[r['sku']].append(r)
    order = ['Fab'] + [o for o in ['Sort', 'Bump', 'Assembly', 'Test1', 'Test2', 'Pack']]

    def std_for(sku, v):
        r = std_rows.get((sku, v))
        if r:
            return r
        lst = by_sku_std.get(sku)
        return lst[0] if lst else None

    def value_through(sku, v, done_ops):
        r = std_for(sku, v)
        if not r:
            return 0.0, 0.0
        tot = float(r['total'] or 0)
        return sum(float(r.get(o) or 0) for o in order if o in done_ops), tot

    lots_out = []
    for l in p.lots:
        if l['issue'] or l['SKU'] not in p.products:
            continue
        sku, v, op = l['SKU'], l['Vendor'], l['Operation']
        ops = p.ops_of(sku)
        wafer = op in ('Sort', 'Bump', 'DieBank')
        qty = float(l.get('Wafers') or 0) if wafer else float(l.get('Units') or 0)
        if qty <= 0:
            continue
        if op == 'FG':
            eq = qty
            done = set(order)
        else:
            if op == 'DieBank':
                done = {'Fab'} | {o for o in ('Sort', 'Bump') if o in ops}
                eq = qty * float(p.products[sku]['GDPW'])
                for o in ops:
                    eq *= p.yld(sku, v, o, PAD)
            else:
                idx = ops.index(op) if op in ops else 0
                finished = l['State'] == 'DONE'
                done = {'Fab'} | set(ops[:idx + (1 if finished else 0)])
                if wafer:
                    eq = qty * float(p.products[sku]['GDPW'])
                    for o in ops:
                        eq *= p.yld(sku, v, o, PAD)
                else:
                    eq = qty
                    for o in ops[idx + (1 if finished else 0):]:
                        eq *= p.yld(sku, v, o, PAD)
        through, total = value_through(sku, v, done)
        val = eq * through
        dc = _datecode(l.get('DateCode'))
        age = (p.as_of - dc).days / 30.44 if dc else None
        lots_out.append({'lot': l['LotID'], 'vendor': v, 'sku': sku, 'stage': op, 'state': l['State'], 'qty': qty,
                         'unit': 'wafers' if wafer else 'units', 'fg_eq': eq, 'complete': (through / total * 100) if total else 0,
                         'value': val, 'datecode': l.get('DateCode'), 'age': age,
                         'aging': ('No date code' if age is None else 'Obsolete risk' if age > obs_m else
                                   '12+ months' if age > 12 else '6-12 months' if age > 6 else '3-6 months' if age > 3 else '0-3 months')})
    # per product
    prods = []
    for sku in p.products:
        ls = [l for l in lots_out if l['sku'] == sku]
        dem = p.dem.get(sku, [0] * p.H)
        fg = sum(l['fg_eq'] for l in ls if l['stage'] == 'FG')
        wip = sum(l['fg_eq'] for l in ls if l['stage'] != 'FG')
        inv = fg + wip
        # demand over the threshold weeks (months pro-rated), days of supply by walking the monthly demand
        # WIP still has to flow through the line: cover the threshold plus the product's cycle time
        lead_w = sum(float(p.flow[sku][o]['CycleTimeDays'] or 0) for o in p.ops_of(sku)) / 7.0
        need, left_w = 0.0, weeks + lead_w
        for i in range(p.H):
            mw = p.days / 7.0
            take = min(left_w, mw)
            need += dem[i] * take / mw
            left_w -= take
            if left_w <= 0:
                break
        dos, rem = None, inv
        for i in range(p.H if inv > 0 else 0):
            if dem[i] <= 0:
                continue
            if rem <= dem[i]:
                dos = i * p.days + rem / dem[i] * p.days
                break
            rem -= dem[i]
        if dos is None and inv > 0:
            dos = float('inf') if sum(dem) <= 0 else p.H * p.days
        excess = max(0.0, inv - need)
        unit_v = (sum(l['value'] for l in ls) / inv) if inv else 0.0
        fg_v = sum(l['value'] for l in ls if l['stage'] == 'FG')
        obs = [l for l in ls if l['aging'] == 'Obsolete risk']
        # value excess at FG standard cost first (FG is consumed first)
        r = std_for(sku, None) or {}
        fg_cost = float(r.get('total') or 0)
        ex_from_fg = min(excess, fg)
        excess_v = ex_from_fg * fg_cost + (excess - ex_from_fg) * ((sum(l['value'] for l in ls if l['stage'] != 'FG') / wip) if wip else 0)
        prods.append({'sku': sku, 'status': p.products[sku]['Status'], 'fg': fg, 'wip': wip, 'inv': inv,
                      'value': sum(l['value'] for l in ls), 'fg_value': fg_v, 'demand3': sum(dem[:3]) / 3 if p.H >= 3 else sum(dem) / max(1, p.H),
                      'need_threshold': need, 'lead_weeks': lead_w, 'dos': dos, 'excess': excess, 'excess_value': excess_v,
                      'obsolete_qty': sum(l['fg_eq'] for l in obs), 'obsolete_value': sum(l['value'] for l in obs), 'unit_value': unit_v,
                      'hold_value': sum(l['value'] for l in ls if l['state'] == 'HOLD')})
    stage = defaultdict(float)
    for l in lots_out:
        stage[(l['sku'], l['stage'])] += l['value']
    aging = defaultdict(float)
    for l in lots_out:
        aging[l['aging']] += l['value']
    return {'products': prods, 'lots': lots_out, 'stage': dict(stage), 'aging': dict(aging), 'weeks': weeks, 'obs_months': obs_m}
