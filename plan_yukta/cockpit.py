"""
Plan Yukta cockpit engine.

One run turns the workspace tables into every module's results:

  demand plan -> finished goods netting -> Pack -> Test2 -> Test1 (tester allocation with pull-in)
  -> Assembly -> Bump -> Sort (prober allocation) -> fab outs -> fab wafer starts

It plans backwards from customer demand through each manufacturing step at each OSAT,
offsetting by cycle time, dividing by yield, netting the WIP already in the line, and
capacity-checking the test steps against the tester fleet. Upstream steps are planned
from what the testers can actually start, so a tester shortfall flows through to
finished goods, ATP, P&L and the supplier forecasts.

Monthly buckets. Month 0 is the plan start month; negative months (before the plan
start) exist only to catch requirements that are already inside lead time.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .workspace import TABLES, settings_dict

PAD = 8                       # months before plan start kept to catch inside-lead-time needs
EXT = 6                       # months planned past the horizon so lead times do not cut the plan short
WEEKS_PER_MONTH = 52 / 12
DAYS_PER_MONTH = 30.4
EPS = 1e-6
TEST_OPS = ('Sort', 'Test1', 'Test2')
WAFER_OPS = ('Sort', 'Bump')
BACKWARD = ['Pack', 'Test2', 'Test1', 'Assembly', 'Bump', 'Sort']
FLOW_ORDER = ['Sort', 'Bump', 'Assembly', 'Test1', 'Test2', 'Pack']


def r0(x):
    return int(round(x or 0))


def month_add(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + n
    return f'{t // 12:04d}-{t % 12 + 1:02d}'


def month_diff(a: str, b: str) -> int:
    """a - b in months."""
    return (int(a[:4]) * 12 + int(a[5:7])) - (int(b[:4]) * 12 + int(b[5:7]))


def to_date(s) -> date | None:
    if not s:
        return None
    return datetime.strptime(str(s)[:10], '%Y-%m-%d').date()


def month_day(ym: str, day: int) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, min(day, 28))


def holt(series, alpha, beta, horizon):
    """Holt's linear trend exponential smoothing: (one-step fitted, future)."""
    if not series:
        return [], [0.0] * horizon
    if len(series) == 1:
        return [series[0]], [max(0.0, series[0])] * horizon
    level, trend = series[0], series[1] - series[0]
    fitted = [series[0]]
    for y in series[1:]:
        fitted.append(level + trend)
        prev = level
        level = alpha * y + (1 - alpha) * (level + trend)
        trend = beta * (level - prev) + (1 - beta) * trend
    return fitted, [max(0.0, level + (h + 1) * trend) for h in range(horizon)]


DEFAULT_WEIGHT = -0.02


def pullin_intensity(weight):
    """
    Pull-in weight (per product) -> (share of the pull-in cap used, may it use non-consignee testers).
      positive (up to +0.05): avoid pull-in entirely; shortfalls are made late.
      0: neutral, 25% of the cap and only on your own idle (consignee) testers.
      negative: 25% + 75% x |weight| / 0.10 of the cap (-0.02 -> 40%, -0.05 -> 63%, -0.10 -> 100%);
                from -0.05 down, paid non-consignee tester time may also be used to build ahead.
    """
    w = DEFAULT_WEIGHT if weight is None else float(weight)
    if w > 1e-9:
        return 0.0, False
    if abs(w) <= 1e-9:
        return 0.25, False
    return min(1.0, 0.25 + 0.75 * abs(w) / 0.10), w <= -0.05 + 1e-9


def strategy_label(weight, pull='Y'):
    w = DEFAULT_WEIGHT if weight is None else float(weight)
    if pull != 'Y' or w > 1e-9:
        return 'Avoid'
    if abs(w) <= 1e-9:
        return 'Neutral'
    return 'Aggressive' if w <= -0.08 + 1e-9 else ('Moderate' if w <= -0.04 + 1e-9 else 'Conservative')


@dataclass
class Chain:
    """One product at one OSAT vendor."""
    sku: str
    vendor: str
    share: float
    ops: list
    off: dict                         # start offset (months before ship) per op
    demand: list = field(default_factory=list)
    levels: dict = field(default_factory=dict)   # op -> dict of arrays


