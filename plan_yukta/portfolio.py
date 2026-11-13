"""
Portfolio and roadmap engine: engineering capacity by skill pool, value-based prioritisation with a
capacity funding line, scenarios, dependency checks, gate governance and roadmap health.

Formulas are in CALCULATIONS.md section 21.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date, timedelta

from .cockpit import month_add, to_date
from .workspace import PF_GATES, settings_dict

CRIT_COL = {'Value': 'ValueUSDm', 'Strategic fit': 'StrategicFit', 'Customer demand': 'CustomerDemand',
            'Time criticality': 'TimeCriticality', 'Technical risk': 'TechRisk'}
DEFAULT_W = {'Value': 35, 'Strategic fit': 20, 'Customer demand': 20, 'Time criticality': 15, 'Technical risk': 10}
STAGE_ORDER = ['Idea', 'Concept', 'Plan', 'Develop', 'Validate', 'Release', 'Sustain', 'Stopped']
MAX_SHIFT = 12
DEFAULT_RAMP = {'Permanent hire': (0.5, 6, 1.0, 0.0), 'Contractor': (0.5, 3, 0.9, 35.0), 'Partner': (0.6, 2, 0.85, 20.0),
                'Transfer': (0.7, 3, 1.0, 0.0)}
REASON_TYPE = {'Hiring plan': 'Permanent hire', 'Contractors': 'Contractor', 'Partner': 'Partner', 'Transfer': 'Transfer',
               'Scenario': 'Contractor'}


def mdiff(a, b):
    """Months from a to b (YYYY-MM)."""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def quarter_of(m, fy_start=1):
    k = (int(m[5:7]) - fy_start) % 12
    y = int(m[:4]) + (1 if fy_start > 1 and int(m[5:7]) >= fy_start else 0)
    return f'FY{str(y)[2:]} Q{k // 3 + 1}' if fy_start > 1 else f'{m[:4]} Q{k // 3 + 1}'


def apply_scenario(tables, changes):
    """Return a copy of the portfolio tables with the scenario changes applied (in Seq order)."""
    t = {k: copy.deepcopy(v) for k, v in tables.items() if k.startswith('pf_')}
    proj = {p['ProjectID']: p for p in t['pf_projects']}
    notes = []
    for c in sorted(changes, key=lambda r: r.get('Seq') or 0):
        kind, pid, val = c['Change'], c.get('ProjectID'), c.get('Value')
        p = proj.get(pid) if pid else None
        if kind in ('Delay months', 'Stop', 'Fund', 'Scale demand %') and not p:
            notes.append(f'Row {c.get("Seq")}: project {pid or "(blank)"} is not in Portfolio projects; skipped.')
            continue
        if kind == 'Delay months':
            k = int(val or 0)
            p['Start'], p['Launch'] = month_add(p['Start'], k), month_add(p['Launch'], k)
            for d in t['pf_demand']:
                if d['ProjectID'] == pid:
                    d['From'], d['To'] = month_add(d['From'], k), month_add(d['To'], k)
            for g in t['pf_gates']:
                if g['ProjectID'] == pid and g['Status'] not in ('Passed',):
                    for f in ('Planned', 'Forecast'):
                        dd = to_date(g.get(f))
                        if dd:
                            g[f] = _shift_date(dd, k).isoformat()
        elif kind == 'Stop':
            p['Funding'], p['Stage'] = 'Stopped', 'Stopped'
        elif kind == 'Fund':
            p['Funding'] = 'Committed'
        elif kind == 'Scale demand %':
            f = 1 + float(val or 0) / 100
            for d in t['pf_demand']:
                if d['ProjectID'] == pid:
                    d['FTE'] = max(0.0, float(d['FTE']) * f)
        elif kind in ('Add FTE', 'Hire FTE'):
            if not c.get('Pool') or not c.get('Month'):
                notes.append(f'Row {c.get("Seq")}: {kind} needs a Pool and a Month; skipped.')
                continue
            t['pf_capacity_changes'].append({'Pool': c['Pool'], 'Month': c['Month'], 'DeltaFTE': float(val or 0),
                                             'Reason': 'Scenario' if kind == 'Add FTE' else 'Hiring plan'})
    return t, notes


def _shift_date(d, k):
    t = d.year * 12 + d.month - 1 + k
    y, m = t // 12, t % 12 + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


class Portfolio:
    def __init__(self, ws, changes=None, scenario_name=None):
        self.ws = ws
        self.s = settings_dict(ws)
        self.as_of = to_date(self.s.get('As-of date')) or date.today()
        self.start = str(self.s.get('Plan start month'))[:7]
        self.H = int(self.s.get('Portfolio horizon months', 24))
        self.fy = int(self.s.get('Portfolio quarter start month', 1))
        self.months = [month_add(self.start, i) for i in range(self.H)]
        self.scenario = scenario_name
        self.notes = []
        if changes:
            self.t, self.notes = apply_scenario(ws['tables'], changes)
        else:
            self.t = {k: v for k, v in ws['tables'].items() if k.startswith('pf_')}
        self.projects = {p['ProjectID']: dict(p) for p in self.t['pf_projects']}
        self.pools = {r['Pool']: r for r in self.t['pf_pools']}
        self._capacity()
        self._gates()
        self._scores()
        self._funding()
        self._deps()
        self._health()

    # ------------------------------------------------------------ capacity
    def _idx(self, m):
        return mdiff(self.start, m)

    # ---- FTE ramp-up and productivity levers
    def ramp_profiles(self):
        prof = dict(DEFAULT_RAMP)
        for r in self.t.get('pf_ramp') or []:
            prof[r['Type']] = (float(r['StartFactor']), int(r['RampMonths']), float(r['SteadyFactor']), float(r['CostPremiumPct'] or 0))
        return prof

    def active_levers(self, mode=None):
        mode = mode or self.lever_mode
        ok = {'None': (), 'Approved': ('Approved', 'In place'),
              'All': ('Idea', 'Planned', 'Approved', 'In place')}.get(mode, ('Approved', 'In place'))
        return [l for l in self.t.get('pf_levers') or [] if l['Status'] in ok]

    def ramp_for(self, pool, typ, start_month, levers):
        """(start factor, ramp months, steady factor) for a cohort starting in start_month, after levers."""
        st, rm, sf, _ = self.ramp_prof.get(typ, self.ramp_prof['Permanent hire'])
        for l in levers:
            if l['Pool'] not in (pool, 'All') or start_month < l['From']:
                continue
            if l['Effect'] == 'Shorter ramp (months)':
                rm = max(0, rm - int(round(float(l['Value']))))
            elif l['Effect'] == 'Higher start factor':
                st = min(max(sf, st), st + float(l['Value']))
        return st, rm, sf

    @staticmethod
    def factor(st, rm, sf, k):
        if k < 0:
            return 0.0
        if rm <= 0:
            return sf
        return st + (sf - st) * min(1.0, k / rm)

    def uplift(self, pool, i, levers):
        m = self.months[i]
        return sum(float(l['Value']) / 100 for l in levers
                   if l['Effect'] == 'Productivity uplift %' and l['Pool'] in (pool, 'All') and m >= l['From'])

    def effective_supply(self, changes, levers, ramp=True):
        """Headcount and effective FTE per pool and month, plus each cohort's effective contribution."""
        H = self.H
        nominal = {p: [float(r['FTE'])] * H for p, r in self.pools.items()}
        eff = {p: [float(r['FTE'])] * H for p, r in self.pools.items()}
        cohorts = []
        for c in changes:
            pool = c['Pool']
            if pool not in nominal:
                continue
            d = float(c['DeltaFTE'])
            k0 = self._idx(c['Month'])
            typ = REASON_TYPE.get(c.get('Reason'), 'Permanent hire')
            st, rm, sf = self.ramp_for(pool, typ, c['Month'], levers) if (d > 0 and ramp) else (1.0, 0, 1.0)
            row = {'pool': pool, 'month': c['Month'], 'reason': c.get('Reason'), 'type': typ if d > 0 else 'Leaver', 'fte': d,
                   'start': st, 'ramp': rm, 'steady': sf, 'eff': [0.0] * H}
            for i in range(H):
                k = i - k0
                if k < 0:
                    continue
                f = self.factor(st, rm, sf, k) if d > 0 else 1.0
                nominal[pool][i] += d
                row['eff'][i] = d * f
                eff[pool][i] += d * f
            cohorts.append(row)
        for p in eff:
            for i in range(H):
                nominal[p][i] = max(0.0, nominal[p][i])
                eff[p][i] = max(0.0, eff[p][i] * (1 + self.uplift(p, i, levers)))
        return nominal, eff, cohorts

    def _capacity(self):
        H = self.H
        self.target = {p: float(r['TargetUtilPct']) / 100 for p, r in self.pools.items()}
        self.ramp_on = str(self.s.get('Apply FTE ramp-up', 'Y')) == 'Y'
        self.lever_mode = str(self.s.get('Productivity levers counted', 'Approved'))
        self.ramp_prof = self.ramp_profiles()
        levers = self.active_levers() if self.ramp_on else []
        self.headcount, eff, self.cohorts = self.effective_supply(self.t['pf_capacity_changes'], levers, self.ramp_on)
        self.supply = eff if self.ramp_on else {p: list(v) for p, v in self.headcount.items()}
        self.pdem = defaultdict(lambda: defaultdict(lambda: [0.0] * H))      # project -> pool -> months
        self.unknown_pools = set()
        for d in self.t['pf_demand']:
            if d['ProjectID'] not in self.projects:
                continue
            if d['Pool'] not in self.supply:
                self.unknown_pools.add(d['Pool'])
                continue
            a, b = self._idx(d['From']), self._idx(d['To'])
            for i in range(max(0, a), min(H - 1, b) + 1):
                self.pdem[d['ProjectID']][d['Pool']][i] += float(d['FTE'])
        # project FTE totals (whole window, not just horizon) for investment views
        self.fte_months = defaultdict(float)
        for d in self.t['pf_demand']:
            if d['ProjectID'] in self.projects:
                self.fte_months[d['ProjectID']] += float(d['FTE']) * (mdiff(d['From'], d['To']) + 1)

    def demand_of(self, pids):
        out = {p: [0.0] * self.H for p in self.supply}
        for pid in pids:
            for pool, v in self.pdem.get(pid, {}).items():
                for i, x in enumerate(v):
                    out[pool][i] += x
        return out

    # ------------------------------------------------------------ gates and dates
    def _gates(self):
        self.gates = defaultdict(list)
        order = {g: i for i, g in enumerate(PF_GATES)}
        for g in self.t['pf_gates']:
            if g['ProjectID'] not in self.projects:
                continue
            pl, fc = to_date(g['Planned']), to_date(g.get('Forecast'))
            eff = fc or pl
            slip = round((eff - pl).days / 30.4) if (eff and pl) else 0
            overdue = g['Status'] in ('Planned', 'Conditional') and eff and eff < self.as_of
            self.gates[g['ProjectID']].append(dict(g, planned=pl, forecast=fc, eff=eff, slip=slip, overdue=bool(overdue)))
        for pid in self.gates:
            self.gates[pid].sort(key=lambda g: order.get(g['Gate'], 9))
        for pid, p in self.projects.items():
            g5 = next((g for g in self.gates.get(pid, []) if g['Gate'] == 'G5 Release'), None)
            p['launch_fc'] = f'{g5["eff"]:%Y-%m}' if (g5 and g5['eff']) else p['Launch']
            p['launch_slip'] = mdiff(p['Launch'], p['launch_fc'])
            nxt = next((g for g in self.gates.get(pid, []) if g['Status'] != 'Passed'), None)
            p['next_gate'] = nxt

    # ------------------------------------------------------------ prioritisation
    def weights(self):
        rows = self.t.get('pf_value_weights') or []
        if not rows:
            return dict(DEFAULT_W)
        w = {k: 0.0 for k in CRIT_COL}
        for r in rows:
            w[r['Criterion']] = float(r['WeightPct'])
        return w

    def _scores(self):
        w = self.weights()
        live = [p for p in self.projects.values() if p['Funding'] != 'Stopped']
        vals = [float(p['ValueUSDm']) for p in live] or [0]
        lo, hi = min(vals), max(vals)
        tw = sum(w.values()) or 1
        for p in self.projects.values():
            v = 1 + 4 * (float(p['ValueUSDm']) - lo) / (hi - lo) if hi > lo else 3
            crit = {'Value': v, 'Strategic fit': float(p['StrategicFit']), 'Customer demand': float(p['CustomerDemand']),
                    'Time criticality': float(p['TimeCriticality']), 'Technical risk': 6 - float(p['TechRisk'])}
            p['crit'] = crit
            p['score'] = sum(crit[k] * w[k] for k in crit) / tw * 20
            fm = self.fte_months.get(p['ProjectID'], 0.0)
            p['fte_years'] = fm / 12
            cost = sum(float(d['FTE']) * (mdiff(d['From'], d['To']) + 1) / 12 * float(self.pools[d['Pool']]['CostPerFTEk'])
                       for d in self.t['pf_demand'] if d['ProjectID'] == p['ProjectID'] and d['Pool'] in self.pools) / 1000
            p['cost_usdm'] = cost
            p['value_per_cost'] = float(p['ValueUSDm']) / cost if cost else None

    def _fits(self, load, pid, shift=0):
        """Worst overload (FTE over target) if project pid is added with a shift; 0 = fits."""
        worst, where = 0.0, None
        for pool, v in self.pdem.get(pid, {}).items():
            cap = self.supply[pool]
            for i in range(self.H):
                j = i - shift
                x = v[j] if 0 <= j < self.H else 0.0
                if shift and j < 0:
                    x = 0.0
                if not x:
                    continue
                over = load[pool][i] + x - cap[i] * self.target[pool]
                if over > worst + 1e-9:
                    worst, where = over, (pool, self.months[i])
        return worst, where

    def _shifted(self, pid, k):
        out = {}
        for pool, v in self.pdem.get(pid, {}).items():
            out[pool] = [0.0] * k + v[:self.H - k] if k else list(v)
        return out

    def _funding(self):
        committed = [p for p in self.projects.values() if p['Funding'] == 'Committed']
        proposed = sorted([p for p in self.projects.values() if p['Funding'] == 'Proposed'], key=lambda p: -p['score'])
        load = self.demand_of([p['ProjectID'] for p in committed])
        self.load_committed = {k: list(v) for k, v in load.items()}
        for p in committed:
            p['funding_result'] = 'Committed'
            p['fund_shift'] = 0
        self.funded_order = []
        for p in sorted(proposed, key=lambda p: -p['score']):
            pid = p['ProjectID']
            worst, where = self._fits(load, pid)
            if worst <= 0:
                p['funding_result'], p['fund_shift'], p['blocker'] = 'Fits now', 0, None
            else:
                p['blocker'] = where
                p['overload'] = worst
                ok = None
                for k in range(1, MAX_SHIFT + 1):
                    w2, _ = self._fits(load, pid, k)
                    if w2 <= 0:
                        ok = k
                        break
                if ok:
                    p['funding_result'], p['fund_shift'] = f'Fits if {ok} months later', ok
                else:
                    p['funding_result'], p['fund_shift'] = 'Above the line', None
            if p['fund_shift'] is not None:
                for pool, v in self._shifted(pid, p['fund_shift']).items():
                    for i, x in enumerate(v):
                        load[pool][i] += x
            self.funded_order.append(pid)
        for p in self.projects.values():
            if p['Funding'] == 'Stopped':
                p['funding_result'], p['fund_shift'] = 'Stopped', None
        self.load_line = load
        self.load_all = self.demand_of([pid for pid, p in self.projects.items() if p['Funding'] != 'Stopped'])

    # ------------------------------------------------------------ dependencies
    def _deps(self):
        self.deps = []
        for d in self.t['pf_dependencies']:
            a, b = self.projects.get(d['From']), self.projects.get(d['To'])
            if not a or not b:
                miss = d['From'] if not a else d['To']
                self.deps.append(dict(d, ok=False, gap=None, need=None, msg=f'Project {miss} is not in Portfolio projects',
                                      from_name=(a or {}).get('Name', d['From']), to_name=(b or {}).get('Name', d['To'])))
                continue
            need = month_add(a['launch_fc'], int(d['LagMonths']))
            gap = mdiff(need, b['launch_fc'])           # >= 0 = enough time
            active = a['Funding'] != 'Stopped' and b['Funding'] != 'Stopped'
            ok = gap >= 0 or not active
            msg = ('' if ok else f'{b["Name"]} launches {b["launch_fc"]} but needs {a["Name"]} by {need} '
                                 f'({a["Name"]} {a["launch_fc"]} + {int(d["LagMonths"])} months): {-gap} month{"s" if -gap != 1 else ""} short')
            if a['Funding'] == 'Stopped' and b['Funding'] != 'Stopped':
                ok, msg = False, f'{b["Name"]} depends on {a["Name"]}, which is stopped in this scenario'
            self.deps.append(dict(d, ok=ok, gap=gap, need=need, msg=msg, from_name=a['Name'], to_name=b['Name']))

    # ------------------------------------------------------------ health
    def overloads(self, load):
        out = []
        for pool, v in load.items():
            for i, x in enumerate(v):
                cap = self.supply[pool][i] * self.target[pool]
                if x > cap + 1e-9:
                    out.append((pool, i, x - cap))
        return out

    def _health(self):
        risks = defaultdict(list)
        for r in self.t['pf_risks']:
            if r['Status'] != 'Closed':
                risks[r['ProjectID']].append(int(r['Probability']) * int(r['Impact']))
        over = {(pool, i) for pool, i, x in self.overloads(self.load_committed)
                if x > 0.05 * self.supply[pool][i] * self.target[pool]}      # ignore overloads under 5% of the pool
        badd = defaultdict(list)
        for d in self.deps:
            if not d['ok']:
                badd[d['To']].append(d)
        for pid, p in self.projects.items():
            slips = [g['slip'] for g in self.gates.get(pid, []) if g['Status'] != 'Passed']
            ms = max(slips + [0])
            sched = 'R' if ms > 2 or any(g['overdue'] for g in self.gates.get(pid, [])) else 'A' if ms > 0 else 'G'
            hit_months = {i for pool, v in self.pdem.get(pid, {}).items() for i, x in enumerate(v) if x and (pool, i) in over}
            cap_hits = len(hit_months)
            capr = 'R' if cap_hits >= 4 else 'A' if cap_hits else 'G'
            rmax = max(risks.get(pid, [0]))
            riskr = 'R' if rmax >= 15 else 'A' if rmax >= 9 else 'G'
            depr = 'R' if badd.get(pid) else 'G'
            if p['Funding'] == 'Stopped':
                sched = capr = riskr = depr = '-'
            p['rag'] = {'Schedule': sched, 'Capacity': capr, 'Risk': riskr, 'Dependencies': depr}
            vals = [x for x in p['rag'].values() if x != '-']
            p['health'] = 'R' if 'R' in vals else 'A' if 'A' in vals else ('G' if vals else '-')
            p['risk_max'] = rmax
            p['cap_hits'] = cap_hits

    # ------------------------------------------------------------ summaries
    def quarters(self):
        qs = []
        for i, m in enumerate(self.months):
            q = quarter_of(m, self.fy)
            if not qs or qs[-1][0] != q:
                qs.append((q, []))
            qs[-1][1].append(i)
        return qs

    def util_table(self, load):
        rows = []
        for pool in self.supply:
            sup, dem = self.supply[pool], load[pool]
            rows.append({'pool': pool, 'supply': sup, 'demand': dem,
                         'util': [d / s * 100 if s else (0 if not d else 999) for d, s in zip(dem, sup)],
                         'target': self.target[pool] * 100})
        return rows

    def kpis(self):
        live = [p for p in self.projects.values() if p['Funding'] != 'Stopped']
        com = [p for p in live if p['Funding'] == 'Committed']
        ov = self.overloads(self.load_committed)
        ov_line = self.overloads(self.load_line)
        nxt4 = range(min(12, self.H))
        cap = sum(self.supply[p][i] * self.target[p] for p in self.supply for i in nxt4)
        use = sum(self.load_committed[p][i] for p in self.supply for i in nxt4)
        return {
            'projects': len(live), 'committed': len(com), 'proposed': sum(1 for p in live if p['Funding'] == 'Proposed'),
            'value_committed': sum(float(p['ValueUSDm']) for p in com),
            'value_fundable': sum(float(p['ValueUSDm']) for p in live if p.get('funding_result') in ('Committed', 'Fits now')
                                  or str(p.get('funding_result', '')).startswith('Fits if')),
            'value_above': sum(float(p['ValueUSDm']) for p in live if p.get('funding_result') == 'Above the line'),
            'util12': use / cap * 100 if cap else 0,
            'overload_fte_m': sum(x for _, _, x in ov), 'overload_cells': len(ov), 'overload_line': sum(x for _, _, x in ov_line),
            'red': sum(1 for p in live if p['health'] == 'R'), 'amber': sum(1 for p in live if p['health'] == 'A'),
            'dep_conflicts': sum(1 for d in self.deps if not d['ok']),
            'overdue_gates': sum(1 for gl in self.gates.values() for g in gl if g['overdue']),
            'slipping': sum(1 for p in live if p['launch_slip'] > 0),
            'cost_usdm': sum(p['cost_usdm'] for p in live),
        }

    def upcoming_gates(self, days=120):
        out = []
        lim = self.as_of + timedelta(days=days)
        for pid, gl in self.gates.items():
            p = self.projects[pid]
            if p['Funding'] == 'Stopped':
                continue
            for g in gl:
                if g['Status'] in ('Planned', 'Conditional', 'Deferred') and g['eff'] and g['eff'] <= lim:
                    out.append(dict(g, name=p['Name'], funding=p['Funding'], score=p['score'], health=p['health'],
                                    funding_result=p.get('funding_result')))
        out.sort(key=lambda g: g['eff'])
        return out


