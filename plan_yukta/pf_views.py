"""Page builders for the Portfolio & Roadmaps section."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode

from . import charts
from . import portfolio as PF
from .cockpit import month_add, to_date
from .views import K, callout, chart, col, cols2, html, mlabel, page, table
from .workspace import PF_BUS, PF_CATEGORIES, PF_GATES

RAG_TXT = {'R': 'Red', 'A': 'Amber', 'G': 'Green', '-': '–'}


def _e(v):
    return escape('' if v is None else str(v))


def _rag(code, label=''):
    c = code if code in ('R', 'A', 'G') else 'x'
    return f'<span class="rag {c}" title="{_e(label)} {RAG_TXT.get(code, "")}">{_e(label[:1] if label else RAG_TXT.get(code, "–")[:1])}</span>'


def _rags(p):
    return ''.join(_rag(v, k) for k, v in p['rag'].items())


def _chips(name, opts, sel, args, anchor=''):
    keep = {k: v for k, v in args.items() if k not in (name, 'msg', 'err')}
    out = []
    for v, lbl in opts:
        q = dict(keep)
        if v:
            q[name] = v
        out.append(f'<a class="chip {"on" if str(v) == str(sel or "") else ""}" href="?{_e(urlencode(q))}{anchor}">{_e(lbl)}</a>')
    return '<div class="chips">' + ''.join(out) + '</div>'


def _d(m):
    return date(int(m[:4]), int(m[5:7]), 1)


def _m_end(m):
    nm = month_add(m, 1)
    return _d(nm) - timedelta(days=1)


def _fund_tone(r):
    r = str(r or '')
    return 'ok' if r in ('Committed', 'Fits now') else 'warn' if r.startswith('Fits if') else 'bad' if r == 'Above the line' else ''


def _qgrid(pf, load, title, note=''):
    """Quarterly utilisation heatmap by pool."""
    qs = pf.quarters()
    rows = []
    for r in pf.util_table(load):
        cells = []
        for q, idx in qs:
            sup = sum(r['supply'][i] for i in idx) / len(idx)
            dem = sum(r['demand'][i] for i in idx) / len(idx)
            u = dem / sup * 100 if sup else 0
            tgt = r['target']
            tone = 'bad' if u > tgt + 0.5 else 'warn' if u > tgt - 10 else 'ok' if u > 1 else ''
            cells.append((f'{u:.0f}%' if dem > 0.05 else '–', tone))
        rows.append({'label': f'{r["pool"]} · {r["supply"][0]:.0f} FTE', 'cells': cells, 'href': f'/m/pf-capacity?pool={r["pool"]}'})
    return {'type': 'grid', 'title': title, 'note': note, 'months': [q for q, _ in qs], 'groups': [{'title': '', 'rows': rows}]}


def _insights(pf, R=None):
    k = pf.kpis()
    out = []
    ov = sorted(pf.overloads(pf.load_committed), key=lambda x: -x[2])
    if ov:
        pool, i, x = ov[0]
        n = sum(1 for o in ov if o[0] == pool)
        out.append(f'<b>{_e(pool)}</b> is over its target utilisation in {n} month{"s" if n > 1 else ""} on committed work alone, '
                   f'worst in {mlabel(pf.months[i])} by {x:.0f} FTE. Contractors or a later start for a proposed project fix it '
                   f'(see Scenario Planner).')
    for p in sorted(pf.projects.values(), key=lambda p: -p['launch_slip']):
        if p['launch_slip'] > 0 and p['Funding'] != 'Stopped':
            hit = [d for d in pf.deps if d['From'] == p['ProjectID'] and not d['ok']]
            out.append(f'<b>{_e(p["Name"])}</b> release forecast {mlabel(p["launch_fc"])}, {p["launch_slip"]} months late'
                       + (f'; it now holds up {", ".join(_e(d["to_name"]) for d in hit)}.' if hit else '.'))
            break
    prop = sorted([p for p in pf.projects.values() if p['Funding'] == 'Proposed'], key=lambda p: -p['score'])
    if prop:
        p = prop[0]
        out.append(f'Highest-priority unfunded project: <b>{_e(p["Name"])}</b> (score {p["score"]:.0f}, ${p["ValueUSDm"]:,.0f}M value): '
                   f'{_e(p.get("funding_result", "")).lower()}'
                   + (f', blocked by {_e(p["blocker"][0])} in {mlabel(p["blocker"][1])}.' if p.get('blocker') else '.'))
    # shelf: committed load in the last two quarters of the horizon vs supply
    tail = range(max(0, pf.H - 6), pf.H)
    cap = sum(pf.supply[x][i] for x in pf.supply for i in tail)
    use = sum(pf.load_committed[x][i] for x in pf.supply for i in tail)
    if cap and use / cap < 0.5:
        out.append(f'Committed work uses only {use / cap * 100:.0f}% of capacity in the last six months of the horizon: '
                   f'the roadmap needs new commitments to keep teams loaded beyond {mlabel(pf.months[max(0, pf.H - 6)])}.')
    if R is not None:
        for s in PF.silicon_links(pf, R):
            if s['late_months'] is not None:
                out.append(f'Silicon: <b>{_e(s["name"])}</b> → product {_e(s["sku"])} qualifies {s["qual_done"]:%b %Y} in the supply plan; '
                           + (f'{-s["late_months"]} months of margin before the roadmap needs it ({mlabel(s["need_by"])}).' if s['late_months'] <= 0
                              else f'<b>{s["late_months"]} months after</b> the roadmap needs it ({mlabel(s["need_by"])}).'))
    up = pf.upcoming_gates(90)
    if up:
        out.append(f'{len(up)} gate decision{"s" if len(up) > 1 else ""} due in the next 90 days: '
                   + ', '.join(f'{_e(g["name"])} {_e(g["Gate"].split(" ", 1)[0])} ({g["eff"]:%d %b})' for g in up[:5]) + '.')
    return out


def _scenario_arg(ws, args):
    name = args.get('scenario') or ''
    sc = PF.scenarios(ws)
    adhoc = []
    if args.get('d_pid') and args.get('d_m'):
        try:
            adhoc.append({'Seq': 1, 'Change': 'Delay months', 'ProjectID': args['d_pid'], 'Value': int(args['d_m'])})
        except ValueError:
            pass
    if args.get('a_pool') and args.get('a_fte') and args.get('a_month'):
        try:
            adhoc.append({'Seq': 2, 'Change': 'Add FTE', 'Pool': args['a_pool'], 'Month': args['a_month'][:7], 'Value': float(args['a_fte'])})
        except ValueError:
            pass
    for i, (kind, key) in enumerate((('Fund', 'f_pid'), ('Stop', 's_pid')), start=3):
        if args.get(key):
            adhoc.append({'Seq': i, 'Change': kind, 'ProjectID': args[key]})
    if args.get('x_pid') and args.get('x_pct'):
        try:
            adhoc.append({'Seq': 5, 'Change': 'Scale demand %', 'ProjectID': args['x_pid'], 'Value': float(args['x_pct'])})
        except ValueError:
            pass
    if adhoc:
        return 'What-if', adhoc
    if name in sc:
        return name, sc[name]
    return None, None


# ------------------------------------------------------------------ overview
def overview(R, args, ws):
    pf = PF.Portfolio(ws)
    k = pf.kpis()
    live = [p for p in pf.projects.values() if p['Funding'] != 'Stopped']
    sections = [{'type': 'kpis', 'items': [
        K('Active projects', str(k['projects']), f'{k["committed"]} committed · {k["proposed"]} proposed'),
        K('Committed value', f'${k["value_committed"]:,.0f}M', f'${k["cost_usdm"]:,.0f}M engineering cost across all live projects'),
        K('Capacity used, next 12 months', f'{k["util12"]:.0f}%', 'committed work vs target capacity',
          'warn' if k['util12'] > 90 else 'ok'),
        K('Red projects', str(k['red']), f'{k["amber"]} amber · {k["dep_conflicts"]} dependency conflict{"s" if k["dep_conflicts"] != 1 else ""} · '
                                         f'{k["slipping"]} release slipping', 'bad' if k['red'] else 'warn' if k['amber'] else 'ok'),
        K('Over target capacity', f'{k["overload_fte_m"]:,.0f} FTE-months', f'in {k["overload_cells"]} pool-months, committed work',
          'bad' if k['overload_fte_m'] > 0 else 'ok'),
    ]}]
    ins = _insights(pf, R)
    sections.append(html('<section class="panel insights"><h2>Executive summary</h2><ul class="exec">' + ''.join(f'<li>{x}</li>' for x in ins)
                         + '</ul><p class="muted small">Written from the data each time the page loads. Change a table, a weight or a scenario and it updates.</p></section>'))
    bu = defaultdict(float)
    cat = defaultdict(float)
    for p in live:
        bu[p['BU']] += p['fte_years']
        cat[p['Category']] += p['fte_years']
    pts = [{'label': p['Name'], 'x': p['score'], 'y': float(p['ValueUSDm']), 'r': p['fte_years'],
            'cls': ('above' if p.get('funding_result') == 'Above the line' else 'proposed' if p['Funding'] == 'Proposed' else ''),
            'tip': f'{p["Name"]}: score {p["score"]:.0f}, value ${p["ValueUSDm"]:,.0f}M, {p["fte_years"]:.0f} FTE-years, {p.get("funding_result")}'}
           for p in live]
    sections.append(cols2(
        chart('Investment by business unit', charts.donut(sorted(bu.items(), key=lambda x: -x[1]), title='FTE-years', unit=' FTE-yr'),
              'Engineering FTE-years over each project\'s whole life.'),
        chart('Investment by category', charts.donut(sorted(cat.items(), key=lambda x: -x[1]), title='FTE-years', unit=' FTE-yr'))))
    sections.append(chart('Value against priority', charts.bubble(pts, 'Priority score', 'Value ($M)', xmax=100,
                                                                 quad=(60, 500, ['Big bets', 'Do now', 'Question marks', 'Quick wins'])),
                          'Bubble size = engineering FTE-years. Blue committed, purple proposed, red above the funding line.'))
    sections.append(_qgrid(pf, pf.load_committed, 'Capacity heatmap: committed work by quarter',
                           'Average utilisation of each skill pool. Red is above the pool\'s target utilisation. Click a pool for detail.'))
    rows = []
    for p in sorted(live, key=lambda p: (p['Funding'] != 'Committed', -p['score'])):
        ng = p.get('next_gate')
        rows.append({'name': p['Name'], 'pid': p['ProjectID'], 'BU': p['BU'], 'Category': p['Category'], 'Stage': p['Stage'],
                     'Funding': p['Funding'], 'launch': p['launch_fc'], 'slip': p['launch_slip'] or None, 'score': p['score'],
                     'value': float(p['ValueUSDm']), 'cost': p['cost_usdm'], 'health': _rags(p), 'health_sort': 'RAG'.find(p['health']),
                     'next': (f'{ng["Gate"]} · {ng["eff"]:%d %b %Y}' if ng and ng.get('eff') else '–'),
                     'fund_res': p.get('funding_result'), 'f_t': _fund_tone(p.get('funding_result'))})
    sections.append(table('Portfolio', [col('name', 'Project'), col('health', 'Health S·C·R·D', 'raw'), col('BU', 'BU'), col('Category', 'Category'),
                                        col('Stage', 'Stage'), col('fund_res', 'Funding', 'badge', tone='f_t'), col('launch', 'Release (forecast)', 'month'),
                                        col('slip', 'Slip (months)', 'int'), col('score', 'Priority', 'num0'), col('value', 'Value $M', 'num0'),
                                        col('cost', 'Cost $M', 'num1'), col('next', 'Next gate')],
                          rows, note='Health chips: Schedule, Capacity, Risk, Dependencies. Edit projects in Portfolio projects.'))
    return page('pf-overview', sections)


# ------------------------------------------------------------------ roadmap
def roadmap(R, args, ws):
    pf = PF.Portfolio(ws)
    by = args.get('by') or 'BU'
    fund = args.get('funding') or ''
    projs = [p for p in pf.projects.values() if (not fund or p['Funding'] == fund)]
    if not projs:
        return page('pf-roadmap', [callout('No projects match. Add projects in Portfolio projects.')])
    lanes_order = PF_BUS if by == 'BU' else PF_CATEGORIES
    groups = defaultdict(list)
    for p in projs:
        groups[p[by]].append(p)
    lanes = []
    for lane in lanes_order + sorted(set(groups) - set(lanes_order)):
        items = []
        for p in sorted(groups.get(lane, []), key=lambda p: p['Start']):
            gs = []
            for g in pf.gates.get(p['ProjectID'], []):
                if not g['eff']:
                    continue
                st = ('passed' if g['Status'] == 'Passed' else 'conditional' if g['Status'] == 'Conditional'
                      else 'late' if (g['slip'] > 0 or g['overdue']) else 'planned')
                gs.append((g['eff'], f'{p["Name"]} {g["Gate"]}', st))
            cls = 'stopped' if p['Funding'] == 'Stopped' else 'sustain' if p['Stage'] == 'Sustain' else p['Funding'].lower()
            sustain = p['Stage'] == 'Sustain'
            items.append({'id': p['ProjectID'], 'name': p['Name'] + (' (sustaining)' if sustain else ''),
                          'start': max(_d(p['Start']), _d(month_add(pf.start, -18))) if sustain else _d(p['Start']),
                          'end': _d(month_add(pf.start, pf.H)) if sustain else _m_end(p['Launch']),
                          'fc_end': _m_end(p['launch_fc']) if p['launch_slip'] > 0 else None, 'cls': f'{cls} h-{p["health"]}', 'gates': gs,
                          'tip': f'{p["Name"]} ({p["Category"]}, {p["Stage"]}, {p["Funding"]}): {mlabel(p["Start"])} to {mlabel(p["Launch"])}'})
        if items:
            lanes.append((lane, items))
    st = min(_d(p['Start']) for p in projs if p['Stage'] != 'Sustain') if any(p['Stage'] != 'Sustain' for p in projs) else _d(pf.start)
    st = max(st, _d(month_add(pf.start, -18)))
    en = max(_m_end(p['launch_fc']) for p in projs) + timedelta(days=60)
    deps = [(d['From'], d['To'], d['ok']) for d in pf.deps]
    filt = ('<div class="panel-head"><span class="muted small">Lanes</span>' + _chips('by', [('BU', 'Business unit'), ('Category', 'Category')], by, args)
            + '<span class="muted small">Funding</span>' + _chips('funding', [('', 'All'), ('Committed', 'Committed'), ('Proposed', 'Proposed'), ('Stopped', 'Stopped')], fund, args)
            + '</div>')
    k = pf.kpis()
    sections = [html(filt), {'type': 'kpis', 'items': [
        K('Releases in the next 12 months', str(sum(1 for p in projs if pf.start <= p['launch_fc'] <= month_add(pf.start, 11) and p['Funding'] != 'Stopped')), ''),
        K('Slipping releases', str(k['slipping']), 'forecast later than target', 'bad' if k['slipping'] else 'ok'),
        K('Dependency conflicts', str(k['dep_conflicts']), 'a project launches before what it needs', 'bad' if k['dep_conflicts'] else 'ok'),
        K('Gates in the next 90 days', str(len(pf.upcoming_gates(90))), 'see Portfolio Board & Gates'),
    ]}]
    sections.append(chart('Roadmap', charts.roadmap(lanes, st, en, today=[(pf.as_of, 'today', 'today')], deps=deps),
                          'Bars run from start to target release; red extension = forecast slip. Diamonds are gates: green passed, amber conditional, '
                          'red late, hollow planned. Dashed lines are dependencies (red = conflict). Purple bars are proposed, not yet funded.'))
    drows = [dict(d, status=('OK' if d['ok'] else 'Conflict'), s_t=('ok' if d['ok'] else 'bad')) for d in pf.deps]
    sections.append(table('Dependencies', [col('status', 'Check', 'badge', tone='s_t'), col('from_name', 'Delivers'), col('to_name', 'Needed by'),
                                           col('Type', 'Type'), col('LagMonths', 'Lag (months)', 'int'), col('need', 'Needed by (month)', 'month'),
                                           col('gap', 'Margin (months)', 'int'), col('msg', 'Conflict')], drows, search=False,
                          note='Margin = needing project\'s release − (delivering project\'s forecast release + lag). Negative = conflict.'))
    # Jira drift
    jira = {r['JiraKey']: r for r in ws['tables'].get('pf_jira', [])}
    jrows = []
    for p in projs:
        j = jira.get(p.get('JiraKey') or '')
        if not j:
            continue
        due = to_date(j.get('DueDate'))
        drift = PF.mdiff(p['Launch'], f'{due:%Y-%m}') if due else None
        tot = int(j['Total'] or 0)
        jrows.append({'name': p['Name'], 'key': j['JiraKey'], 'status': j.get('Status'), 'done': (int(j['Done']) / tot * 100) if tot else None,
                      'due': f'{due:%Y-%m}' if due else None, 'launch': p['Launch'], 'drift': drift,
                      'd_t': ('bad' if drift and drift > 0 else 'ok'), 'flag': ('Jira later than roadmap' if drift and drift > 0 else 'Aligned'),
                      'synced': j.get('Synced')})
    if jrows:
        sections.append(table('Roadmap vs Jira', [col('name', 'Project'), col('key', 'Epic'), col('status', 'Jira status'), col('done', 'Issues done %', 'num0'),
                                                  col('due', 'Jira due', 'month'), col('launch', 'Roadmap release', 'month'), col('drift', 'Drift (months)', 'int'),
                                                  col('flag', 'Check', 'badge', tone='d_t')], jrows, search=False,
                              note='From Jira & Confluence (demo rows until you connect your site). Drift = Jira due date − roadmap target.'))
    sil = PF.silicon_links(pf, R) if R else []
    if sil:
        srows = [dict(s, q=(f'{s["qual_done"]:%d %b %Y}' if s['qual_done'] else '–'), smp=(f'{s["samples"]:%d %b %Y}' if s['samples'] else '–'),
                      m_t=('bad' if s['late_months'] and s['late_months'] > 0 else 'ok'),
                      margin=(-s['late_months'] if s['late_months'] is not None else None),
                      check=('Late' if s['late_months'] and s['late_months'] > 0 else 'On time' if s['late_months'] is not None else 'Not in supply plan'))
                 for s in sil]
        sections.append(table('Roadmap to silicon', [col('name', 'Project'), col('sku', 'Supply-plan product'), col('smp', 'Samples ready'),
                                                     col('q', 'Qualified'), col('need_by', 'Roadmap needs it', 'month'), col('margin', 'Margin (months)', 'int'),
                                                     col('check', 'Check', 'badge', tone='m_t')], srows, search=False,
                              note='Projects that become silicon are linked to a product in the supply plan (LinkedSKU). Dates come from NPI Management: '
                                   'wafer starts, OSAT steps and qualification. "Needs it" = earliest of its own release and what dependent projects need.'))
    return page('pf-roadmap', sections)


# ------------------------------------------------------------------ capacity
def capacity(R, args, ws):
    name, changes = _scenario_arg(ws, args)
    pf = PF.Portfolio(ws, changes, name)
    mode = args.get('mode') or 'committed'
    load = {'committed': pf.load_committed, 'line': pf.load_line, 'all': pf.load_all}.get(mode, pf.load_committed)
    pools = list(pf.supply)
    pool = args.get('pool') if args.get('pool') in pools else None
    if not pool:
        ov = sorted(pf.overloads(load), key=lambda x: -x[2])
        pool = ov[0][0] if ov else (pools[0] if pools else None)
    if not pool:
        return page('pf-capacity', [callout('Add skill pools in Skill pools and resource demand in Resource demand.')])
    mode_opts = [('committed', 'Committed'), ('line', 'Committed + fundable'), ('all', 'Everything proposed')]
    sections = [html('<div class="panel-head"><span class="muted small">Demand</span>' + _chips('mode', mode_opts, mode, args)
                     + '<span class="muted small">Pool</span>' + _chips('pool', [(x, x) for x in pools], pool, args) + '</div>')]
    if name:
        sections.append(callout(f'Scenario <b>{_e(name)}</b> applied. <a href="/m/pf-capacity?mode={_e(mode)}&pool={_e(pool)}">Back to baseline</a>', 'info'))
    ov = pf.overloads(load)
    tot_sup = sum(pf.supply[x][0] for x in pools)
    gap_q = []
    for q, idx in pf.quarters():
        for x in pools:
            need = max(load[x][i] - pf.supply[x][i] * pf.target[x] for i in idx)
            if need > 0.5:
                gap_q.append({'quarter': q, 'pool': x, 'fte': need, 'cost': need * float(pf.pools[x]['CostPerFTEk']) / 4 / 1000})
    sections.append({'type': 'kpis', 'items': [
        K('Engineers', f'{tot_sup:,.0f} FTE', f'{len(pools)} skill pools'),
        K('Pool-months over target', str(len(ov)), f'{sum(x for _, _, x in ov):,.0f} FTE-months over', 'bad' if ov else 'ok'),
        K('Peak extra FTE needed', f'{max([g["fte"] for g in gap_q] + [0]):,.0f}', 'largest single-pool gap in a quarter', 'warn' if gap_q else 'ok'),
        K(f'{pool} next 12 months', f'{sum(load[pool][:12]) / max(1, sum(pf.supply[pool][:12])) * 100:.0f}%', f'target {pf.target[pool] * 100:.0f}%'),
    ]})
    sections.append(_qgrid(pf, load, 'Utilisation by quarter', 'Average of the months in each quarter. Red above target.'))
    # stacked demand by project for the pool
    contrib = sorted(((pid, v[pool]) for pid, v in pf.pdem.items() if pool in v and sum(v[pool]) > 0
                      and (mode == 'all' or pf.projects[pid]['Funding'] == 'Committed' or (mode == 'line' and pf.projects[pid].get('fund_shift') is not None))),
                     key=lambda x: -sum(x[1]))
    series = []
    for pid, v in contrib[:7]:
        sh = pf.projects[pid].get('fund_shift') or 0
        vv = ([0.0] * sh + v[:pf.H - sh]) if (mode == 'line' and pf.projects[pid]['Funding'] == 'Proposed') else v
        series.append((pf.projects[pid]['Name'], vv))
    if len(contrib) > 7:
        rest = [sum(v[i] for _, v in contrib[7:]) for i in range(pf.H)]
        series.append(('Other', rest))
    cap_line = [pf.supply[pool][i] * pf.target[pool] for i in range(pf.H)]
    sections.append(chart(f'{pool}: demand by project vs capacity',
                          charts.bars(pf.months, series, lines=[('Target capacity', cap_line), ('Headcount', pf.supply[pool])], unit=' FTE',
                                      title=pool),
                          'Stacked demand from each project. Lines: headcount and headcount × target utilisation.'))
    if gap_q:
        sections.append(table('Capacity asks', [col('quarter', 'Quarter'), col('pool', 'Pool'), col('fte', 'Extra FTE needed (peak month)', 'num1'),
                                                col('cost', 'Quarter cost $M', 'num2')], gap_q, search=False,
                              note='Extra FTE to keep each pool at its target utilisation in its worst month of the quarter, costed at the pool\'s '
                                   'loaded cost. This is the resource request to take to the Portfolio Board.'))
    ch = [dict(c) for c in pf.t['pf_capacity_changes']]
    sections.append(table('Planned capacity changes', [col('Pool', 'Pool'), col('Month', 'From', 'month'), col('DeltaFTE', 'FTE change', 'num1'),
                                                       col('Reason', 'Reason')], ch, search=False, empty='No hires or changes planned.',
                          note='Edit in Capacity changes. Scenario rows of type Add FTE show here as Scenario.'))
    prow = [{'pool': x, 'fte': pf.supply[x][0], 'target': pf.target[x] * 100, 'cost': float(pf.pools[x]['CostPerFTEk']),
             'peak': max(load[x]) if load[x] else 0, 'peak_m': pf.months[load[x].index(max(load[x]))] if load[x] and max(load[x]) > 0 else None,
             'site': pf.pools[x].get('Site')} for x in pools]
    sections.append(table('Skill pools', [col('pool', 'Pool'), col('fte', 'FTE today', 'num0'), col('target', 'Target util %', 'num0'),
                                          col('peak', 'Peak demand FTE', 'num1'), col('peak_m', 'Peak month', 'month'), col('cost', 'Cost / FTE-year $k', 'num0'),
                                          col('site', 'Sites')], prow, search=False))
    return page('pf-capacity', sections)


# ------------------------------------------------------------------ prioritisation
def priority(R, args, ws):
    pf = PF.Portfolio(ws)
    w = pf.weights()
    live = [p for p in pf.projects.values() if p['Funding'] != 'Stopped']
    k = pf.kpis()
    fits_now = sum(float(p['ValueUSDm']) for p in live if p['Funding'] == 'Proposed' and p.get('funding_result') == 'Fits now')
    later = sum(float(p['ValueUSDm']) for p in live if str(p.get('funding_result', '')).startswith('Fits if'))
    sections = [{'type': 'kpis', 'items': [
        K('Proposed value that fits now', f'${fits_now:,.0f}M', 'inside target capacity after committed work', 'ok'),
        K('Fits with a later start', f'${later:,.0f}M', 'start delayed until capacity frees up', 'warn' if later else 'ok'),
        K('Above the line', f'${k["value_above"]:,.0f}M', f'no start within {PF.MAX_SHIFT} months fits', 'bad' if k['value_above'] else 'ok'),
        K('Top weight', max(w, key=w.get), ' · '.join(f'{c} {w[c]:.0f}%' for c in PF.CRIT_COL)),
    ]}]
    rows = []
    rank = 0
    for p in sorted(live, key=lambda p: (p['Funding'] != 'Committed', -p['score'])):
        rank += 1
        sh = p.get('fund_shift')
        rows.append({'rank': rank, 'name': p['Name'], 'Funding': p['Funding'], 'BU': p['BU'], 'score': p['score'],
                     'v': p['crit']['Value'], 'fit': p['crit']['Strategic fit'], 'dem': p['crit']['Customer demand'],
                     'tc': p['crit']['Time criticality'], 'rk': float(p['TechRisk']), 'value': float(p['ValueUSDm']), 'cost': p['cost_usdm'],
                     'roi': p['value_per_cost'], 'res': p.get('funding_result'), 'r_t': _fund_tone(p.get('funding_result')),
                     'block': (f'{p["blocker"][0]} · {mlabel(p["blocker"][1])}' if p.get('blocker') else ''),
                     'start_if': (month_add(p['Start'], sh) if sh is not None else None),
                     'launch_if': (month_add(p['launch_fc'], sh) if sh is not None else None)})
    sections.append(table('Ranked portfolio and funding line',
                          [col('rank', '#', 'int'), col('name', 'Project'), col('score', 'Score', 'num1'),
                           col('v', 'Value (1-5)', 'num1'), col('fit', 'Fit', 'num0'), col('dem', 'Demand', 'num0'), col('tc', 'Time crit.', 'num0'),
                           col('rk', 'Risk', 'num0'), col('value', 'Value $M', 'num0'), col('cost', 'Cost $M', 'num1'), col('roi', 'Value ÷ cost', 'num1'),
                           col('res', 'Funding line', 'badge', tone='r_t'), col('block', 'Blocked by'), col('start_if', 'Earliest start', 'month'),
                           col('launch_if', 'Release if funded', 'month')], rows, search=False,
                          note='Committed projects take capacity first. Proposed projects are then added in score order; each is placed at the earliest '
                               f'start (up to {PF.MAX_SHIFT} months late) that keeps every pool at or under its target utilisation.'))
    pts = [{'label': p['Name'], 'x': p['score'], 'y': p['cost_usdm'], 'r': float(p['ValueUSDm']),
            'cls': ('above' if p.get('funding_result') == 'Above the line' else 'proposed' if p['Funding'] == 'Proposed' else '')} for p in live]
    sections.append(chart('Score against cost', charts.bubble(pts, 'Priority score', 'Engineering cost ($M)', xmax=100,
                                                         quad=(60, 15, ['Expensive, lower priority', 'Strategic bets', 'Cheap, lower priority', 'Best value'])),
                          'Bubble size = value. Lower right is the best use of engineers. Blue committed, purple proposed, red above the line.'))
    sections.append(html('<section class="panel"><h2>How the score works</h2><p class="sub">Each criterion is on a 1-5 scale. Value is scaled across the live '
             'portfolio (lowest = 1, highest = 5). Technical risk counts against (6 − risk).</p>'
             f'<p class="formula">Score = Σ (criterion × weight) ÷ Σ weights × 20</p>'
             '<p class="sub">So 100 = top marks on every criterion. Change weights in Prioritisation weights to see the ranking and the funding line move: '
             'for example raise Time criticality to 30% before a competitive cycle.</p></section>'))
    return page('pf-priority', sections)


# ------------------------------------------------------------------ scenarios
def scenario(R, args, ws):
    sc = PF.scenarios(ws)
    name, changes = _scenario_arg(ws, args)
    base = PF.Portfolio(ws)
    pids = sorted(base.projects)
    pools = list(base.supply)
    opts = [(n, n) for n in sc]
    sections = [html('<div class="panel-head"><span class="muted small">Saved scenarios</span>'
                     + (_chips('scenario', opts, args.get('scenario') if not args.get('d_pid') and not args.get('a_pool') else '', {}) if opts else '<span class="muted small">none yet</span>')
                     + '</div>')]
    po = ''.join(f'<option value="{_e(p)}" {"selected" if args.get("d_pid") == p else ""}>{_e(base.projects[p]["Name"])}</option>' for p in pids)
    poo = ''.join(f'<option {"selected" if args.get("a_pool") == x else ""}>{_e(x)}</option>' for x in pools)
    prop = ''.join(f'<option value="{_e(p)}" {"selected" if args.get("f_pid") == p else ""}>{_e(base.projects[p]["Name"])}</option>'
                   for p in pids if base.projects[p]['Funding'] == 'Proposed')
    live = ''.join(f'<option value="{_e(p)}" {"selected" if args.get("s_pid") == p else ""}>{_e(base.projects[p]["Name"])}</option>'
                   for p in pids if base.projects[p]['Funding'] != 'Stopped')
    xo = ''.join(f'<option value="{_e(p)}" {"selected" if args.get("x_pid") == p else ""}>{_e(base.projects[p]["Name"])}</option>' for p in pids)
    form = (f'<section class="panel"><h2>Quick what-if</h2><p class="sub">Combine any of these and press Run. Nothing is saved until you press Save.</p>'
            f'<form method="get" class="formgrid">'
            f'<label>Delay project<select name="d_pid"><option value="">–</option>{po}</select></label>'
            f'<label>by months<input type="number" name="d_m" min="-12" max="24" value="{_e(args.get("d_m") or 3)}"></label>'
            f'<label>Add FTE to pool<select name="a_pool"><option value="">–</option>{poo}</select></label>'
            f'<label>FTE<input type="number" name="a_fte" min="-500" max="500" step="1" value="{_e(args.get("a_fte") or 10)}"></label>'
            f'<label>from<input type="month" name="a_month" value="{_e(args.get("a_month") or base.start)}"></label>'
            f'<label>Fund<select name="f_pid"><option value="">–</option>{prop}</select></label>'
            f'<label>Stop<select name="s_pid"><option value="">–</option>{live}</select></label>'
            f'<label>Scale demand of<select name="x_pid"><option value="">–</option>{xo}</select></label>'
            f'<label>by %<input type="number" name="x_pct" min="-90" max="200" value="{_e(args.get("x_pct") or "")}" placeholder="-15"></label>'
            f'<div><button class="btn" type="submit">Run</button> <a class="btn ghost" href="/m/pf-scenarios">Clear</a></div></form></section>')
    sections.append(html(form))
    if not changes:
        sections.append(callout('Pick a saved scenario or build a what-if above. The baseline is the portfolio as it is in the data tables.', 'info'))
        sections.append(table('Saved scenario rows', [col('Scenario', 'Scenario'), col('Seq', '#', 'int'), col('Change', 'Change'), col('ProjectID', 'Project'),
                                                      col('Pool', 'Pool'), col('Month', 'Month', 'month'), col('Value', 'Value', 'num1'), col('Note', 'Note')],
                              ws['tables'].get('pf_scenarios', []), search=False, note='Edit in Scenarios.'))
        return page('pf-scenarios', sections)
    scen = PF.Portfolio(ws, changes, name)
    cmp = PF.compare(base, scen)
    kb, ks = cmp['base'], cmp['scen']

    def dlt(a, b, good='down', fmt='{:,.0f}'):
        d = b - a
        if abs(d) < 1e-6:
            return 'no change', ''
        tone = ('ok' if (d < 0) == (good == 'down') else 'bad')
        return (('+' if d > 0 else '') + fmt.format(d)), tone

    items = []
    for lab, key, good, f, unit in (('Over target capacity', 'overload_fte_m', 'down', '{:,.0f}', ' FTE-months'),
                                    ('Value above the line', 'value_above', 'down', '{:,.0f}', ' $M'),
                                    ('Dependency conflicts', 'dep_conflicts', 'down', '{:,.0f}', ''),
                                    ('Red projects', 'red', 'down', '{:,.0f}', ''),
                                    ('Capacity used, next 12 months', 'util12', 'none', '{:,.1f}', ' %')):
        d, tone = dlt(kb[key], ks[key], good, f)
        items.append(K(lab, f.format(ks[key]) + unit, f'baseline {f.format(kb[key])} · {d}', tone if good != 'none' else ''))
    sections.append({'type': 'kpis', 'items': items})
    desc = '; '.join(_describe(c, base) for c in sorted(changes, key=lambda c: c.get('Seq') or 0))
    note = ''.join(f'<br><span class="muted small">{_e(n)}</span>' for n in scen.notes)
    save = ''
    if name == 'What-if':
        hidden = ''.join(f'<input type="hidden" name="{_e(k_)}" value="{_e(v)}">' for k_, v in args.items() if k_ not in ('msg', 'err', 'scenario'))
        save = (f'<form method="post" action="/pf/scenario/save" class="actrow">{hidden}<input name="name" required maxlength="60" placeholder="Scenario name" '
                f'aria-label="Scenario name"><button class="btn sm" type="submit">Save as scenario</button></form>')
    sections.append(html(f'<section class="panel"><h2>Scenario: {_e(name)}</h2><p>{_e(desc)}{note}</p>{save}'
                         f'<p class="muted small"><a href="/m/pf-capacity?{_e(urlencode({k_: v for k_, v in args.items() if k_ not in ("msg", "err")}))}">Open capacity with this scenario</a></p></section>'))
    rows = [dict(r, f_b=_fund_tone(r['base_fund']), f_s=_fund_tone(r['scen_fund'])) for r in cmp['rows'] if r['changed']]
    sections.append(table('What changes', [col('name', 'Project'), col('base_launch', 'Release (baseline)', 'month'), col('scen_launch', 'Release (scenario)', 'month'),
                                           col('shift', 'Moved (months)', 'int'), col('base_fund', 'Funding (baseline)', 'badge', tone='f_b'),
                                           col('scen_fund', 'Funding (scenario)', 'badge', tone='f_s'), col('base_health', 'Health before'),
                                           col('scen_health', 'Health after'), col('fte_delta', 'FTE-years change', 'num1')], rows, search=False,
                          empty='No project changes outcome in this scenario.'))
    sections.append(cols2(_qgrid(base, base.load_line, 'Baseline: committed + fundable'),
                          _qgrid(scen, scen.load_line, 'Scenario: committed + fundable')))
    bad = [d for d in scen.deps if not d['ok']]
    if bad:
        sections.append(table('Dependency conflicts in this scenario', [col('from_name', 'Delivers'), col('to_name', 'Needed by'), col('msg', 'Conflict')],
                              bad, search=False))
    return page('pf-scenarios', sections)


def _describe(c, pf):
    nm = pf.projects.get(c.get('ProjectID') or '', {}).get('Name', c.get('ProjectID'))
    v = c.get('Value')
    return {'Delay months': f'delay {nm} by {int(v or 0)} months',
            'Stop': f'stop {nm}', 'Fund': f'fund {nm}',
            'Scale demand %': f'scale {nm} demand by {float(v or 0):+.0f}%',
            'Add FTE': f'add {float(v or 0):+.0f} FTE to {c.get("Pool")} from {mlabel(c["Month"]) if c.get("Month") else "?"}'}.get(c['Change'], c['Change'])


# ------------------------------------------------------------------ portfolio board
def recommend(pf, g):
    p = pf.projects[g['ProjectID']]
    if g.get('Readiness') is None:
        return 'Assess first', 'info', 'Readiness checklist not filled in yet (Lifecycle gates → Readiness).'
    rd = float(g.get('Readiness') or 0)
    issues = []
    if p['Funding'] == 'Proposed' and p.get('funding_result') != 'Fits now' and g['Gate'] in ('G1 Plan approval', 'G2 Development commit'):
        issues.append(f'capacity: {str(p.get("funding_result", "")).lower()}')
    if p['rag']['Risk'] == 'R':
        issues.append('open high risk')
    if p['rag']['Dependencies'] == 'R':
        issues.append('dependency conflict')
    if rd >= 85 and not issues:
        return 'Approve', 'ok', 'Ready: checklist complete and capacity available.'
    if rd >= 70:
        return 'Approve with conditions', 'warn', 'Conditions: ' + (', '.join(issues) if issues else f'close the remaining {100 - rd:.0f}% of the checklist') + '.'
    return 'Defer', 'bad', f'Readiness {rd:.0f}%' + (' and ' + ', '.join(issues) if issues else '') + '.'


def board(R, args, ws):
    pf = PF.Portfolio(ws)
    up = pf.upcoming_gates(int(args.get('days') or 120))
    overdue = [g for gl in pf.gates.values() for g in gl if g['overdue']]
    sections = [html('<div class="panel-head"><span class="muted small">Look ahead</span>'
                     + _chips('days', [('60', '60 days'), ('120', '120 days'), ('365', '12 months')], args.get('days') or '120', args)
                     + '<a class="btn ghost sm" href="/export/board-pack.xlsx">Download board pack (Excel)</a>'
                     + '<form method="post" action="/pf/confluence/publish" style="display:inline"><button class="btn ghost sm" type="submit">Publish board pack to Confluence</button></form>'
                     + '</div>')]
    sections.append({'type': 'kpis', 'items': [
        K('Gate decisions due', str(len(up)), f'next {args.get("days") or 120} days'),
        K('Ready to approve', str(sum(1 for g in up if recommend(pf, g)[0] == 'Approve')), 'readiness ≥ 85%, capacity and risk clear', 'ok'),
        K('Overdue gates', str(len(overdue)), 'planned date passed without a decision', 'bad' if overdue else 'ok'),
        K('Decisions logged', str(len(ws['tables'].get('pf_decisions', []))), 'Decision log'),
    ]})
    trs = []
    for g in up:
        rec, tone, why = recommend(pf, g)
        p = pf.projects[g['ProjectID']]
        opts = ''.join(f'<option {"selected" if o == rec else ""}>{o}</option>' for o in ('Approve', 'Approve with conditions', 'Defer', 'Re-scope', 'Stop'))
        form = (f'<form method="post" action="/pf/gate/decide" class="decform"><input type="hidden" name="pid" value="{_e(g["ProjectID"])}">'
                f'<input type="hidden" name="gate" value="{_e(g["Gate"])}"><select name="decision" aria-label="Decision">{opts}</select>'
                f'<input name="summary" maxlength="200" placeholder="Decision note" aria-label="Decision note"><button class="btn sm" type="submit">Record</button></form>')
        trs.append(f'<tr><td class="nw">{g["eff"]:%d %b %Y}</td><td><b>{_e(p["Name"])}</b><div class="muted small">{_e(p["BU"])} · {_e(p["Category"])}</div></td>'
                   f'<td>{_e(g["Gate"])}</td><td class="r">{(str(round(g["Readiness"])) + "%") if g.get("Readiness") is not None else "–"}</td><td class="nw">{_rags(p)}</td>'
                   f'<td><span class="badge {_fund_tone(p.get("funding_result"))}">{_e(p.get("funding_result"))}</span></td>'
                   f'<td><span class="badge {tone}">{_e(rec)}</span><div class="muted small wrap">{_e(why)}</div></td><td>{form}</td></tr>')
    sections.append(html('<section class="panel"><h2>Upcoming gate decisions</h2><p class="sub">The recommendation reads the readiness checklist, the funding line, '
                         'open risks and dependencies. Record the board\'s decision: it is added to the Decision log and the gate status is updated.</p>'
                         '<div class="tablewrap"><table><thead><tr><th>Date</th><th>Project</th><th>Gate</th><th class="r">Readiness</th><th>Health S·C·R·D</th>'
                         '<th>Funding line</th><th>Recommendation</th><th>Decision</th></tr></thead><tbody>'
                         + (''.join(trs) or '<tr><td colspan="8" class="muted">No gates due in this window.</td></tr>') + '</tbody></table></div></section>'))
    if overdue:
        sections.append(table('Overdue gates', [col('ProjectID', 'Project'), col('Gate', 'Gate'), col('Planned', 'Planned', 'date'), col('Status', 'Status')],
                              overdue, search=False))
    names = {pid: p['Name'] for pid, p in pf.projects.items()}
    dec = sorted([dict(d, name=names.get(d['ProjectID'], d['ProjectID']),
                       d_t=('ok' if d['Decision'] == 'Approve' else 'warn' if d['Decision'] in ('Approve with conditions', 'Re-scope') else 'bad'))
                  for d in ws['tables'].get('pf_decisions', [])], key=lambda d: str(d['Date']), reverse=True)
    sections.append(table('Decision log', [col('Date', 'Date', 'date'), col('Forum', 'Forum'), col('name', 'Project'), col('Gate', 'Gate'),
                                           col('Decision', 'Decision', 'badge', tone='d_t'), col('Summary', 'Summary'), col('Owner', 'Owner'),
                                           col('ActionDue', 'Action due', 'date')], dec, search=False))
    # gate pipeline: count by stage
    st = defaultdict(int)
    for p in pf.projects.values():
        st[p['Stage']] += 1
    sections.append(chart('Lifecycle pipeline', charts.bars(PF.STAGE_ORDER, [('Projects', [st.get(s, 0) for s in PF.STAGE_ORDER])], title='Projects by stage'),
                          'How many projects sit at each stage: a healthy pipeline keeps ideas and concepts coming behind the projects in development.'))
    return page('pf-board', sections)


# ------------------------------------------------------------------ RAID
def raid(R, args, ws):
    pf = PF.Portfolio(ws)
    names = {pid: p['Name'] for pid, p in pf.projects.items()}
    rk = [r for r in ws['tables'].get('pf_risks', [])]
    open_ = [r for r in rk if r['Status'] != 'Closed']
    grid = defaultdict(list)
    for r in open_:
        grid[(int(r['Probability']), int(r['Impact']))].append(r['RiskID'])
    cells = ['<div class="h"></div>'] + [f'<div class="h">I{i}</div>' for i in range(1, 6)]
    for p_ in range(5, 0, -1):
        cells.append(f'<div class="h">P{p_}</div>')
        for i in range(1, 6):
            z = 'z3' if p_ * i >= 15 else 'z2' if p_ * i >= 8 else 'z1'
            ids = grid.get((p_, i), [])
            cells.append(f'<div class="{z}" title="P{p_} × I{i} = {p_ * i}">{_e(" ".join(ids))}</div>')
    sections = [{'type': 'kpis', 'items': [
        K('Open RAID items', str(len(open_)), f'{sum(1 for r in open_ if r["Type"] == "Risk")} risks · {sum(1 for r in open_ if r["Type"] == "Issue")} issues'),
        K('High (P×I ≥ 15)', str(sum(1 for r in open_ if int(r['Probability']) * int(r['Impact']) >= 15)), '', 'bad'),
        K('Overdue actions', str(sum(1 for r in open_ if to_date(r.get('Due')) and to_date(r['Due']) < pf.as_of)), '', 'warn'),
        K('Dependency conflicts', str(sum(1 for d in pf.deps if not d['ok'])), 'from the roadmap'),
    ]}]
    sections.append(cols2(html(f'<section class="panel"><h2>Risk heatmap</h2><p class="sub">Open items by probability (P) and impact (I).</p>'
                               f'<div class="riskgrid">{"".join(cells)}</div></section>'),
                          table('Top exposures', [col('RiskID', 'ID'), col('name', 'Project'), col('Title', 'Item'), col('score', 'P×I', 'int')],
                                sorted([dict(r, name=names.get(r['ProjectID'], r['ProjectID']), score=int(r['Probability']) * int(r['Impact'])) for r in open_],
                                       key=lambda r: -r['score'])[:6], search=False)))
    rows = [dict(r, name=names.get(r['ProjectID'], r['ProjectID']), score=int(r['Probability']) * int(r['Impact']),
                 s_t=('bad' if int(r['Probability']) * int(r['Impact']) >= 15 else 'warn' if int(r['Probability']) * int(r['Impact']) >= 8 else 'ok'))
            for r in rk]
    rows.sort(key=lambda r: (r['Status'] == 'Closed', -r['score']))
    sections.append(table('RAID log', [col('RiskID', 'ID'), col('Type', 'Type'), col('name', 'Project'), col('Title', 'Item'),
                                       col('score', 'P×I', 'badge', tone='s_t'), col('Owner', 'Owner'), col('Mitigation', 'Mitigation'),
                                       col('Due', 'Due', 'date'), col('Status', 'Status')], rows, note='Edit in RAID log.'))
    drows = [dict(d, status=('OK' if d['ok'] else 'Conflict'), s_t=('ok' if d['ok'] else 'bad')) for d in pf.deps]
    sections.append(table('Dependencies', [col('status', 'Check', 'badge', tone='s_t'), col('from_name', 'Delivers'), col('to_name', 'Needed by'),
                                           col('Type', 'Type'), col('gap', 'Margin (months)', 'int'), col('Note', 'Note'), col('msg', 'Conflict')],
                          drows, search=False))
    return page('pf-raid', sections)


# ------------------------------------------------------------------ integrations
def integrations(R, args, ws, status=None):
    from . import integrations as IG
    cfg = IG.config(ws)
    st = status or IG.status(cfg)
    jira = ws['tables'].get('pf_jira', [])
    mode = 'on' if st['jira_ready'] else 'demo'
    sections = [{'type': 'kpis', 'items': [
        K('Jira', 'Connected' if st['jira_ready'] else 'Demo data', st['jira_note'], 'ok' if st['jira_ready'] else 'warn'),
        K('Confluence', 'Connected' if st['conf_ready'] else 'Not set up', st['conf_note'], 'ok' if st['conf_ready'] else 'warn'),
        K('Epics tracked', str(len(jira)), f'last sync: {jira[0].get("Synced") if jira else "never"}'),
        K('Source of credentials', st['source'], 'environment variables override the form'),
    ]}]
    tok_set = bool(cfg.get('token'))
    form = (f'<section class="panel"><h2>Connect your Atlassian site</h2>'
            f'<p class="sub">Jira and Confluence Cloud use the same site and an API token (Atlassian account → Security → API tokens). '
            f'The token is kept with this browser\'s workspace only, is never exported to Excel, and is deleted with the workspace. '
            f'For a permanent setup, the site owner can set <code>ATLASSIAN_SITE</code>, <code>ATLASSIAN_EMAIL</code>, <code>ATLASSIAN_TOKEN</code>, '
            f'<code>CONFLUENCE_SPACE</code> as environment variables instead.</p>'
            f'<form method="post" action="/pf/integrations/save" class="formgrid">'
            f'<label>Site<input name="site" placeholder="https://your-company.atlassian.net" value="{_e(cfg.get("site"))}" maxlength="120"></label>'
            f'<label>Email<input name="email" type="email" value="{_e(cfg.get("email"))}" maxlength="120"></label>'
            f'<label>API token<input name="token" type="password" placeholder="{"saved (leave blank to keep)" if tok_set else ""}" maxlength="300" autocomplete="off"></label>'
            f'<label style="grid-column:span 2">Epics JQL<input name="jql" value="{_e(cfg.get("jql") or IG.DEFAULT_JQL)}" maxlength="300"></label>'
            f'<label>Confluence space key<input name="space" value="{_e(cfg.get("space"))}" maxlength="40" placeholder="PORT"></label>'
            f'<div><button class="btn" type="submit">Save</button></div></form>'
            f'<div class="actions" style="margin-top:10px">'
            f'<form method="post" action="/pf/integrations/test"><button class="btn ghost sm" type="submit">Test connection</button></form>'
            f'<form method="post" action="/pf/jira/sync"><button class="btn ghost sm" type="submit">Sync epics from Jira</button></form>'
            f'<form method="post" action="/pf/confluence/publish"><button class="btn ghost sm" type="submit">Publish board pack to Confluence</button></form>'
            f'<form method="post" action="/pf/integrations/clear"><button class="btn ghost sm" type="submit">Forget credentials</button></form></div></section>')
    sections.append(html(form))
    sections.append(html('<section class="panel"><h2>What the integration does</h2><ul class="exec">'
                         '<li><b>Jira → roadmap.</b> Runs the epics JQL, reads each epic\'s status and due date, and counts its child issues by status category '
                         '(done, in progress, to do). Epics are matched to projects by JiraKey. The Roadmap page compares the Jira due date with the roadmap '
                         'target and flags drift.</li>'
                         '<li><b>Roadmap → Confluence.</b> Publishes the board pack (executive summary, portfolio table, funding line, capacity asks, '
                         'upcoming gates, decisions) as a page in your space. Publishing again updates the same page and keeps its history.</li>'
                         '<li><b>Calls used:</b> Jira <code>GET /rest/api/3/search/jql</code>; Confluence <code>GET /wiki/api/v2/spaces</code>, '
                         '<code>GET/POST /wiki/api/v2/pages</code>, <code>PUT /wiki/api/v2/pages/{id}</code>. Read-only on Jira.</li>'
                         '<li>Without credentials the page runs on demo epic rows, so the demo works offline.</li></ul></section>'))
    rows = []
    names = {p['JiraKey']: p['Name'] for p in ws['tables'].get('pf_projects', []) if p.get('JiraKey')}
    for j in jira:
        tot = int(j['Total'] or 0)
        rows.append(dict(j, project=names.get(j['JiraKey'], '(not linked)'), pct=(int(j['Done']) / tot * 100) if tot else None))
    sections.append(table('Epic status', [col('JiraKey', 'Epic'), col('project', 'Project'), col('Summary', 'Summary'), col('Status', 'Status'),
                                          col('DueDate', 'Due', 'date'), col('Done', 'Done', 'int'), col('InProgress', 'In progress', 'int'),
                                          col('Total', 'Total', 'int'), col('pct', 'Done %', 'num0'), col('Synced', 'Synced')], rows, search=False,
                          empty='No epics yet: sync from Jira or edit Jira epic status.'))
    return page('pf-integrations', sections)