class Plan:
    def __init__(self, ws: dict, apply_overrides: bool | None = None):
        self.ws = ws
        self.t = ws['tables']
        self.s = settings_dict(ws)
        # overrides = future tester arrivals/removals, hardware arrivals, test-time/OEE changes, yield changes
        self.apply = (self.s.get('Apply overrides', 'Y') == 'Y') if apply_overrides is None else apply_overrides
        self.issues = []          # data checks found while planning
        self.alerts = []          # planning alerts
        self._setup()

    # ------------------------------------------------------------------ setup
    def _setup(self):
        s = self.s
        self.start = str(s['Plan start month'])
        self.H = int(s['Horizon months'])
        self.HX = self.H + EXT
        self.N = PAD + self.HX
        self.months = [month_add(self.start, i) for i in range(self.H)]
        self.months_x = [month_add(self.start, i) for i in range(self.HX)]
        self.as_of = to_date(s['As-of date']) or date.today()
        self.days = float(s['Working days per month'])
        self.uplift = 1 + float(s['Demand uplift %']) / 100
        self.allow_nc = s['Allow non-consignee testers'] == 'Y'
        self.hw_limit = s['Limit testers to hardware-ready'] == 'Y'
        self.count_hold = s['Count held lots as supply'] == 'Y'
        self.lot = max(1, int(s['Wafer lot size']))
        self.pull_h = int(s['Pull-in horizon months'])
        self.products = {r['SKU']: r for r in self.t['products']}
        self.flow = defaultdict(dict)
        for r in sorted(self.t['process_flow'], key=lambda r: (r['SKU'], r['Step'])):
            if r['SKU'] in self.products:
                self.flow[r['SKU']][r['Operation']] = r
        self.vendors = {r['Vendor']: r for r in self.t['vendors'] if r['Enabled'] == 'Y'}
        self.cap = {(r['Vendor'], r['SKU'], r['Step']): r for r in self.t['tester_capacity']}
        self.fleet = {(r['Vendor'], r['Step']): r for r in self.t['tester_fleet']}
        self.overrides = defaultdict(list)
        self.cap_over = defaultdict(list)
        self.fleet_changes = list(self.t.get('fleet_changes', [])) if self.apply else []
        self.hw_arrivals = list(self.t.get('hardware_arrivals', [])) if self.apply else []
        if self.apply:
            for r in self.t['yield_overrides']:
                self.overrides[(r['SKU'], r['Vendor'], r['Operation'])].append(r)
            for r in self.t.get('capacity_overrides', []):
                self.cap_over[(r['Vendor'], r['SKU'], r['Step'])].append(r)
        for v in list(self.overrides.values()) + list(self.cap_over.values()):
            v.sort(key=lambda r: r['EffectiveMonth'])
        self._upm_cache = {}
        self.bins = defaultdict(list)
        for r in self.t['bin_splits']:
            self.bins[r['SKU']].append((r['Bin'], float(r['Fraction'])))

    def lab(self, pos: int) -> str:
        return month_add(self.start, pos - PAD)

    def ops_of(self, sku):
        return [op for op in FLOW_ORDER if op in self.flow[sku]]

    def yld(self, sku, vendor, op, pos):
        if op not in self.flow[sku]:
            return 1.0
        y = float(self.flow[sku][op]['Yield'])
        m = self.lab(pos)
        for o in self.overrides.get((sku, vendor, op), []):
            if o['EffectiveMonth'] <= m:
                y = float(o['Yield'])
        return y

    def rework(self, sku, vendor, op, pos):
        if op not in self.flow[sku]:
            return 0.0
        rw = float(self.flow[sku][op]['ReworkRate'] or 0)
        m = self.lab(pos)
        for o in self.overrides.get((sku, vendor, op), []):
            if o['EffectiveMonth'] <= m and o.get('ReworkRate') is not None:
                rw = float(o['ReworkRate'])
        return rw

    def die_per_wafer(self, sku, vendor, pos):
        """Good die from one sorted (and bumped) wafer."""
        g = float(self.products[sku]['GDPW'])
        return g * self.yld(sku, vendor, 'Sort', pos) * self.yld(sku, vendor, 'Bump', pos)

    def good_units_per_wafer(self, sku, vendor='', pos=PAD):
        u = float(self.products[sku]['GDPW'])
        for op in self.ops_of(sku):
            u *= self.yld(sku, vendor, op, pos)
        return u

    def test_params(self, vendor, sku, step, i=0):
        """Test time, sites, index and OEE in plan month i, after any test-time / OEE override."""
        c = self.cap.get((vendor, sku, step))
        if not c:
            return None
        c = dict(c)
        c['_override'] = None
        m = self.months_x[min(max(i, 0), self.HX - 1)]
        for o in self.cap_over.get((vendor, sku, step), []):
            if o['EffectiveMonth'] <= m:
                for k in ('TestTimeSec', 'Sites', 'IndexTimeSec', 'OEE'):
                    if o.get(k) is not None:
                        c[k] = o[k]
                c['_override'] = o
        return c

    def upm(self, vendor, sku, step, i=0):
        """Units (wafers for Sort) one tester can test in plan month i."""
        key = (vendor, sku, step, i)
        if key in self._upm_cache:
            return self._upm_cache[key]
        c = self.test_params(vendor, sku, step, i)
        f = self.fleet.get((vendor, step))
        if not c:
            return 0.0, None
        hours = float(f['HoursPerDay']) if f else 24.0
        avail = hours * 3600 * float(c['OEE']) * self.days
        if step == 'Sort':
            gdpw = float(self.products[sku]['GDPW'])
            td = math.ceil(gdpw / float(c['Sites'])) / float(c.get('StepEff') or 1.0)
            sec = td * (float(c['TestTimeSec']) + float(c['IndexTimeSec'])) + float(c.get('WaferLoadSec') or 0)
        else:
            sec = (float(c['TestTimeSec']) + float(c['IndexTimeSec'])) / float(c['Sites'])
        out = ((avail / sec if sec > 0 else 0.0), sec)
        self._upm_cache[key] = out
        return out

    # ------------------------------------------------------------------ demand
    def demand_plan(self):
        a, b = float(self.s['Holt alpha']), float(self.s['Holt beta'])
        hist = defaultdict(dict)
        for r in self.t['shipment_history']:
            if r['Month'] < self.start:
                hist[r['SKU']][r['Month']] = float(r['Units'])
        HX = self.HX
        fc = defaultdict(lambda: [0.0] * HX)
        last_fc = {}
        for r in self.t['forecast']:
            i = month_diff(r['Month'], self.start)
            if 0 <= i < HX:
                fc[r['SKU']][i] += float(r['Units'])
        for sku, arr in list(fc.items()):
            known = max((month_diff(r['Month'], self.start) for r in self.t['forecast'] if r['SKU'] == sku), default=-1)
            if self.H - 1 <= known < HX - 1:
                for i in range(known + 1, HX):      # beyond the last forecast month: hold the last value
                    arr[i] = arr[known]
        od = defaultdict(lambda: [0.0] * HX)
        for r in self.t['orders']:
            if r['Status'] == 'Cancelled':
                continue
            i = month_diff(r['Month'], self.start)
            if 0 <= i < HX:
                od[r['SKU']][i] += float(r['Qty'])
        self.history, self.fc, self.od = hist, fc, od
        self.stat, self.accuracy, self.dem = {}, {}, {}
        for sku, p in self.products.items():
            h = hist.get(sku, {})
            ms = sorted(h)
            # continuous monthly series up to the month before plan start
            series = []
            if ms:
                m = ms[0]
                while m < self.start:
                    series.append(h.get(m, 0.0))
                    m = month_add(m, 1)
            fitted, future = holt(series, a, b, HX)
            self.stat[sku] = future if len(series) >= 3 else list(fc[sku])
            if len(series) >= 4:
                act = series[-6:]
                fit = fitted[-6:]
                tot = sum(act) or 1
                self.accuracy[sku] = {'wmape': sum(abs(x - y) for x, y in zip(act, fit)) / tot * 100,
                                      'bias': sum(y - x for x, y in zip(act, fit)) / tot * 100, 'points': len(series)}
            strat = p['BuildStrategy']
            out = []
            for i in range(HX):
                f, o, st = fc[sku][i], od[sku][i], self.stat[sku][i]
                if strat == 'ORDERS':
                    v = o
                elif strat == 'STAT':
                    v = max(st, o)
                elif strat == 'BLEND':
                    v = max((f + st) / 2 if f else st, o)
                else:
                    v = max(f, o)
                out.append(v * self.uplift)
            self.dem[sku] = out

    # ------------------------------------------------------------------ supply now
    def wip(self):
        pmap = {(r['Vendor'], r['VendorProduct'].strip().upper()): r['SKU'] for r in self.t['product_codes']}
        omap = {(r['Vendor'], r['VendorOperation'].strip().upper()): r['Operation'] for r in self.t['operation_codes']}
        self.lots = []
        sup = defaultdict(float)        # (sku, vendor, op, 'out'|'load') -> qty
        fg_bins = defaultdict(float)    # (sku, vendor, bin) -> units
        for r in self.t['osat_wip']:
            sku = pmap.get((r['Vendor'], str(r['VendorProduct']).strip().upper()))
            op = omap.get((r['Vendor'], str(r['VendorOperation']).strip().upper()))
            lot = dict(r, SKU=sku, Operation=op, issue='')
            if not sku:
                lot['issue'] = 'product code not mapped'
            elif not op:
                lot['issue'] = 'operation not mapped'
            elif sku not in self.products:
                lot['issue'] = 'SKU not in products'
            self.lots.append(lot)
            if lot['issue'] or (r['State'] == 'HOLD' and not self.count_hold):
                continue
            wafers = float(r.get('Wafers') or 0)
            units = float(r.get('Units') or 0)
            v = r['Vendor']
            if op in ('Sort', 'Bump', 'DieBank'):
                q = wafers
            else:
                q = units
            if op == 'FG':
                fg_bins[(sku, v, r.get('Bin') or 'BIN_1')] += units
                sup[(sku, v, 'FG', 'out')] += units
                continue
            if op == 'DieBank':
                sup[(sku, v, 'DieBank', 'out')] += wafers
                continue
            if op not in self.flow[sku]:
                lot['issue'] = f'{op} is not in the process flow of {sku}'
                continue
            done = r['State'] == 'DONE'
            y = 1.0 if (done or op in WAFER_OPS) else self.yld(sku, v, op, PAD)
            sup[(sku, v, op, 'out')] += q * y
            if op in TEST_OPS and not done:
                rw = self.rework(sku, v, op, PAD)
                remaining = 0.5 if r['State'] == 'RUN' else 1.0
                sup[(sku, v, op, 'load')] += q * (1 + rw) * remaining
        self.supply, self.fg_bins = sup, fg_bins
        # fab WIP by expected out month (position)
        self.fab_wip = defaultdict(lambda: [0.0] * self.N)
        transit = int(self.s['Fab to OSAT transit days'])
        for r in self.t['fab_wip']:
            if r['SKU'] not in self.products:
                continue
            arrive = to_date(r['ExpectedOutDate']) + timedelta(days=transit)
            pos = month_diff(f'{arrive.year:04d}-{arrive.month:02d}', self.start) + PAD
            pos = min(max(pos, PAD), self.N - 1)   # already-out lots count as available now
            self.fab_wip[r['SKU']][pos] += float(r['Wafers'])

    # ------------------------------------------------------------------ capacity
    def fleet_by_month(self):
        """(vendor, step) -> list over plan months of (consignee, non-consignee)."""
        out = {}
        HX = self.HX
        self.events = defaultdict(lambda: [[] for _ in range(HX)])    # (vendor, step) -> per month: change notes
        for (v, st), f in self.fleet.items():
            c = [int(f['Consignee'])] * HX
            n = [int(f['NonConsignee'])] * HX
            for ch in sorted(self.fleet_changes, key=lambda r: r['Month']):
                if ch['Vendor'] == v and ch['Step'] == st:
                    i0 = max(0, month_diff(ch['Month'], self.start))
                    if i0 < HX:
                        dc, dn = int(ch['ConsigneeChange'] or 0), int(ch['NonConsigneeChange'] or 0)
                        self.events[(v, st)][i0].append(' '.join(x for x in (f'{dc:+d} C' if dc else '', f'{dn:+d} NC' if dn else '') if x))
                    for i in range(i0, HX):
                        c[i] = max(0, c[i] + int(ch['ConsigneeChange'] or 0))
                        n[i] = max(0, n[i] + int(ch['NonConsigneeChange'] or 0))
            out[(v, st)] = [c, n]
        for r in self.hw_arrivals:
            i0 = month_diff(r['Month'], self.start)
            if 0 <= i0 < HX:
                self.events[(r['Vendor'], r['Step'])][i0].append(f'{int(r["Qty"]):+d} {r["HardwareType"].lower()}')
        for (v, sku, st), items in self.cap_over.items():
            for o in items:
                i0 = month_diff(o['EffectiveMonth'], self.start)
                if 0 <= i0 < HX:
                    what = ', '.join(f'{lab} {o[k]:g}' for k, lab in (('TestTimeSec', 'test s'), ('Sites', 'sites'),
                                                                      ('IndexTimeSec', 'index s'), ('OEE', 'OEE')) if o.get(k) is not None)
                    self.events[(v, st)][i0].append(f'{sku}: {what}')
        self.fleet_m = out
        # hardware-ready consignee testers
        hw = defaultdict(list)
        for r in self.t['hardware']:
            hw[(r['Vendor'], r['Step'])].append(r)
        self.hw_ready = {}
        for key, items in hw.items():
            ready = []
            for i in range(HX):
                m = self.months_x[i]
                kits = []
                for r in items:
                    qty = int(r['InService'] or 0)
                    qty += sum(int(a['Qty']) for a in self.hw_arrivals if a['Vendor'] == r['Vendor'] and a['Step'] == r['Step']
                               and a['HardwareType'].strip().lower() == r['HardwareType'].strip().lower() and a['Month'] <= m)
                    kits.append(max(0, qty) // max(1, int(r['PerTester'])))
                ready.append(min(kits) if kits else 0)
            self.hw_ready[key] = ready
        self.cap_m = {}
        for key, (c, n) in out.items():
            cc = list(c)
            if self.hw_limit and key in self.hw_ready:
                cc = [min(a, b) for a, b in zip(cc, self.hw_ready[key])]
            nn = list(n) if self.allow_nc else [0] * HX
            self.cap_m[key] = (cc, nn)

    def allocate(self, vendor, step, loads, earliest=None):
        """
        Rough-cut capacity allocation of tester time (in tester-months) for one vendor and test step.

        loads: {sku: [insertions per month]}; earliest: {sku: first month pull-in may use}.
        1. Each month, highest priority first, give each product the tester time it needs:
           consignee testers first, then non-consignee (if allowed).
        2. Pull-in: idle tester time in earlier months builds ahead for a later shortfall, latest
           month first, within the pull-in horizon, never before material can exist (earliest),
           and capped at the product's service level / max pull-in % of the shortfall.
        3. Catch-up: what is still short is made in the next months with idle time (late).
        """
        H = self.HX
        cc, nn = self.cap_m.get((vendor, step), ([0] * H, [0] * H))
        skus = sorted(loads, key=lambda k: (-int(self.products[k]['Priority']), k))
        upm = {k: [self.upm(vendor, k, step, i)[0] for i in range(H)] for k in skus}   # per month: overrides change it
        earliest = earliest or {}
        res = {k: {'load': list(loads[k]), 'tc': [0.0] * H, 'tn': [0.0] * H, 'prod': [0.0] * H, 'prod_c': [0.0] * H,
                   'gap': [0.0] * H, 'pullin': [0.0] * H, 'covered': [0.0] * H, 'catchup': [0.0] * H,
                   'late_left': [0.0] * H} for k in skus}
        idle_c, idle_n = [float(x) for x in cc], [float(x) for x in nn]

        def give(k, m, units, allow_n=True):
            """Use idle tester time in month m for product k; returns units made."""
            r, u = res[k], upm[k][m]
            if u <= 0:
                return 0.0
            want = units / u
            a_c = min(want, idle_c[m])
            idle_c[m] -= a_c
            a_n = min(want - a_c, idle_n[m]) if allow_n else 0.0
            idle_n[m] -= a_n
            r['tc'][m] += a_c
            r['tn'][m] += a_n
            r['prod'][m] += (a_c + a_n) * u
            r['prod_c'][m] += a_c * u
            return (a_c + a_n) * u

        for i in range(H):
            for k in skus:
                L = loads[k][i]
                if L <= EPS:
                    continue
                if upm[k][i] <= 0:
                    res[k]['gap'][i] = L
                    continue
                made = give(k, i, L)
                res[k]['gap'][i] = max(0.0, L - made)
        for k in skus:                                    # pull-in
            p = self.products[k]
            if p['PullIn'] != 'Y' or max(upm[k]) <= 0:
                continue
            intensity, allow_n = pullin_intensity(p.get('PullInWeight'))
            cap_share = min(float(p['ServiceLevelPct']), float(p['MaxPullInPct'])) / 100.0 * intensity
            if cap_share <= 0:
                continue
            lo = earliest.get(k, 0)
            for g in range(H):
                gap = res[k]['gap'][g]
                if gap <= EPS:
                    continue
                budget = gap * cap_share
                for m in range(g - 1, max(lo, g - self.pull_h) - 1, -1):
                    if budget <= EPS or m < 0:
                        break
                    made = give(k, m, budget, allow_n)
                    if made > EPS:
                        budget -= made
                        res[k]['pullin'][m] += made
                        res[k]['covered'][g] += made
                        res[k]['gap'][g] -= made
        for k in skus:                                    # catch-up of what is still short
            if max(upm[k]) <= 0:
                continue
            owed = 0.0
            for i in range(H):
                if owed > EPS:
                    made = give(k, i, owed)
                    res[k]['catchup'][i] += made
                    owed -= made
                owed += res[k]['gap'][i]
                res[k]['late_left'][i] = owed
        summary = []
        for i in range(H):
            used = sum(res[k]['prod'][i] / upm[k][i] for k in skus if upm[k][i] > 0)
            need_frac = sum(loads[k][i] / upm[k][i] for k in skus if upm[k][i] > 0)
            total = cc[i] + nn[i]
            summary.append({'month': self.months_x[i], 'consignee': cc[i], 'non_consignee': nn[i], 'total': total,
                            'fleet_consignee': self.fleet_m.get((vendor, step), [[0] * H])[0][i],
                            'used': used, 'needed': need_frac, 'needed_int': math.ceil(need_frac - 1e-6),
                            'alloc_c': sum(res[k]['tc'][i] for k in skus), 'alloc_n': sum(res[k]['tn'][i] for k in skus),
                            'util': (used / total * 100) if total else (100.0 if need_frac > EPS else 0.0),
                            'load_util': (need_frac / total * 100) if total else (100.0 if need_frac > EPS else 0.0),
                            'gap': sum(res[k]['gap'][i] for k in skus), 'pullin': sum(res[k]['pullin'][i] for k in skus),
                            'catchup': sum(res[k]['catchup'][i] for k in skus),
                            'events': list(self.events[(vendor, step)][i]) if hasattr(self, 'events') else [],
                            'late_left': sum(res[k]['late_left'][i] for k in skus)})
        return res, summary, upm

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def net(arr, qty):
        """Consume a quantity available now against a requirement array, earliest first."""
        out = list(arr)
        left = qty
        for i, v in enumerate(out):
            if left <= EPS:
                break
            use = min(v, left)
            out[i] = v - use
            left -= use
        return out, left

    def shift(self, arr, delta):
        """Move a requirement `delta` months earlier."""
        out = [0.0] * self.N
        for i, v in enumerate(arr):
            if v:
                j = i - delta
                if j < 0:
                    j = 0
                out[j] += v
        return out

    def collapse(self, arr):
        """Requirements before month 0 cannot be executed; move them to month 0."""
        late = sum(arr[:PAD])
        first = next((i for i in range(PAD) if arr[i] > EPS), None)
        out = [0.0] * PAD + list(arr[PAD:])
        out[PAD] += late
        return out, late, first

    @staticmethod
    def cum_gap(need, avail):
        g, cn, ca = [], 0.0, 0.0
        for a, b in zip(need, avail):
            cn += a
            ca += b
            g.append(max(0.0, cn - ca))
        return g

    # ------------------------------------------------------------------ main backward pass
    def run(self):
        self.demand_plan()
        self.wip()
        self.fleet_by_month()
        transit = int(self.s['Fab to OSAT transit days'])
        fab_days = float(self.s['Fab cycle time weeks']) * 7
        self.chains = []
        for sku, p in self.products.items():
            ops = self.ops_of(sku)
            if not ops:
                self.issues.append(('error', 'process_flow', f'{sku} has no process flow, so it is not planned.'))
                continue
            steps = [op for op in ops if op in TEST_OPS]
            qual = [v for v in self.vendors if all((v, sku, st) in self.cap for st in steps)]
            if not qual:
                if any(self.dem[sku]):
                    self.issues.append(('error', 'tester_capacity',
                                        f'{sku} has demand but no enabled vendor has test times for all of its test steps ({", ".join(steps)}).'))
                continue
            tot = sum(float(self.vendors[v]['SharePct']) for v in qual) or len(qual)
            cum, off = 0.0, {}
            for op in reversed(ops):
                cum += float(self.flow[sku][op]['CycleTimeDays'])
                off[op] = int(round(cum / DAYS_PER_MONTH))
            off['_fabout'] = int(round((cum + transit) / DAYS_PER_MONTH))
            off['_fabstart'] = int(round((cum + transit + fab_days) / DAYS_PER_MONTH))
            for v in qual:
                share = (float(self.vendors[v]['SharePct']) / tot) if tot else 1 / len(qual)
                ch = Chain(sku, v, share, ops, off)
                ch.demand = [d * share for d in self.dem[sku]]
                self.chains.append(ch)
        H, N = self.HX, self.N
        # finished goods requirement with safety stock build
        for ch in self.chains:
            p = self.products[ch.sku]
            ssw = float(p['SafetyStockWeeks'] or 0)
            target = [ssw * (ch.demand[min(i + 1, H - 1)]) / WEEKS_PER_MONTH for i in range(H)]
            req, prev, credit = [0.0] * N, 0.0, 0.0
            for i in range(H):
                x = ch.demand[i] + target[i] - prev + credit
                credit = min(0.0, x)
                req[PAD + i] = max(0.0, x)
                prev = target[i]
            ch.ss_target = target
            fg_now = self.supply.get((ch.sku, ch.vendor, 'FG', 'out'), 0.0)
            ch.fg_now = fg_now
            need, _ = self.net(req, fg_now)
            ch.need = need                     # Pack output needed, by ship month
            ch.pack_out_req = list(need)
            ch.consumer = 0
            ch.unit = 'units'
        # level by level
        self.alloc = {}
        for op in BACKWARD:
            starts = {}
            for ch in self.chains:
                if op not in ch.ops:
                    continue
                need = ch.need
                if op in WAFER_OPS and ch.unit == 'units':
                    need = self._to_wafers(ch, need)
                supply_out = self.supply.get((ch.sku, ch.vendor, op, 'out'), 0.0)
                if op == ([o for o in ch.ops if o in WAFER_OPS] or [None])[-1]:
                    supply_out += self.supply.get((ch.sku, ch.vendor, 'DieBank', 'out'), 0.0)
                net_need, left = self.net(need, supply_out)
                delta = ch.off[op] - ch.consumer
                ch.consumer = ch.off[op]
                y = [self.yld(ch.sku, ch.vendor, op, i) for i in range(N)]
                st = [0.0] * N
                for i, v in enumerate(net_need):
                    if v:
                        j = max(0, i - delta)
                        st[j] += v / (1.0 if op in WAFER_OPS else y[j])
                lvl = {'need_out': need, 'net_out': net_need, 'supply_out': supply_out, 'supply_left': left,
                       'delta': delta, 'starts_req_raw': st, 'yield': y}
                st_c, late, first = self.collapse(st)
                lvl.update(starts_req=st_c, late=late, late_first=first)
                ch.levels[op] = lvl
                starts[(ch.sku, ch.vendor)] = st_c
            if op in TEST_OPS:
                by_vendor = defaultdict(dict)
                for ch in self.chains:
                    if op not in ch.ops:
                        continue
                    lvl = ch.levels[op]
                    rw = [self.rework(ch.sku, ch.vendor, op, i) for i in range(N)]
                    ins = [lvl['starts_req'][PAD + i] * (1 + rw[PAD + i]) for i in range(H)]
                    ins[0] += self.supply.get((ch.sku, ch.vendor, op, 'load'), 0.0)
                    lvl['rw'] = rw
                    lvl['wip_load'] = self.supply.get((ch.sku, ch.vendor, op, 'load'), 0.0)
                    lvl['ins_req'] = ins
                    by_vendor[ch.vendor][ch.sku] = ins
                for v, loads in by_vendor.items():
                    earliest = {}
                    for ch in self.chains:
                        if ch.vendor == v and op in ch.ops:
                            # pull-in only where upstream material can still be built: fab start offset minus this step's
                            earliest[ch.sku] = max(0, ch.off['_fabstart'] - ch.off[op])
                    res, summary, upm = self.allocate(v, op, loads, earliest)
                    self.alloc[(v, op)] = {'res': res, 'summary': summary, 'upm': upm}
                for ch in self.chains:
                    if op not in ch.ops:
                        continue
                    lvl = ch.levels[op]
                    r = self.alloc[(ch.vendor, op)]['res'][ch.sku]
                    wl = lvl['wip_load']
                    prod_starts = [0.0] * N
                    for i in range(H):
                        ins_new = r['prod'][i] - (wl if i == 0 else 0.0)
                        if i == 0 and ins_new < 0:
                            ins_new = 0.0
                        prod_starts[PAD + i] = max(0.0, ins_new) / (1 + lvl['rw'][PAD + i])
                    lvl['alloc'] = r
                    lvl['starts'] = prod_starts
                    ch.need = prod_starts
            else:
                for ch in self.chains:
                    if op in ch.ops:
                        ch.levels[op]['starts'] = ch.levels[op]['starts_req']
                        ch.need = ch.levels[op]['starts']
            for ch in self.chains:
                if op in ch.ops:
                    ch.unit = 'wafers' if op in WAFER_OPS else 'units'
        self._fab()
        self._finished_goods()
        return self

    def _to_wafers(self, ch, need_units):
        return [v / max(EPS, self.die_per_wafer(ch.sku, ch.vendor, i)) for i, v in enumerate(need_units)]

    # ------------------------------------------------------------------ fab
    def _fab(self):
        H, N = self.HX, self.N
        cap = int(self.s['Fab capacity wafers per month'])
        self.fab = {}
        by_sku = defaultdict(list)
        for ch in self.chains:
            by_sku[ch.sku].append(ch)
        for sku, chs in by_sku.items():
            off = chs[0].off
            first = chs[0].ops[0]
            d_out = off['_fabout'] - off[first]
            d_start = off['_fabstart'] - off['_fabout']
            # sort starts (wafers) per vendor -> wafers that must arrive from the fab
            need = [0.0] * N
            per_vendor = {}
            for ch in chs:
                arr = self.shift(ch.levels[first]['starts'], d_out)
                per_vendor[ch.vendor] = arr
                need = [a + b for a, b in zip(need, arr)]
            wipq = self.fab_wip[sku]
            # Fab WIP first serves needs already late (inside lead time), then the current month.
            # A need new starts can still meet on time is ordered; one they cannot is backlogged
            # until WIP arrives or until late new starts (begun in month 0) arrive, whichever is first.
            start_need = [0.0] * N
            backlog, late_by, late_wafers = [], [], 0.0
            earliest_out = PAD + d_start
            for i in range(N):
                arrive = wipq[i]
                if i == earliest_out and backlog:
                    for m, q in backlog:
                        start_need[PAD] += q
                    backlog = []
                while arrive > EPS and backlog:
                    take = min(arrive, backlog[0][1])
                    arrive -= take
                    backlog[0][1] -= take
                    if backlog[0][1] <= EPS:
                        backlog.pop(0)
                q = need[i]
                use = min(arrive, q)
                q -= use
                if q > EPS:
                    if i - d_start >= PAD:
                        start_need[i - d_start] += q
                    else:
                        backlog.append([i, q])
                        late_wafers += q
                        late_by.append((self.lab(i), q))
            for m, q in backlog:
                start_need[PAD] += q
            starts = [0.0] * N
            # wafer lot rounding with carry-forward of the rounding excess
            excess = 0.0
            for i in range(PAD, N):
                v = max(0.0, start_need[i] - excess)
                excess = max(0.0, excess - start_need[i])
                if v > EPS:
                    lots = math.ceil(v / self.lot - 1e-9)
                    starts[i] = lots * self.lot
                    excess += starts[i] - v
            outs = [0.0] * N
            for i, v in enumerate(starts):
                if v:
                    j = i + d_start
                    if j < N:
                        outs[j] += v
            # available wafers at OSAT per month = fab WIP + new outs; gap vs need (cumulative)
            avail = [a + b for a, b in zip(wipq, outs)]
            gap = self.cum_gap(need, avail)
            over = [i for i in range(PAD, N) if starts[i] > cap > 0]
            self.fab[sku] = {'need': need, 'per_vendor': per_vendor, 'wip': wipq, 'starts': starts, 'outs': outs,
                             'cum_gap': gap, 'late_wafers': late_wafers, 'late_by': late_by,
                             'd_out': d_out, 'd_start': d_start, 'off_out': off['_fabout'], 'over_cap': over}
            if late_wafers > 0.5:
                first_m = late_by[0][0] if late_by else self.months[0]
                gu = self.good_units_per_wafer(sku)
                self.alerts.append({'severity': 'high', 'module': 'FAB PO', 'sku': sku, 'month': first_m,
                                    'text': f'{late_wafers:,.0f} wafers of {sku} are needed out of the fab sooner than new starts can '
                                            f'deliver (inside fab lead time); fab WIP covers them late. Ask the fab to expedite '
                                            f'(about {late_wafers * gu:,.0f} finished units); Complete Flow shows the customer impact.'})
        # fab capacity check across products
        tot = [sum(self.fab[s]['starts'][i] for s in self.fab) for i in range(N)]
        for i in range(PAD, PAD + self.H):
            if cap > 0 and tot[i] > cap:
                self.alerts.append({'severity': 'medium', 'module': 'FAB PO', 'sku': 'All', 'month': self.lab(i),
                                    'text': f'Wafer starts {tot[i]:,.0f} exceed the allocated fab capacity of {cap:,} wafers.'})
        self.fab_total = tot

    # ------------------------------------------------------------------ finished goods / shortfall
    def _finished_goods(self):
        H, N = self.HX, self.N
        self.fg = {}
        for ch in self.chains:
            deficit = [0.0] * N       # cumulative production deficit expressed in finished units, by ship month
            for op in ch.ops:
                lvl = ch.levels[op]
                need_starts = lvl['starts_req_raw']
                prod = lvl['starts']
                g = self.cum_gap(need_starts, prod)
                down = 1.0
                seen = False
                for o in ch.ops:
                    if o == op:
                        seen = True
                    if seen and o not in WAFER_OPS:
                        down *= self.yld(ch.sku, ch.vendor, o, PAD + 1)
                if op in WAFER_OPS:
                    down *= self.die_per_wafer(ch.sku, ch.vendor, PAD + 1)
                lvl['cum_gap_starts'] = g
                lvl['down'] = down
                for i in range(N):
                    j = i + ch.off[op]
                    if g[i] > EPS and 0 <= j < N:
                        deficit[j] += g[i] * down
                # positions shifted past the end are ignored
            fab = self.fab.get(ch.sku)
            if fab:
                share = 0.0
                tot_need = sum(fab['need']) or 1.0
                share = sum(fab['per_vendor'][ch.vendor]) / tot_need
                first = ch.ops[0]
                gu = self.die_per_wafer(ch.sku, ch.vendor, PAD + 1)
                for o in ch.ops:
                    if o not in WAFER_OPS:
                        gu *= self.yld(ch.sku, ch.vendor, o, PAD + 1)
                for i in range(N):
                    j = i + fab['off_out']
                    if fab['cum_gap'][i] > EPS and 0 <= j < N:
                        deficit[j] += fab['cum_gap'][i] * share * gu
            # constrained pack output by ship month
            po = ch.pack_out_req
            po_c = [0.0] * N
            prev = 0.0
            for i in range(N):
                d = max(0.0, deficit[i])
                po_c[i] = max(0.0, po[i] - (d - prev))
                prev = d
            avail, backlog = ch.fg_now, 0.0
            ship, short, fg_end = [0.0] * H, [0.0] * H, [0.0] * H
            for i in range(H):
                avail += po_c[PAD + i]
                want = ch.demand[i] + backlog
                s = min(want, avail)
                backlog = want - s
                avail -= s
                ship[i], short[i], fg_end[i] = s, backlog, avail
            self.fg[(ch.sku, ch.vendor)] = {'pack_out_plan': po[PAD:], 'pack_out': po_c[PAD:], 'deficit': deficit[PAD:],
                                            'ship': ship, 'short': short, 'fg_end': fg_end, 'fg_now': ch.fg_now,
                                            'ss': ch.ss_target, 'demand': ch.demand}
            vis = short[:self.H]
            if max(vis) > 0.5:
                i = next(k for k, v in enumerate(vis) if v > 0.5)
                self.alerts.append({'severity': 'high', 'module': 'Complete Flow', 'sku': ch.sku, 'month': self.months[i],
                                    'text': f'{ch.sku} at OSAT-{ch.vendor}: customers will be short up to {max(vis):,.0f} units '
                                            f'(first in {self.months[i]}). See Testing Starts and FAB PO for the cause.'})


# ======================================================================================
# Module views built on a finished Plan
# ======================================================================================
def compute(ws: dict, apply_overrides: bool | None = None) -> dict:
    p = Plan(ws, apply_overrides).run()
    R = {'plan': p, 'months': p.months, 'settings': p.s}
    R['demand'] = demand_view(p)
    R['testing'] = testing_view(p)
    R['flow'] = flow_view(p)
    R['frontend'] = frontend_view(p)
    R['assembly'] = assembly_view(p)
    R['cost'] = cost_view(p, R)
    R['fab_po'] = fab_po_view(p)
    R['osat_po'] = osat_po_view(p, R)
    R['substrate'] = substrate_view(p, R)
    R['atp'] = atp_view(p)
    R['pnl'] = pnl_view(p, R)
    R['osat_wip'] = osat_wip_view(p)
    R['hardware'] = hardware_view(p)
    R['ate'] = ate_view(p, R)
    R['npi'] = npi_view(p)
    R['pva'] = pva_view(p)
    R['cross'] = cross_view(p)
    R['b2b'] = b2b_view(p, R)
    R['checks'] = checks_view(p)
    R['home'] = home_view(p, R)
    return R


def _s(v, nd=0):
    return round(v, nd) if v is not None else None


def demand_view(p: Plan):
    rows = []
    for sku in p.products:
        h = p.history.get(sku, {})
        rows.append({'sku': sku, 'strategy': p.products[sku]['BuildStrategy'], 'status': p.products[sku]['Status'],
                     'forecast': p.fc[sku], 'orders': p.od[sku], 'stat': p.stat[sku], 'plan': p.dem[sku],
                     'hist_months': sorted(h)[-12:], 'hist': [h[m] for m in sorted(h)[-12:]],
                     'acc': p.accuracy.get(sku), 'total': sum(p.dem[sku]),
                     'order_cover': [(o / f * 100) if f else None for o, f in zip(p.od[sku], p.dem[sku])]})
    return {'rows': rows}


def testing_view(p: Plan):
    """Module 1: final-test (and sort) starts, tester allocation, gaps and pull-in."""
    lines = []
    for ch in p.chains:
        for op in ('Test1', 'Test2'):
            if op not in ch.ops:
                continue
            lvl = ch.levels[op]
            r = lvl['alloc']
            upm_m = p.alloc[(ch.vendor, op)]['upm'][ch.sku]
            for i in range(p.H):
                lines.append({'month': p.months[i], 'sku': ch.sku, 'vendor': ch.vendor, 'step': op,
                              'share': ch.share * 100, 'yield': lvl['yield'][PAD + i] * 100, 'rework': lvl['rw'][PAD + i] * 100,
                              'good_out': lvl['net_out'][PAD + i + lvl['delta']] if PAD + i + lvl['delta'] < p.N else 0,
                              'starts_req': lvl['starts_req'][PAD + i], 'ins_req': r['load'][i],
                              'upm': upm_m[i], 'tc': r['tc'][i], 'tn': r['tn'][i], 'prod': r['prod'][i], 'gap': r['gap'][i],
                              'pullin': r['pullin'][i], 'covered': r['covered'][i],
                              'starts': lvl['starts'][PAD + i]})
    caps = []
    for (v, op), a in sorted(p.alloc.items()):
        for row in a['summary'][:p.H]:
            caps.append(dict(row, vendor=v, step=op))
    late = []
    for ch in p.chains:
        for op in ch.ops:
            lvl = ch.levels[op]
            if lvl['late'] > 0.5:
                late.append({'sku': ch.sku, 'vendor': ch.vendor, 'op': op, 'qty': lvl['late'],
                             'first': p.lab(lvl['late_first']) if lvl['late_first'] is not None else ''})
    for (v, op), a in p.alloc.items():
        for row in a['summary'][:p.H]:
            if row['gap'] > 0.5:
                p.alerts.append({'severity': 'high', 'module': 'Testing Starts', 'sku': f'OSAT-{v} {op}', 'month': row['month'],
                                 'text': f'Testers at OSAT-{v} {op} are short by {row["gap"]:,.0f} {"wafers" if op == "Sort" else "units"} '
                                         f'after pull-in ({row["needed"]:.1f} testers needed, {row["total"]} available).'})
                break
    return {'lines': lines, 'caps': caps, 'late': late}


def flow_view(p: Plan):
    """Module 4: one row per product, vendor and month through every step."""
    rows = []
    for ch in p.chains:
        fg = p.fg[(ch.sku, ch.vendor)]
        for i in range(p.H):
            pos = PAD + i
            row = {'month': p.months[i], 'sku': ch.sku, 'vendor': ch.vendor, 'demand': ch.demand[i],
                   'ship': fg['ship'][i], 'short': fg['short'][i], 'fg_end': fg['fg_end'][i], 'ss': fg['ss'][i],
                   'pack_out': fg['pack_out'][i]}
            for op in FLOW_ORDER:
                if op in ch.ops:
                    lvl = ch.levels[op]
                    row[op] = lvl['starts'][pos]
                    if op in ('Test1', 'Test2', 'Sort'):
                        row[op + '_gap'] = lvl['alloc']['gap'][i]
                        row[op + '_pullin'] = lvl['alloc']['pullin'][i]
                else:
                    row[op] = None
            rows.append(row)
    # stage totals by month for the dashboard
    totals = {}
    for op in FLOW_ORDER:
        totals[op] = [sum((r[op] or 0) for r in rows if r['month'] == m) for m in p.months]
    totals['demand'] = [sum(r['demand'] for r in rows if r['month'] == m) for m in p.months]
    totals['ship'] = [sum(r['ship'] for r in rows if r['month'] == m) for m in p.months]
    totals['short'] = [sum(r['short'] for r in rows if r['month'] == m) for m in p.months]
    totals['fab_starts'] = [p.fab_total[PAD + i] for i in range(p.H)]
    return {'rows': rows, 'totals': totals}


def assembly_view(p: Plan):
    rows = []
    for ch in p.chains:
        if 'Assembly' not in ch.ops:
            continue
        lvl = ch.levels['Assembly']
        for i in range(p.H):
            pos = PAD + i
            dpw = p.die_per_wafer(ch.sku, ch.vendor, pos)
            rows.append({'month': p.months[i], 'sku': ch.sku, 'vendor': ch.vendor,
                         'units_out_needed': lvl['net_out'][pos + lvl['delta']] if pos + lvl['delta'] < p.N else 0,
                         'yield': lvl['yield'][pos] * 100, 'die_in': lvl['starts'][pos], 'die_per_wafer': dpw,
                         'wafers': lvl['starts'][pos] / dpw if dpw else 0})
    sup = []
    for ch in p.chains:
        if 'Assembly' not in ch.ops:
            continue
        lvl = ch.levels['Assembly']
        sup.append({'sku': ch.sku, 'vendor': ch.vendor, 'supply': lvl['supply_out'], 'left': lvl['supply_left'],
                    'diebank': p.supply.get((ch.sku, ch.vendor, 'DieBank', 'out'), 0.0)})
    return {'rows': rows, 'supply': sup}


def frontend_view(p: Plan):
    rows = []
    for ch in p.chains:
        for i in range(p.H):
            pos = PAD + i
            row = {'month': p.months[i], 'sku': ch.sku, 'vendor': ch.vendor}
            for op in WAFER_OPS:
                if op in ch.ops:
                    lvl = ch.levels[op]
                    row[op] = lvl['starts'][pos]
                    if op == 'Sort':
                        row['sort_gap'] = lvl['alloc']['gap'][i]
                        row['probers'] = lvl['alloc']['tc'][i] + lvl['alloc']['tn'][i]
                else:
                    row[op] = None
            rows.append(row)
    fab = []
    for sku, f in p.fab.items():
        for i in range(p.H):
            pos = PAD + i
            fab.append({'month': p.months[i], 'sku': sku, 'need': f['need'][pos], 'wip': f['wip'][pos],
                        'outs': f['outs'][pos], 'starts': f['starts'][pos], 'gap': f['cum_gap'][pos]})
    return {'rows': rows, 'fab': fab}


def _test_rate(p, vendor, sku, step, share_nc):
    c = p.cap.get((vendor, sku, step))
    if not c:
        return 0.0
    return float(c['CostConsigneeUSD']) * (1 - share_nc) + float(c['CostNonConsigneeUSD']) * share_nc


def _osat_cost(p, vendor, op, sku):
    rows = [r for r in p.t['osat_costs'] if r['Vendor'] == vendor and r['Operation'] == op]
    exact = [r for r in rows if r['SKU'] == sku]
    star = [r for r in rows if r['SKU'] == '*']
    r = (exact or star or [None])[0]
    return float(r['CostUSD']) if r else None


def cost_view(p: Plan, R):
    """Module 7: spend by vendor/process/month and standard cost per good unit."""
    spend = []
    missing = set()
    nc_share = {}
    for ch in p.chains:
        for op in TEST_OPS:
            if op in ch.ops:
                a = ch.levels[op]['alloc']
                tot = sum(a['prod'][:p.H]) or 1
                nc_share[(ch.sku, ch.vendor, op)] = sum(x - y for x, y in zip(a['prod'][:p.H], a['prod_c'][:p.H])) / tot
    for ch in p.chains:
        for i in range(p.H):
            pos = PAD + i
            for op in ch.ops:
                lvl = ch.levels[op]
                qty = lvl['starts'][pos]
                if op in TEST_OPS:
                    a = lvl['alloc']
                    qty_ins = a['prod'][i]
                    c_units = a['prod_c'][i]
                    cap = p.cap.get((ch.vendor, ch.sku, op))
                    cost = (c_units * float(cap['CostConsigneeUSD']) + (qty_ins - c_units) * float(cap['CostNonConsigneeUSD'])) if cap else 0
                    spend.append({'month': p.months[i], 'sku': ch.sku, 'vendor': ch.vendor, 'process': op,
                                  'qty': qty_ins, 'unit': 'wafers' if op == 'Sort' else 'insertions', 'cost': cost})
                else:
                    rate = _osat_cost(p, ch.vendor, op, ch.sku)
                    if rate is None:
                        missing.add((ch.vendor, op, ch.sku))
                        rate = 0.0
                    spend.append({'month': p.months[i], 'sku': ch.sku, 'vendor': ch.vendor, 'process': op,
                                  'qty': qty, 'unit': 'wafers' if op in WAFER_OPS else 'units', 'cost': qty * rate})
    for sku, f in p.fab.items():
        price = float(p.products[sku]['WaferPriceUSD'])
        for i in range(p.H):
            q = f['starts'][PAD + i]
            if q:
                spend.append({'month': p.months[i], 'sku': sku, 'vendor': 'FAB', 'process': 'Fab', 'qty': q,
                              'unit': 'wafers', 'cost': q * price})
    for v, op, sku in sorted(missing):
        p.issues.append(('warning', 'osat_costs', f'No {op} price for {sku} at OSAT-{v}; costed at zero.'))
    # standard cost roll-up per good unit
    std = {}
    std_rows = []
    for ch in p.chains:
        pos = PAD + 1
        sku, v = ch.sku, ch.vendor
        gupw = p.good_units_per_wafer(sku, v, pos)
        parts = {'Fab': float(p.products[sku]['WaferPriceUSD']) / gupw if gupw else 0}
        later = {}
        y_after = 1.0
        for op in reversed(ch.ops):
            if op not in WAFER_OPS:
                y_after *= p.yld(sku, v, op, pos)
            later[op] = y_after
        for op in ch.ops:
            if op in WAFER_OPS:
                if op == 'Sort':
                    rate = _test_rate(p, v, sku, 'Sort', nc_share.get((sku, v, 'Sort'), 0))
                else:
                    rate = _osat_cost(p, v, op, sku) or 0
                parts[op] = rate / gupw if gupw else 0
            else:
                y_from = later[op]           # good units out of this step through to FG, per unit started
                rate = (_test_rate(p, v, sku, op, nc_share.get((sku, v, op), 0)) * (1 + p.rework(sku, v, op, pos))
                        if op in TEST_OPS else (_osat_cost(p, v, op, sku) or 0))
                parts[op] = rate / y_from if y_from else 0
        total = sum(parts.values())
        std[(sku, v)] = total
        std_rows.append(dict(sku=sku, vendor=v, total=total, gupw=gupw, **{k: parts.get(k) for k in ['Fab'] + FLOW_ORDER}))
    by_sku = {}
    for sku in p.products:
        ws_ = [(ch.share, std[(ch.sku, ch.vendor)]) for ch in p.chains if ch.sku == sku]
        if ws_:
            by_sku[sku] = sum(a * b for a, b in ws_) / (sum(a for a, _ in ws_) or 1)
    return {'spend': spend, 'std': std_rows, 'std_by_sku': by_sku, 'nc_share': nc_share}


def _cutoff_status(as_of, cutoff, semi):
    if as_of > cutoff:
        return 'PAST CUTOFF', 'bad'
    if as_of > semi:
        return 'ORDER NOW', 'warn'
    if as_of > semi - timedelta(days=14):
        return 'UPCOMING', 'info'
    return 'PLANNED', 'ok'


def fab_po_view(p: Plan):
    cut, semi = int(p.s['Fab order cutoff day']), int(p.s['Fab semi-cutoff day'])
    rows = []
    for sku, f in p.fab.items():
        price = float(p.products[sku]['WaferPriceUSD'])
        for i in range(p.H):
            q = f['starts'][PAD + i]
            if q <= 0:
                continue
            m = p.months[i]
            c_date = month_day(month_add(m, -1), cut)
            s_date = month_day(month_add(m, -2), semi)
            status, tone = _cutoff_status(p.as_of, c_date, s_date)
            out_m = month_add(m, f['d_start'])
            ship_to = {}
            for v, arr in f['per_vendor'].items():
                tot = sum(f['need'][PAD:]) or 1
                ship_to[v] = sum(arr[PAD:]) / tot
            rows.append({'start_month': m, 'out_month': out_m, 'sku': sku, 'wafers': q, 'lots': int(q // p.lot),
                         'price': price, 'value': q * price, 'cutoff': c_date, 'semi': s_date, 'status': status,
                         'tone': tone, 'days_to_cutoff': (c_date - p.as_of).days,
                         'ship_to': ', '.join(f'{v} {s * 100:.0f}%' for v, s in sorted(ship_to.items()))})
    order = {'PAST CUTOFF': 0, 'ORDER NOW': 1, 'UPCOMING': 2, 'PLANNED': 3}
    rows.sort(key=lambda r: (order[r['status']], r['start_month'], r['sku']))
    expedite = [{'sku': s, 'wafers': f['late_wafers'], 'months': ', '.join(m for m, _ in f['late_by'][:4])}
                for s, f in p.fab.items() if f['late_wafers'] > 0.5]
    return {'rows': rows, 'expedite': expedite}


OSAT_OPS_PO = ['Sort', 'Bump', 'Assembly', 'Test1', 'Test2', 'Pack']


def osat_po_view(p: Plan, R):
    cut, semi = int(p.s['OSAT order cutoff day']), int(p.s['OSAT semi-cutoff day'])
    agg = defaultdict(lambda: defaultdict(float))
    for r in R['cost']['spend']:
        if r['vendor'] == 'FAB':
            continue
        k = (r['vendor'], r['month'], r['sku'])
        agg[k][r['process']] += r['qty']
        agg[k]['_cost'] += r['cost']
    rows = []
    for (v, m, sku), d in agg.items():
        if d['_cost'] <= 0 and not any(d[o] for o in OSAT_OPS_PO):
            continue
        c_date = month_day(month_add(m, -1), cut)
        s_date = month_day(month_add(m, -2), semi)
        status, tone = _cutoff_status(p.as_of, c_date, s_date)
        rows.append(dict(vendor=v, month=m, sku=sku, cost=d['_cost'], cutoff=c_date, semi=s_date, status=status, tone=tone,
                         **{o: d.get(o, 0.0) for o in OSAT_OPS_PO}))
    rows.sort(key=lambda r: (r['month'], r['vendor'], r['sku']))
    by_vendor = defaultdict(float)
    for r in rows:
        by_vendor[r['vendor']] += r['cost']
    return {'rows': rows, 'by_vendor': dict(by_vendor)}


def substrate_view(p: Plan, R):
    stock = defaultdict(list)
    for r in p.t['substrates']:
        stock[(r['SKU'], r['Vendor'])].append(dict(r, left=float(r['Units'])))
    for v in stock.values():
        v.sort(key=lambda r: (r['ArrivalMonth'], r['ExpiryMonth']))
    rows, expired = [], []
    for ch in p.chains:
        mat = p.products[ch.sku]['SubstrateType']
        if mat == 'None' or 'Assembly' not in ch.ops:
            continue
        batches = stock.get((ch.sku, ch.vendor), [])
        if not batches:
            p.issues.append(('warning', 'substrates', f'{ch.sku} needs {mat.lower()} at OSAT-{ch.vendor} but no stock or arrivals are listed.'))
        lvl = ch.levels['Assembly']
        for i in range(p.H):
            m = p.months[i]
            need = lvl['starts'][PAD + i]
            for b in batches:          # write off what expired before this month
                if b['ExpiryMonth'] < m and b['left'] > 0 and b['ArrivalMonth'] <= m:
                    expired.append({'sku': ch.sku, 'vendor': ch.vendor, 'supplier': b['Supplier'], 'arrival': b['ArrivalMonth'],
                                    'expiry': b['ExpiryMonth'], 'units': b['left']})
                    b['left'] = 0.0
            used, consigned = 0.0, 0.0
            for b in batches:
                if need - used <= EPS:
                    break
                if b['ArrivalMonth'] > m or b['ExpiryMonth'] < m or b['left'] <= 0:
                    continue
                take = min(b['left'], need - used)
                b['left'] -= take
                used += take
                if b['Consigned'] == 'Y':
                    consigned += take
            short = max(0.0, need - used)
            on_hand = sum(b['left'] for b in batches if b['ArrivalMonth'] <= m and b['ExpiryMonth'] >= m)
            pct = short / need * 100 if need else 0
            sev = 'OK' if short <= 0.5 else ('CRITICAL' if pct >= 50 else 'HIGH' if pct >= 25 else 'MEDIUM')
            rows.append({'month': m, 'sku': ch.sku, 'vendor': ch.vendor, 'material': mat, 'need': need, 'used': used,
                         'consigned': consigned, 'short': short, 'on_hand_after': on_hand, 'severity': sev})
    first_short = {}
    for r in rows:
        if r['severity'] != 'OK' and (r['sku'], r['vendor']) not in first_short:
            first_short[(r['sku'], r['vendor'])] = r
            p.alerts.append({'severity': 'high' if r['severity'] in ('CRITICAL', 'HIGH') else 'medium',
                             'module': 'Substrate', 'sku': r['sku'], 'month': r['month'],
                             'text': f'{r["material"]} for {r["sku"]} at OSAT-{r["vendor"]} runs short by {r["short"]:,.0f} units '
                                     f'in {r["month"]}: assembly cannot start without it. Pull in or order a delivery before then.'})
    for e in expired:
        p.alerts.append({'severity': 'medium', 'module': 'Substrate', 'sku': e['sku'], 'month': e['expiry'],
                         'text': f'{e["units"]:,.0f} {e["sku"]} material units at OSAT-{e["vendor"]} expire unused ({e["expiry"]}).'})
    return {'rows': rows, 'expired': expired}


def atp_view(p: Plan):
    """Cumulative available-to-promise by product, vendor and bin."""
    H = p.H
    res = defaultdict(lambda: [0.0] * H)
    for r in p.t['reservations']:
        if r['Status'] != 'Reserved':
            continue
        m = r['SSD'][:7]
        i = max(0, month_diff(m, p.start))
        if i < H:
            res[(r['SKU'], r['Vendor'], r['Bin'])][i] += float(r['Qty'])
    table = {}
    for ch in p.chains:
        fg = p.fg[(ch.sku, ch.vendor)]
        bins = p.bins.get(ch.sku) or [('BIN_1', 1.0)]
        for b, frac in bins:
            onhand = p.fg_bins.get((ch.sku, ch.vendor, b), 0.0)
            supply_cum, s = [], onhand
            for i in range(H):
                s += fg['pack_out'][i] * frac
                supply_cum.append(s)
            rv = res[(ch.sku, ch.vendor, b)]
            rc, c = [], 0.0
            for i in range(H):
                c += rv[i]
                rc.append(c)
            net = [a - b_ for a, b_ in zip(supply_cum, rc)]
            atp = [min(net[i:]) for i in range(H)]
            table[(ch.sku, ch.vendor, b)] = {'onhand': onhand, 'supply_cum': supply_cum, 'reserved_cum': rc,
                                             'atp': [max(0.0, a) for a in atp], 'reserved': rv}
    return {'table': table}


def atp_check(p: Plan, atp: dict, lines: list[dict]):
    """Promise order lines against ATP. Returns one result per line, with allocations."""
    accept = defaultdict(dict)
    for r in p.t['customer_bins']:
        accept[(r['Customer'].lower(), r['SKU'])][r['Bin']] = int(r['MOQ'] or 0)
    # cumulative (supply - reserved); ATP in month i = min of it from i onwards
    net = {k: [a - b for a, b in zip(v['supply_cum'], v['reserved_cum'])] for k, v in atp['table'].items()}
    atp_at = lambda k, i: max(0.0, min(net[k][i:]))
    out = []
    for ln in lines:
        sku, cust, b, qty, crd = ln['sku'], ln['customer'], ln['bin'], float(ln['qty']), ln['crd']
        res = {'line': ln, 'allocations': [], 'messages': [], 'status': '', 'qty': qty}
        ok_bins = accept.get((cust.lower(), sku))
        if ok_bins is not None and b not in ok_bins:
            res['messages'].append(f'{cust} does not accept {sku} {b} (accepted: {", ".join(sorted(ok_bins)) or "none"}).')
            res['status'] = 'NOT ALLOWED'
            out.append(res)
            continue
        if ok_bins is None:
            res['messages'].append(f'{cust} has no row for {sku} in the shippable matrix; no MOQ applied.')
        moq = (ok_bins or {}).get(b, 0)
        if moq and qty % moq:
            q2 = math.ceil(qty / moq) * moq
            res['messages'].append(f'Rounded up from {qty:,.0f} to {q2:,.0f} for the customer MOQ of {moq:,}.')
            qty = q2
        res['qty'] = qty
        i0 = max(0, month_diff(crd[:7], p.start))
        if i0 >= p.H:
            res['status'] = 'OUTSIDE HORIZON'
            res['messages'].append('The requested date is after the plan horizon.')
            out.append(res)
            continue
        keys = [k for k in net if k[0] == sku and k[2] == b]
        if not keys:
            res['status'] = 'NOT AVAILABLE'
            res['messages'].append(f'No vendor makes {sku} {b} in this plan.')
            out.append(res)
            continue
        need = qty
        for i in range(i0, p.H):
            if need <= 0.5:
                break
            for k in sorted(keys, key=lambda k: -atp_at(k, i)):
                avail = math.floor(atp_at(k, i))
                if avail <= 0 or need <= 0.5:
                    continue
                take = min(avail, need)
                for j in range(i, p.H):
                    net[k][j] -= take
                ssd = crd if i == i0 else f'{p.months[i]}-01'
                res['allocations'].append({'vendor': k[1], 'qty': take, 'ssd': ssd, 'month': p.months[i]})
                need -= take
        promised = qty - need
        if need <= 0.5 and all(a['month'] == p.months[i0] for a in res['allocations']):
            res['status'] = 'AVAILABLE'
        elif need <= 0.5:
            res['status'] = 'LATER DATE'
            res['messages'].append('Not all of it is available by the requested date; the rest ships later, as listed.')
        elif promised > 0:
            res['status'] = 'PARTIAL'
            res['messages'].append(f'{need:,.0f} units cannot be promised within the plan horizon.')
        else:
            res['status'] = 'NOT AVAILABLE'
            res['messages'].append('Nothing can be promised within the plan horizon.')
        res['qty'] = qty
        out.append(res)
    return out


def pnl_view(p: Plan, R):
    std = R['cost']['std_by_sku']
    price = defaultdict(dict)
    for r in p.t['pricing']:
        price[r['SKU']][r['Customer']] = float(r['ASPUSD'])
    orders = defaultdict(lambda: defaultdict(float))
    for r in p.t['orders']:
        if r['Status'] != 'Cancelled':
            i = month_diff(r['Month'], p.start)
            if 0 <= i < p.H:
                orders[(r['SKU'], i)][r['Customer']] += float(r['Qty'])
    ship = defaultdict(lambda: [0.0] * p.H)
    short = defaultdict(lambda: [0.0] * p.H)
    for (sku, v), fg in p.fg.items():
        for i in range(p.H):
            ship[sku][i] += fg['ship'][i]
            short[sku][i] += fg['short'][i]
    rows = []
    for sku in p.products:
        if sku not in std:
            continue
        for i in range(p.H):
            left = ship[sku][i]
            for cust, q in sorted(orders[(sku, i)].items()):
                take = min(left, q)
                left -= take
                if take > 0:
                    asp = price[sku].get(cust, price[sku].get('*', 0.0))
                    rows.append({'sku': sku, 'month': p.months[i], 'customer': cust, 'units': take, 'asp': asp,
                                 'revenue': take * asp, 'cogs': take * std[sku]})
            if left > 0.5:
                asp = price[sku].get('*', 0.0)
                rows.append({'sku': sku, 'month': p.months[i], 'customer': 'Forecast (no order yet)', 'units': left,
                             'asp': asp, 'revenue': left * asp, 'cogs': left * std[sku]})
    for sku in p.products:
        if sku in std and not price[sku]:
            p.issues.append(('warning', 'pricing', f'No selling price for {sku}; its revenue shows as zero.'))
    lost = []
    for sku in p.products:
        if sku not in std:
            continue
        units = sum(short[sku][i] - (short[sku][i - 1] if i else 0) for i in range(p.H) if short[sku][i] > (short[sku][i - 1] if i else 0))
        if units > 0.5:
            asp = price[sku].get('*', 0.0)
            lost.append({'sku': sku, 'units': units, 'revenue': units * asp, 'margin': units * (asp - std[sku])})
    return {'rows': rows, 'std': std, 'lost': lost}


def osat_wip_view(p: Plan):
    lots = p.lots
    by_vendor = defaultdict(lambda: {'lots': 0, 'units': 0.0, 'wafers': 0.0, 'hold': 0, 'hold_units': 0.0})
    matrix = defaultdict(float)
    for l in lots:
        d = by_vendor[l['Vendor']]
        d['lots'] += 1
        d['units'] += float(l.get('Units') or 0)
        d['wafers'] += float(l.get('Wafers') or 0)
        if l['State'] == 'HOLD':
            d['hold'] += 1
            d['hold_units'] += float(l.get('Units') or 0) or float(l.get('Wafers') or 0)
        if not l['issue']:
            q = float(l.get('Units') or 0) if l['Operation'] not in ('Sort', 'Bump', 'DieBank') else float(l.get('Wafers') or 0)
            matrix[(l['SKU'], l['Operation'])] += q
    unmapped = [l for l in lots if l['issue']]
    for l in unmapped:
        p.issues.append(('warning', 'osat_wip', f'Lot {l["LotID"]} at OSAT-{l["Vendor"]}: {l["issue"]} '
                                                f'("{l["VendorProduct"]}" / "{l["VendorOperation"]}"). It is left out of the plan.'))
    fg = defaultdict(lambda: defaultdict(float))
    for (sku, v, b), q in p.fg_bins.items():
        fg[sku][b] += q
    return {'lots': lots, 'by_vendor': dict(by_vendor), 'matrix': dict(matrix), 'unmapped': unmapped,
            'holds': [l for l in lots if l['State'] == 'HOLD'], 'fg_bins': {k: dict(v) for k, v in fg.items()}}


def hardware_view(p: Plan):
    rows = []
    for (v, st), ready in sorted(p.hw_ready.items()):
        fleet_c = p.fleet_m.get((v, st), [[0] * p.H])[0]
        a = p.alloc.get((v, st))
        used = [x['alloc_c'] for x in a['summary'][:p.H]] if a else [0] * p.H
        need_c = [min(x['needed_int'], fleet_c[i]) for i, x in enumerate(a['summary'][:p.H])] if a else [0] * p.H
        for i in range(p.H):
            rows.append({'vendor': v, 'step': st, 'month': p.months[i], 'fleet_c': fleet_c[i], 'ready': ready[i],
                         'gap': max(0, fleet_c[i] - ready[i]), 'planned_c': used[i], 'need_c': need_c[i]})
    first = {}
    for r in rows:
        if r['gap'] > 0 and (r['vendor'], r['step']) not in first:
            first[(r['vendor'], r['step'])] = r
            p.alerts.append({'severity': 'medium', 'module': 'Hardware', 'sku': f'OSAT-{r["vendor"]} {r["step"]}', 'month': r['month'],
                             'text': f'Only {r["ready"]} of {r["fleet_c"]} consignee testers at OSAT-{r["vendor"]} {r["step"]} have a full '
                                     f'hardware kit in {r["month"]}.'})
    items = [dict(r) for r in p.t['hardware']]
    arrivals = sorted([dict(r) for r in p.t.get('hardware_arrivals', [])], key=lambda r: r['Month'])
    return {'rows': rows, 'items': items, 'arrivals': arrivals}


def ate_view(p: Plan, R):
    price = float(p.s['Tester price USD'])
    opex = float(p.s['Tester running cost USD per month'])
    rate = float(p.s['Discount rate %']) / 100 / 12
    months = int(p.s['Analysis months'])
    buf = float(p.s['Capacity buffer %']) / 100
    cases = []
    lost_by_sku = {l['sku']: l for l in R['pnl']['lost']}
    for (v, st), a in sorted(p.alloc.items()):
        nc_units, saving_units, upms, gap_units = 0.0, 0.0, [], 0.0
        for sku, r in a['res'].items():
            c = p.cap.get((v, sku, st))
            if not c:
                continue
            ncu = sum(x - y for x, y in zip(r['prod'][:p.H], r['prod_c'][:p.H]))
            nc_units += ncu
            saving_units += ncu * (float(c['CostNonConsigneeUSD']) - float(c['CostConsigneeUSD']))
            upms.append(sum(a['upm'][sku][:p.H]) / p.H)
            gap_units += sum(r['gap'][:p.H])
        if not upms:
            continue
        t_used = sum(sum(r['tc'][:p.H]) + sum(r['tn'][:p.H]) for r in a['res'].values())
        made = sum(sum(r['prod'][:p.H]) for r in a['res'].values())
        avg_upm = made / t_used if t_used > EPS else sum(upms) / len(upms)   # units one tester makes for this mix
        months_n = p.H
        avg_nc = nc_units / months_n
        diff = saving_units / nc_units if nc_units else 0.0
        scen = []
        for k in (1, 2, 3, 4):
            shift = min(avg_nc, k * avg_upm)
            recovered = min(gap_units / months_n, max(0.0, k * avg_upm - shift))
            monthly = shift * diff - k * opex
            npv = -k * price + sum(monthly / (1 + rate) ** t for t in range(1, months + 1))
            payback = (k * price / monthly) if monthly > 0 else None
            scen.append({'testers': k, 'units_moved': shift, 'gap_recovered': recovered, 'monthly_saving': monthly,
                         'payback': payback, 'npv': npv, 'roi': (monthly * months - k * price) / (k * price) * 100 if price else None})
        cap_units = [x['total'] * avg_upm for x in a['summary'][:p.H]]
        need_units = [x['needed'] * avg_upm for x in a['summary'][:p.H]]
        peak_need = max(x['needed'] for x in a['summary'][:p.H])
        slack = [{'month': x['month'], 'have': x['total'], 'want': x['needed'] * (1 + buf),
                  'slack': x['total'] - x['needed'] * (1 + buf)} for x in a['summary'][:p.H]]
        best = max(scen, key=lambda s: s['npv'])
        cases.append({'vendor': v, 'step': st, 'avg_nc_units': avg_nc, 'rate_diff': diff, 'avg_upm': avg_upm,
                      'gap_units': gap_units, 'scenarios': scen, 'best': best, 'slack': slack, 'peak_need': peak_need,
                      'invest': best['npv'] > 0 or any(s['slack'] < 0 for s in slack)})
    return {'cases': cases, 'price': price, 'opex': opex, 'months': months, 'lost': R['pnl']['lost']}


def npi_view(p: Plan):
    out = []
    ms = defaultdict(list)
    for r in p.t['npi_milestones']:
        ms[r['SKU']].append(r)
    fab_days = float(p.s['Fab cycle time weeks']) * 7
    transit = int(p.s['Fab to OSAT transit days'])
    for sku, prod in p.products.items():
        if prod['Status'] != 'NPI':
            continue
        start = to_date(prod.get('NPIStartDate')) or p.as_of
        steps = [{'name': 'Fab (engineering wafers)', 'start': start, 'end': start + timedelta(days=fab_days), 'kind': 'fab'}]
        t = steps[-1]['end'] + timedelta(days=transit)
        for op in p.ops_of(sku):
            d = float(p.flow[sku][op]['CycleTimeDays'])
            steps.append({'name': op, 'start': t, 'end': t + timedelta(days=d), 'kind': 'osat',
                          'yield': float(p.flow[sku][op]['Yield'])})
            t = steps[-1]['end']
        samples = t
        qual = []
        failed = []
        for r in sorted(ms.get(sku, []), key=lambda r: r['Order']):
            status = r.get('Status') or 'Planned'
            actual = to_date(r.get('ActualEnd'))
            e = t + timedelta(days=int(r['CycleDays']))
            ro = e + timedelta(days=int(r['ReadoutDays']))
            if actual:                       # the real readout date re-plans every later milestone
                ro = actual
                e = min(e, actual)
            elif status == 'Running' and ro < p.as_of:
                ro = p.as_of                 # still running past its planned readout: earliest finish is today
            slip = (actual - (t + timedelta(days=int(r['CycleDays']) + int(r['ReadoutDays'])))).days if actual else 0
            qual.append({'name': r['Milestone'], 'start': t, 'end': e, 'readout': ro, 'kind': 'qual',
                         'status': status, 'actual': actual, 'slip': slip})
            if status == 'Failed':
                failed.append(r['Milestone'])
            elif status != 'Passed' and not actual and ro < p.as_of:
                p.issues.append(('warning', 'npi_milestones', f'{sku} "{r["Milestone"]}" should have read out by {ro:%d %b %Y}: '
                                                              f'set its Status and ActualEnd.'))
            t = ro
        qual_done = t
        first_dem = next((p.months[i] for i in range(p.H) if p.dem.get(sku, [0] * p.H)[i] > 0), None)
        need_date = month_day(first_dem, 1) if first_dem else None
        risk = bool(need_date and qual_done > need_date) or bool(failed)
        if failed:
            p.alerts.append({'severity': 'high', 'module': 'NPI', 'sku': sku, 'month': first_dem,
                             'text': f'{sku} failed {", ".join(failed)}: qualification is not complete until a fix is re-tested. '
                                     f'Add the re-test as a new milestone and review the first-shipment date.'})
        if need_date and qual_done > need_date:
            p.alerts.append({'severity': 'high', 'module': 'NPI', 'sku': sku, 'month': first_dem,
                             'text': f'{sku} qualification finishes {qual_done:%d %b %Y}, after the first customer demand '
                                     f'({need_date:%b %Y}). Production would have to start at risk, or demand moves out.'})
        lead_m = None
        ch = next((c for c in p.chains if c.sku == sku), None)
        if ch:
            lead_m = ch.off['_fabstart']
        done = sum(1 for q in qual if q['status'] == 'Passed')
        out.append({'sku': sku, 'start': start, 'steps': steps, 'qual': qual, 'samples': samples, 'qual_done': qual_done,
                    'failed': failed, 'passed': done,
                    'first_demand': first_dem, 'need_date': need_date, 'risk': risk, 'fab_lead_months': lead_m,
                    'yield_cum': p.good_units_per_wafer(sku) / float(prod['GDPW']) * 100})
    return {'products': out}


def pva_view(p: Plan):
    snap = {(r['Month'], r['Vendor'], r['SKU'], r['Operation']): float(r['PlannedUnits']) for r in p.t['plan_snapshot']}
    rows = []
    for r in p.t['actuals']:
        k = (r['Month'], r['Vendor'], r['SKU'], r['Operation'])
        plan = snap.get(k)
        oee = float(r['AvailabilityPct']) * float(r['PerformancePct']) * float(r['QualityPct']) / 1e4
        att = (float(r['ActualUnits']) / plan * 100) if plan else None
        rows.append(dict(r, planned=plan, attainment=att, oee=oee))
    vend = defaultdict(lambda: {'plan': 0.0, 'actual': 0.0, 'oee': [], 'disr': 0.0, 'n': 0, 'events': 0})
    for r in rows:
        d = vend[r['Vendor']]
        d['plan'] += r['planned'] or 0
        d['actual'] += float(r['ActualUnits'])
        d['oee'].append(r['oee'])
        d['disr'] += float(r['DisruptionDays'])
        d['n'] += 1
        d['events'] += 1 if r['Disruption'] != 'None' else 0
    vendors = []
    for v, d in sorted(vend.items()):
        att = d['actual'] / d['plan'] * 100 if d['plan'] else 0
        oee = sum(d['oee']) / len(d['oee']) if d['oee'] else 0
        disr = d['disr'] / max(1, d['n'])
        score = 0.5 * min(att, 100) + 0.3 * oee + 0.2 * max(0.0, 100 - disr / 30.4 * 100)
        vendors.append({'vendor': v, 'attainment': att, 'oee': oee, 'disruption_days': d['disr'], 'events': d['events'],
                        'score': score})
    actions = []
    advice = {'Tester down': 'Book non-consignee tester time or move load to another OSAT until the tester is back; check Hardware Readiness.',
              'Material shortage': 'Pull in the next substrate / lead frame delivery; see Substrate & Lead Frame.',
              'Yield excursion': 'Hold an engineering review, then enter a temporary Yield override so the plan builds enough.',
              'Hold': 'Disposition held lots on OSAT WIP; released lots count as supply again.',
              'Logistics': 'Expedite the shipment and add transit buffer for the next cycle.',
              'None': 'No disruption reported: review the vendor\'s loading and the plan quantity.'}
    for r in rows:
        if r['attainment'] is not None and r['attainment'] < 95:
            actions.append({'month': r['Month'], 'vendor': r['Vendor'], 'sku': r['SKU'], 'op': r['Operation'],
                            'attainment': r['attainment'], 'gap': (r['planned'] or 0) - float(r['ActualUnits']),
                            'cause': r['Disruption'], 'action': advice.get(r['Disruption'], advice['None'])})
    return {'rows': rows, 'vendors': vendors, 'actions': actions}


def plan_snapshot_data(R) -> dict:
    """Compact copy of the current plan for Snapshot comparison."""
    out = {}
    for r in R['flow']['rows']:
        k = f"{r['sku']}|{r['month']}"
        d = out.setdefault(k, {'demand': 0.0, 'Test1': 0.0, 'ship': 0.0, 'short': 0.0})
        d['demand'] += r['demand']
        d['Test1'] += r['Test1'] or 0
        d['ship'] += r['ship']
        d['short'] = max(d['short'], 0) + r['short']
    for r in R['frontend']['fab']:
        k = f"{r['sku']}|{r['month']}"
        out.setdefault(k, {'demand': 0.0, 'Test1': 0.0, 'ship': 0.0, 'short': 0.0})['wafer_starts'] = r['starts']
    return out


def cross_view(p: Plan):
    rows, issues = [], []
    totals = defaultdict(float)
    for r in p.t['cross_flow']:
        totals[(r['SKU'], r['AfterOperation'], r['FromVendor'])] += float(r['Percent']) if r['Status'] == 'Active' else 0
    for k, v in totals.items():
        if v > 100:
            issues.append(f'{k[0]} after {k[1]} at OSAT-{k[2]}: active rules move {v:.0f}% (more than 100%).')
            p.issues.append(('error', 'cross_flow', issues[-1]))
    impact = []
    for r in p.t['cross_flow']:
        ch = next((c for c in p.chains if c.sku == r['SKU'] and c.vendor == r['FromVendor']), None)
        valid = ch is not None and r['AfterOperation'] in (ch.ops if ch else [])
        tov = any(c.sku == r['SKU'] and c.vendor == r['ToVendor'] for c in p.chains) or r['ToVendor'] in p.vendors
        moved = []
        if valid and r['Status'] == 'Active':
            lvl = ch.levels[r['AfterOperation']]
            y = lvl['yield']
            for i in range(p.H):
                out_q = lvl['starts'][PAD + i] * (1.0 if r['AfterOperation'] in WAFER_OPS else y[PAD + i])
                moved.append(out_q * float(r['Percent']) / 100)
        cost = sum(moved) / 1000 * float(r['CostPer1000USD'])
        rows.append(dict(r, valid=valid and tov, moved=moved, moved_total=sum(moved), cost=cost))
        if not valid:
            p.issues.append(('warning', 'cross_flow', f'Cross-flow rule {r["SKU"]} {r["FromVendor"]}->{r["ToVendor"]} after '
                                                      f'{r["AfterOperation"]}: that step is not planned at OSAT-{r["FromVendor"]}.'))
    matrix = defaultdict(float)
    for r in rows:
        if r['Status'] == 'Active':
            matrix[(r['FromVendor'], r['ToVendor'])] += r['moved_total']
    return {'rows': rows, 'matrix': dict(matrix), 'issues': issues}


def b2b_view(p: Plan, R):
    fz, sl = int(p.s['Frozen months']), int(p.s['Slushy months'])
    zones = ['Frozen' if i < fz else 'Slushy' if i < fz + sl else 'Liquid' for i in range(p.H)]
    fab = []
    for sku, f in p.fab.items():
        fab.append({'supplier': 'FAB', 'sku': sku, 'item': 'Wafer starts', 'unit': 'wafers',
                    'qty': [f['starts'][PAD + i] for i in range(p.H)]})
    osat = []
    spend = defaultdict(lambda: [0.0] * p.H)
    for r in R['cost']['spend']:
        if r['vendor'] == 'FAB':
            continue
        i = p.months.index(r['month'])
        spend[(r['vendor'], r['sku'], r['process'], r['unit'])][i] += r['qty']
    for (v, sku, proc, unit), q in sorted(spend.items(), key=lambda kv: (kv[0][0], kv[0][1], FLOW_ORDER.index(kv[0][2]))):
        if sum(q) > 0:
            osat.append({'supplier': f'OSAT-{v}', 'sku': sku, 'item': proc, 'unit': unit, 'qty': q})
    tester = []
    for (v, st), a in sorted(p.alloc.items()):
        tester.append({'supplier': f'OSAT-{v}', 'sku': 'All', 'item': f'{st} testers needed', 'unit': 'testers',
                       'qty': [x['needed_int'] for x in a['summary'][:p.H]]})
    return {'zones': zones, 'fab': fab, 'osat': osat, 'tester': tester}


def checks_view(p: Plan):
    t = p.t
    out = list(p.issues)
    for sku in p.products:
        bins = p.bins.get(sku)
        if not bins:
            out.append(('warning', 'bin_splits', f'{sku} has no bin splits; ATP treats all output as BIN_1.'))
        else:
            tot = sum(f for _, f in bins)
            if abs(tot - 1) > 0.01:
                out.append(('error', 'bin_splits', f'{sku} bin fractions add up to {tot:.2f}, not 1.00.'))
        steps = [r['Step'] for r in t['process_flow'] if r['SKU'] == sku]
        if len(steps) != len(set(steps)):
            out.append(('warning', 'process_flow', f'{sku} has two process steps with the same Step number.'))
        flow_ops = [o for o in FLOW_ORDER if o in p.flow[sku]]
        by_step = [r['Operation'] for r in sorted((r for r in t['process_flow'] if r['SKU'] == sku), key=lambda r: r['Step'])]
        if by_step and by_step != flow_ops:
            out.append(('info', 'process_flow', f'{sku}: steps are planned in the standard order {" > ".join(flow_ops)}.'))
        for need in ('Sort', 'Assembly', 'Test1', 'Pack'):
            if p.flow[sku] and need not in p.flow[sku]:
                out.append(('warning', 'process_flow', f'{sku} has no {need} step; the plan skips it.'))
        if 'Test1' not in p.flow[sku] and 'Test2' in p.flow[sku]:
            out.append(('error', 'process_flow', f'{sku} has Test2 without Test1.'))
        if p.products[sku]['Status'] == 'NPI' and not p.products[sku].get('NPIStartDate'):
            out.append(('warning', 'products', f'{sku} is NPI but has no NPIStartDate.'))
    known = set(p.products)
    for name, col in (('forecast', 'SKU'), ('orders', 'SKU'), ('tester_capacity', 'SKU'), ('process_flow', 'SKU'),
                      ('bin_splits', 'SKU'), ('product_codes', 'SKU'), ('fab_wip', 'SKU'), ('substrates', 'SKU')):
        bad = sorted({r[col] for r in t[name] if r[col] not in known})
        if bad:
            out.append(('warning', name, f'{TABLES[name]["title"]} mentions products not in Products: {", ".join(bad[:6])}.'))
    vend = {r['Vendor'] for r in t['vendors']}
    for name in ('tester_fleet', 'tester_capacity', 'osat_costs', 'hardware', 'osat_wip'):
        bad = sorted({r['Vendor'] for r in t[name] if r['Vendor'] not in vend})
        if bad:
            out.append(('warning', name, f'{TABLES[name]["title"]} mentions vendors not in OSAT vendors: {", ".join(bad)}.'))
    for (v, sku, st) in p.cap:
        if (v, st) not in p.fleet and v in p.vendors:
            out.append(('error', 'tester_fleet', f'OSAT-{v} has test times for {sku} {st} but no {st} testers in the fleet.'))
    for name in ('order_history', 'test_results'):
        bad = sorted({r['SKU'] for r in t.get(name, []) if r['SKU'] not in known})
        if bad:
            out.append(('warning', name, f'{TABLES[name]["title"]} mentions products not in Products: {", ".join(bad[:6])}.'))
    over = [r['LotID'] for r in t.get('test_results', []) if float(r['Passed'] or 0) > float(r['Tested'] or 0)]
    if over:
        out.append(('error', 'test_results', f'{len(over)} test result rows pass more units than they test (e.g. lot {over[0]}); fix Passed or Tested.'))
    lots = {(r['Step'], r['LotID']) for r in t.get('test_results', [])}
    orphan = sorted({r['LotID'] for r in t.get('test_bins', []) if (r['Step'], r['LotID']) not in lots})
    if orphan:
        out.append(('info', 'test_bins', f'{len(orphan)} lots have bin counts but no test result row (e.g. {orphan[0]}); they are left out of the bin Pareto.'))
    for r in t.get('vendor_issues', []):
        if r['Status'] == 'Closed' and not r.get('Closed'):
            out.append(('warning', 'vendor_issues', f'Issue {r["IssueID"]} is Closed without a Closed date; it does not count toward days to close.'))
        if r.get('Closed') and r.get('Opened') and str(r['Closed']) < str(r['Opened']):
            out.append(('error', 'vendor_issues', f'Issue {r["IssueID"]} is closed before it was opened.'))
    pids = {r['ProjectID'] for r in t.get('pf_projects', [])}
    pools = {r['Pool'] for r in t.get('pf_pools', [])}
    for name, cols in (('pf_demand', ['ProjectID']), ('pf_gates', ['ProjectID']), ('pf_risks', ['ProjectID']),
                       ('pf_decisions', ['ProjectID']), ('pf_dependencies', ['From', 'To'])):
        bad = sorted({r[c] for r in t.get(name, []) for c in cols if r.get(c) and r[c] not in pids})
        if bad:
            out.append(('warning', name, f'{TABLES[name]["title"]} mentions projects not in Portfolio projects: {", ".join(bad[:6])}; those rows are ignored.'))
    badp = sorted({r['Pool'] for r in t.get('pf_demand', []) + t.get('pf_capacity_changes', []) + t.get('pf_key_roles', [])
                   + [l for l in t.get('pf_levers', []) if l['Pool'] != 'All'] if r['Pool'] not in pools})
    if badp:
        out.append(('warning', 'pf_demand', f'Portfolio tables use pools not in Skill pools: {", ".join(badp[:6])}; those rows are ignored.'))
    rev = [r for r in t.get('pf_demand', []) if r['To'] < r['From']]
    if rev:
        out.append(('error', 'pf_demand', f'{len(rev)} resource demand rows end before they start (e.g. {rev[0]["ProjectID"]} {rev[0]["Pool"]}).'))
    nodem = sorted(p['Name'] for p in t.get('pf_projects', []) if p['Funding'] != 'Stopped'
                   and not any(d['ProjectID'] == p['ProjectID'] for d in t.get('pf_demand', [])))
    if nodem:
        out.append(('info', 'pf_demand', f'Projects with no resource demand (they cost no capacity): {", ".join(nodem[:6])}.'))
    for r in t.get('pf_projects', []):
        if r['Launch'] < r['Start']:
            out.append(('error', 'pf_projects', f'{r["Name"]} launches before it starts.'))
    wsum = sum(float(r['WeightPct']) for r in t.get('qbr_weights', []))
    if t.get('qbr_weights') and abs(wsum - 100) > 0.5:
        out.append(('info', 'qbr_weights', f'QBR weights add up to {wsum:.0f}%; scores are weighted in proportion.'))
    shares = sum(float(r['SharePct']) for r in t['vendors'] if r['Enabled'] == 'Y')
    if t['vendors'] and abs(shares - 100) > 0.5:
        out.append(('info', 'vendors', f'Vendor shares add up to {shares:.0f}%; they are re-normalised per product.'))
    seen, uniq = set(), []
    for sev, tab, msg in out:
        if (tab, msg) not in seen:
            seen.add((tab, msg))
            uniq.append({'severity': sev, 'table': tab, 'message': msg})
    rank = {'error': 0, 'warning': 1, 'info': 2}
    uniq.sort(key=lambda x: rank[x['severity']])
    return {'items': uniq}


def home_view(p: Plan, R):
    H = p.H
    dem6 = sum(sum(p.dem[s][:6]) for s in p.dem)
    short = sum(max(fg['short'][:H]) for fg in p.fg.values())
    peak = max(((x['util'], v, st, x['month']) for (v, st), a in p.alloc.items() for x in a['summary'][:H]), default=(0, '', '', ''))
    load_peak = max(((x['load_util'], v, st, x['month']) for (v, st), a in p.alloc.items() for x in a['summary'][:H]), default=(0, '', '', ''))
    po_due = [r for r in R['fab_po']['rows'] if r['status'] in ('PAST CUTOFF', 'ORDER NOW')]
    holds = R['osat_wip']['holds']
    rev = sum(r['revenue'] for r in R['pnl']['rows'])
    cogs = sum(r['cogs'] for r in R['pnl']['rows'])
    checks = R['checks']['items']
    sev = {'high': 0, 'medium': 1, 'low': 2}
    seen, alerts = set(), []
    for a in sorted(p.alerts, key=lambda a: (sev.get(a['severity'], 3), str(a.get('month') or ''))):
        k = (a['module'], a['text'])
        if k not in seen:
            seen.add(k)
            alerts.append(a)
    return {'demand6': dem6, 'short': short, 'peak': peak, 'load_peak': load_peak, 'po_due': po_due, 'holds': holds,
            'revenue': rev, 'gm': (rev - cogs) / rev * 100 if rev else 0, 'alerts': alerts,
            'errors': sum(1 for c in checks if c['severity'] == 'error'),
            'warnings': sum(1 for c in checks if c['severity'] == 'warning')}