def compare(base: Portfolio, scen: Portfolio):
    """Project-by-project and portfolio-level differences between baseline and scenario."""
    rows = []
    for pid, p in scen.projects.items():
        b = base.projects.get(pid)
        if not b:
            continue
        changed = (p['launch_fc'] != b['launch_fc'] or p.get('funding_result') != b.get('funding_result') or p['Funding'] != b['Funding']
                   or abs(p['fte_years'] - b['fte_years']) > 0.05 or p['health'] != b['health'])
        rows.append({'pid': pid, 'name': p['Name'], 'base_launch': b['launch_fc'], 'scen_launch': p['launch_fc'],
                     'shift': mdiff(b['launch_fc'], p['launch_fc']), 'base_fund': b.get('funding_result'), 'scen_fund': p.get('funding_result'),
                     'base_health': b['health'], 'scen_health': p['health'], 'changed': changed,
                     'fte_delta': p['fte_years'] - b['fte_years']})
    kb, ks = base.kpis(), scen.kpis()
    return {'rows': rows, 'base': kb, 'scen': ks}


def scenarios(ws):
    out = defaultdict(list)
    for r in ws['tables'].get('pf_scenarios', []):
        out[r['Scenario']].append(r)
    return dict(out)


def silicon_links(pf: Portfolio, R):
    """Roadmap projects that become silicon: compare the supply plan's NPI dates with what the roadmap needs."""
    npi = {n['sku']: n for n in R['npi']['products']} if R and R.get('npi') else {}
    out = []
    for pid, p in pf.projects.items():
        sku = p.get('LinkedSKU')
        if not sku:
            continue
        n = npi.get(sku)
        need_by = None
        for d in pf.deps:
            if d['From'] == pid and d['To'] in pf.projects:
                b = pf.projects[d['To']]
                nb = month_add(b['launch_fc'], -int(d['LagMonths']))
                need_by = nb if need_by is None or nb < need_by else need_by
        launch_need = min([x for x in (p['launch_fc'], need_by) if x]) if (need_by or p['launch_fc']) else None
        qd = n['qual_done'] if n else None
        late = (mdiff(launch_need, f'{qd:%Y-%m}') if (qd and launch_need) else None)
        out.append({'pid': pid, 'name': p['Name'], 'sku': sku, 'in_plan': bool(n), 'samples': n['samples'] if n else None,
                    'qual_done': qd, 'need_by': launch_need, 'late_months': late, 'first_demand': n.get('need_date') if n else None,
                    'failed': n.get('failed') if n else None})
    return out
