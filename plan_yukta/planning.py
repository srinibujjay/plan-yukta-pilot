"""
Plan Yukta planning modules: demand forecasting, module-level supply planning,
ATE tester capacity planning and the monthly B2B forecast package for FAB and OSAT.

These use standard fabless planning methods (exponential smoothing, MRP netting
with lead-time offsets and yields, tester throughput from test time and sites,
rolling forecasts with frozen / slushy / liquid time fences). Every number in
the output can be traced to an input and a formula in METHOD.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

WEEKS_PER_MONTH = 52 / 12            # 4.333
STAGES = ['FAB', 'BUMP', 'SORT', 'ASSY', 'FT']
STAGE_LABEL = {'FAB': 'Fab wafer starts', 'BUMP': 'Bump', 'SORT': 'Wafer sort (CP)',
               'ASSY': 'Assembly', 'FT': 'Final test'}


@dataclass
class PlanSettings:
    plan_start: date                    # first month of the plan (1st of month)
    horizon_months: int = 12
    frozen_months: int = 1              # firm: no changes without escalation
    slushy_months: int = 3              # changes within agreed flex
    alpha: float = 0.35                 # level smoothing
    beta: float = 0.15                  # trend smoothing
    demand_uplift_pct: float = 0.0      # scenario lever applied to final demand
    forecast_method: str = 'BLEND'      # CUSTOMER | STAT | BLEND
    overrides: dict = field(default_factory=dict)   # per-parameter scenario overrides for every product


class PlanningInputError(ValueError):
    pass


def month_start(d) -> pd.Timestamp:
    t = pd.Timestamp(d)
    return pd.Timestamp(t.year, t.month, 1)


def months(start, n):
    s = month_start(start)
    return [s + pd.DateOffset(months=i) for i in range(n)]


def wk_to_m(weeks: float) -> int:
    """Lead-time offset in whole monthly buckets."""
    return int(round(float(weeks) / WEEKS_PER_MONTH))


# ---------------------------------------------------------------------------
# 1. Demand forecasting
# ---------------------------------------------------------------------------
def holt(series: list[float], alpha: float, beta: float, horizon: int):
    """Holt's linear exponential smoothing. Returns (fitted one-step forecasts, future forecasts)."""
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
    future = [max(0.0, level + (h + 1) * trend) for h in range(horizon)]
    return fitted, future


def forecast_demand(demand: pd.DataFrame, s: PlanSettings):
    """
    demand: PRODUCT, MONTH, TYPE (ACTUAL | FORECAST), QTY.
    Returns (plan_demand rows per product-month, accuracy per product).
    """
    d = demand.copy()
    d['MONTH'] = d['MONTH'].apply(month_start)
    d['TYPE'] = d['TYPE'].astype(str).str.upper().str.strip()
    d['QTY'] = pd.to_numeric(d['QTY'], errors='coerce').fillna(0)
    horizon = months(s.plan_start, s.horizon_months)
    rows, acc = [], []
    for product, g in d.groupby('PRODUCT'):
        hist = (g[(g['TYPE'] == 'ACTUAL') & (g['MONTH'] < horizon[0])]
                .groupby('MONTH')['QTY'].sum().sort_index())
        cust = g[g['TYPE'] == 'FORECAST'].groupby('MONTH')['QTY'].sum()
        series = hist.tolist()
        fitted, future = holt(series, s.alpha, s.beta, s.horizon_months)

        # accuracy of the statistical model: one-step-ahead over the last 6 months
        pairs = list(zip(series, fitted))[-6:] if len(series) >= 4 else []
        abs_err = sum(abs(a - f) for a, f in pairs)
        actual_sum = sum(a for a, _ in pairs)
        wmape = (abs_err / actual_sum * 100) if actual_sum else None
        bias = (sum(f - a for a, f in pairs) / actual_sum * 100) if actual_sum else None
        acc.append({'PRODUCT': product, 'history_months': len(series),
                    'last_actual': series[-1] if series else 0,
                    'wmape_pct': None if wmape is None else round(wmape, 1),
                    'bias_pct': None if bias is None else round(bias, 1)})

        for i, m in enumerate(horizon):
            stat = future[i]
            c = cust.get(m)
            has_c = c is not None and not pd.isna(c)
            if s.forecast_method == 'CUSTOMER':
                base, src = (c, 'Customer') if has_c else (stat, 'Statistical (no customer forecast)')
            elif s.forecast_method == 'STAT':
                base, src = stat, 'Statistical'
            else:
                base, src = ((c + stat) / 2, 'Blend 50/50') if has_c else (stat, 'Statistical (no customer forecast)')
            final = base * (1 + s.demand_uplift_pct / 100)
            rows.append({'PRODUCT': product, 'MONTH': m, 'customer_fcst': c if has_c else None,
                         'stat_fcst': round(stat), 'final_demand': round(final), 'source': src})
    return pd.DataFrame(rows), pd.DataFrame(acc), d


# ---------------------------------------------------------------------------
# 2. Module-level supply plan (MRP netting through the fabless flow)
# ---------------------------------------------------------------------------
PARAM_COLS = ['PRODUCT', 'GDW', 'FAB_LINE_YIELD', 'SORT_YIELD', 'ASSY_YIELD', 'FT_YIELD',
              'CT_FAB_WK', 'CT_BUMP_WK', 'CT_SORT_WK', 'CT_ASSY_WK', 'CT_FT_WK',
              'WAFER_LOT', 'SAFETY_STOCK_WK', 'FG_ON_HAND', 'DIE_BANK_ON_HAND']


def _pct(v):
    v = float(v)
    return v / 100 if v > 1 else v


def product_params(params: pd.DataFrame, overrides: dict) -> dict:
    missing = [c for c in PARAM_COLS if c not in params.columns]
    if missing:
        raise PlanningInputError(f"Plan_Params is missing column(s): {', '.join(missing)}")
    out = {}
    for _, r in params.iterrows():
        if pd.isna(r['PRODUCT']):
            continue
        p = {c: r[c] for c in PARAM_COLS}
        for k, v in (overrides or {}).items():
            if v is not None and v != '':
                p[k] = v
        for k in ('FAB_LINE_YIELD', 'SORT_YIELD', 'ASSY_YIELD', 'FT_YIELD'):
            p[k] = min(1.0, max(0.01, _pct(p[k])))
        for k in ('GDW', 'CT_FAB_WK', 'CT_BUMP_WK', 'CT_SORT_WK', 'CT_ASSY_WK', 'CT_FT_WK',
                  'WAFER_LOT', 'SAFETY_STOCK_WK', 'FG_ON_HAND', 'DIE_BANK_ON_HAND'):
            p[k] = float(p[k] or 0)
        p['WAFER_LOT'] = max(1.0, p['WAFER_LOT'])
        p['uses_bump'] = p['CT_BUMP_WK'] > 0
        # good finished units from one started wafer
        p['units_per_wafer'] = p['GDW'] * p['FAB_LINE_YIELD'] * p['SORT_YIELD'] * p['ASSY_YIELD'] * p['FT_YIELD']
        p['good_die_per_wafer'] = p['GDW'] * p['FAB_LINE_YIELD'] * p['SORT_YIELD']
        p['lt_back_m'] = wk_to_m(p['CT_ASSY_WK'] + p['CT_FT_WK'])            # die bank -> FG
        p['lt_front_m'] = wk_to_m(p['CT_FAB_WK'] + p['CT_BUMP_WK'] + p['CT_SORT_WK'])  # wafer start -> die bank
        p['lt_total_wk'] = p['CT_FAB_WK'] + p['CT_BUMP_WK'] + p['CT_SORT_WK'] + p['CT_ASSY_WK'] + p['CT_FT_WK']
        out[str(r['PRODUCT']).strip()] = p
    return out


def wip_receipts(p, wip: dict, start: pd.Timestamp):
    """Project current WIP to finished-goods receipts (units, month), assuming each lot is half way through its stage."""
    out = []
    def add(qty_units, weeks_left, stage):
        if qty_units > 0:
            out.append((stage, start + pd.DateOffset(months=wk_to_m(weeks_left)), qty_units))
    ct = {k: p[f'CT_{k}_WK'] for k in STAGES}
    y = p
    add(wip.get('fab_wip_wafers', 0) * y['GDW'] * y['FAB_LINE_YIELD'] * y['SORT_YIELD'] * y['ASSY_YIELD'] * y['FT_YIELD'],
        ct['FAB'] / 2 + ct['BUMP'] + ct['SORT'] + ct['ASSY'] + ct['FT'], 'Fab')
    add(wip.get('BUMP', 0) * y['GDW'] * y['SORT_YIELD'] * y['ASSY_YIELD'] * y['FT_YIELD'],
        ct['BUMP'] / 2 + ct['SORT'] + ct['ASSY'] + ct['FT'], 'Bump')
    add(wip.get('SORT', 0) * y['GDW'] * y['SORT_YIELD'] * y['ASSY_YIELD'] * y['FT_YIELD'],
        ct['SORT'] / 2 + ct['ASSY'] + ct['FT'], 'Sort')
    add(wip.get('ASSEMBLY', 0) * y['ASSY_YIELD'] * y['FT_YIELD'], ct['ASSY'] / 2 + ct['FT'], 'Assembly')
    add(wip.get('TESTING', 0) * y['FT_YIELD'], ct['FT'] / 2, 'Final test')
    add(wip.get('PACKING', 0), 0, 'Packing')
    return out


def supply_plan(final_demand: pd.DataFrame, params: dict, wip_by_product: dict, s: PlanSettings):
    """
    Monthly MRP per product. For each month:
      projected FG = previous FG + WIP receipts + planned receipts - demand
      safety stock target = SAFETY_STOCK_WK x (demand / 4.33)
      if projected FG < target, plan new FG receipts = shortfall
    Planned receipts are offset back through the flow:
      assembly start = receipt month - lt_back, needing receipts / (assy x ft yield) good die
      good die come from the die bank first, then from new wafers:
      wafer start = assembly start - lt_front, wafers = dies / good die per wafer, rounded up to whole lots
    Lot rounding surplus stays in the die bank for later months.
    A wafer start that would fall before the plan start is reported as inside lead time.
    """
    horizon = months(s.plan_start, s.horizon_months)
    start = horizon[0]
    plan_rows, stage_rows, alerts = [], [], []
    for product, p in params.items():
        dem = final_demand[final_demand['PRODUCT'] == product].set_index('MONTH')['final_demand']
        if dem.empty:
            continue
        receipts = {}
        load = {k: {} for k in STAGES}      # module loads keyed by month

        def add_load(stage, month, qty):
            month = max(month, start)
            load[stage][month] = load[stage].get(month, 0) + qty

        # current WIP still has to pass the downstream modules: include it in their loads
        for stage, m, q in wip_receipts(p, wip_by_product.get(product, {}), start):
            receipts[m] = receipts.get(m, 0) + q
            ft_in = q / p['FT_YIELD']
            if stage in ('Fab', 'Bump', 'Sort', 'Assembly', 'Final test'):
                add_load('FT', m - pd.DateOffset(months=wk_to_m(p['CT_FT_WK'])), ft_in)
            if stage in ('Fab', 'Bump', 'Sort', 'Assembly'):
                add_load('ASSY', m - pd.DateOffset(months=int(p['lt_back_m'])), ft_in / p['ASSY_YIELD'])
            if stage in ('Fab', 'Bump', 'Sort'):
                wafers = q / (p['GDW'] * p['SORT_YIELD'] * p['ASSY_YIELD'] * p['FT_YIELD'])
                add_load('SORT', m - pd.DateOffset(months=wk_to_m(p['CT_SORT_WK'] + p['CT_ASSY_WK'] + p['CT_FT_WK'])), wafers)
            if stage == 'Fab' and p['uses_bump']:
                wafers = q / (p['GDW'] * p['SORT_YIELD'] * p['ASSY_YIELD'] * p['FT_YIELD'])
                add_load('BUMP', m - pd.DateOffset(months=wk_to_m(p['CT_BUMP_WK'] + p['CT_SORT_WK'] + p['CT_ASSY_WK'] + p['CT_FT_WK'])), wafers)
        fg = p['FG_ON_HAND']
        die_bank = p['DIE_BANK_ON_HAND']
        for m in horizon:
            demand_m = float(dem.get(m, 0))
            wip_in = receipts.get(m, 0)
            target = p['SAFETY_STOCK_WK'] * demand_m / WEEKS_PER_MONTH
            projected = fg + wip_in - demand_m
            need_fg = max(0.0, target - projected)
            planned_fg, inside_lt = 0.0, False
            if need_fg > 0:
                assy_m = m - pd.DateOffset(months=int(p['lt_back_m']))
                dies_needed = need_fg / (p['ASSY_YIELD'] * p['FT_YIELD'])
                if assy_m < start:
                    inside_lt = True
                    alerts.append({'PRODUCT': product, 'month': m.strftime('%Y-%m'), 'issue': 'Inside lead time',
                                   'detail': f'{need_fg:,.0f} units would have had to enter assembly in {assy_m:%Y-%m}; '
                                             'only current WIP can cover this month.'})
                else:
                    from_bank = min(die_bank, dies_needed)
                    die_bank -= from_bank
                    new_dies = dies_needed - from_bank
                    planned_fg = need_fg
                    if new_dies > 0:
                        wafer_m = assy_m - pd.DateOffset(months=int(p['lt_front_m']))
                        wafers = new_dies / p['good_die_per_wafer']
                        wafers_rounded = math.ceil(wafers / p['WAFER_LOT']) * p['WAFER_LOT']
                        if wafer_m < start:
                            inside_lt = True
                            planned_fg = from_bank * p['ASSY_YIELD'] * p['FT_YIELD']
                            alerts.append({'PRODUCT': product, 'month': m.strftime('%Y-%m'),
                                           'issue': 'Inside lead time',
                                           'detail': f'{wafers_rounded:,.0f} wafers would have had to start in '
                                                     f'{wafer_m:%Y-%m}; expedite, pull from the die bank or allocate.'})
                        else:
                            # lot rounding surplus: extra good die stay in the die bank
                            die_bank += wafers_rounded * p['good_die_per_wafer'] - new_dies
                            load['FAB'][wafer_m] = load['FAB'].get(wafer_m, 0) + wafers_rounded
                            if p['uses_bump']:
                                bm = wafer_m + pd.DateOffset(months=wk_to_m(p['CT_FAB_WK']))
                                load['BUMP'][bm] = load['BUMP'].get(bm, 0) + wafers_rounded * p['FAB_LINE_YIELD']
                            sm = wafer_m + pd.DateOffset(months=wk_to_m(p['CT_FAB_WK'] + p['CT_BUMP_WK']))
                            load['SORT'][sm] = load['SORT'].get(sm, 0) + wafers_rounded * p['FAB_LINE_YIELD']
                    if planned_fg > 0:
                        dies_in = planned_fg / (p['ASSY_YIELD'] * p['FT_YIELD'])
                        load['ASSY'][assy_m] = load['ASSY'].get(assy_m, 0) + dies_in
                        ftm = assy_m + pd.DateOffset(months=wk_to_m(p['CT_ASSY_WK']))
                        load['FT'][ftm] = load['FT'].get(ftm, 0) + dies_in * p['ASSY_YIELD']
            fg = projected + planned_fg
            wos = (fg / (demand_m / WEEKS_PER_MONTH)) if demand_m else None
            if fg < 0:
                alerts.append({'PRODUCT': product, 'month': m.strftime('%Y-%m'), 'issue': 'Shortage',
                               'detail': f'Projected finished goods {fg:,.0f} units: demand cannot be met.'})
            plan_rows.append({'PRODUCT': product, 'MONTH': m, 'demand': round(demand_m),
                              'wip_receipts': round(wip_in), 'planned_receipts': round(planned_fg),
                              'projected_fg': round(fg), 'safety_stock': round(target),
                              'weeks_of_supply': None if wos is None else round(wos, 1),
                              'die_bank': round(die_bank), 'inside_lead_time': 'yes' if inside_lt else ''})
        for stage in STAGES:
            for m, q in load[stage].items():
                stage_rows.append({'PRODUCT': product, 'STAGE': stage, 'MONTH': m, 'qty': q,
                                   'unit': 'wafers' if stage in ('FAB', 'BUMP', 'SORT') else 'units'})
    plan = pd.DataFrame(plan_rows)
    stages = pd.DataFrame(stage_rows, columns=['PRODUCT', 'STAGE', 'MONTH', 'qty', 'unit'])
    return plan, stages, pd.DataFrame(alerts, columns=['PRODUCT', 'month', 'issue', 'detail'])


# ---------------------------------------------------------------------------
# 3. Tester (ATE) capacity planning
# ---------------------------------------------------------------------------
def tester_plan(stage_loads: pd.DataFrame, params: dict, tester_params: pd.DataFrame,
                capacity: pd.DataFrame, s: PlanSettings, overrides: dict | None = None):
    """
    Final test:  seconds per unit  = (test time + index time) / sites
    Wafer sort:  touchdowns/wafer  = ceil(GDW / sites) / stepping efficiency
                 seconds per wafer = touchdowns x (test time + index time) + wafer load time
    Hours required = quantity x seconds / 3600
    Hours available = testers x hours per week x weeks in month x OEE
    """
    overrides = overrides or {}
    horizon = months(s.plan_start, s.horizon_months)
    tp = tester_params.copy()
    tp.columns = [str(c).strip().upper() for c in tp.columns]
    cap = capacity.copy()
    cap.columns = [str(c).strip().upper() for c in cap.columns]
    need = {}
    detail = []
    for _, r in tp.iterrows():
        prod = str(r['PRODUCT']).strip()
        if prod not in params:
            continue
        ins = str(r['INSERTION']).strip().upper()
        ttype = str(r['TESTER_TYPE']).strip()
        sites = max(1.0, float(r['SITES']))
        tt = float(r['TEST_TIME_S']) * (1 + float(overrides.get('test_time_pct', 0) or 0) / 100)
        idx = float(r.get('INDEX_TIME_S', 0) or 0)
        is_sort = ins.startswith('CP') or ins.startswith('WS')
        if is_sort:
            step = _pct(r.get('STEPPING_EFF', 1) or 1)
            touch = math.ceil(params[prod]['GDW'] / sites) / step
            sec = touch * (tt + idx) + float(r.get('WAFER_LOAD_S', 0) or 0)
            stage, per = 'SORT', 'wafer'
        else:
            sec = (tt + idx) / sites
            stage, per = 'FT', 'unit'
        uph = 3600 / sec if sec else 0
        detail.append({'PRODUCT': prod, 'INSERTION': ins, 'TESTER_TYPE': ttype, 'seconds_per_' + per: round(sec, 3),
                       'per': per, 'throughput_per_hour': round(uph, 1)})
        loads = stage_loads[(stage_loads['PRODUCT'] == prod) & (stage_loads['STAGE'] == stage)]
        for m in horizon:
            q = loads.loc[loads['MONTH'] == m, 'qty'].sum()
            need[(ttype, m)] = need.get((ttype, m), 0) + q * sec / 3600
    rows = []
    for _, c in cap.iterrows():
        ttype = str(c['TESTER_TYPE']).strip()
        qty = float(c['QTY_TESTERS']) + float(overrides.get('extra_testers', 0) or 0)
        oee = _pct(overrides.get('oee') or c['OEE'])
        hpw = float(c['HOURS_PER_WEEK'])
        for m in horizon:
            avail = qty * hpw * WEEKS_PER_MONTH * oee
            req = need.get((ttype, m), 0)
            per_tester = hpw * WEEKS_PER_MONTH * oee
            rows.append({'TESTER_TYPE': ttype, 'OSAT': c.get('OSAT', ''), 'MONTH': m, 'testers': qty,
                         'hours_required': round(req, 1), 'hours_available': round(avail, 1),
                         'utilisation_pct': round(req / avail * 100, 1) if avail else None,
                         'testers_needed': math.ceil(req / per_tester) if per_tester and req else 0,
                         'status': ('OVERLOADED' if avail and req > avail else
                                    'TIGHT (>85%)' if avail and req > 0.85 * avail else 'OK')})
    return pd.DataFrame(rows), pd.DataFrame(detail)


# ---------------------------------------------------------------------------
# 4. Monthly B2B forecast package for FAB and OSAT
# ---------------------------------------------------------------------------
def zone(i: int, s: PlanSettings) -> str:
    if i < s.frozen_months:
        return 'Frozen'
    if i < s.frozen_months + s.slushy_months:
        return 'Slushy'
    return 'Liquid'


def b2b_package(stage_loads: pd.DataFrame, testers: pd.DataFrame, s: PlanSettings):
    horizon = months(s.plan_start, s.horizon_months)
    labels = [m.strftime('%Y-%m') for m in horizon]
    zone_row = {lab: zone(i, s) for i, lab in enumerate(labels)}

    def pivot(stages, unit_label):
        sub = stage_loads[stage_loads['STAGE'].isin(stages)].copy()
        sub['m'] = sub['MONTH'].dt.strftime('%Y-%m')
        sub = sub[sub['m'].isin(labels)]
        if sub.empty:
            return pd.DataFrame(columns=['PRODUCT', 'STAGE'] + labels)
        t = sub.pivot_table(index=['PRODUCT', 'STAGE'], columns='m', values='qty', aggfunc='sum', fill_value=0)
        t = t.reindex(columns=labels, fill_value=0).round(0).astype(int).reset_index()
        t['_o'] = t['STAGE'].map({k: i for i, k in enumerate(STAGES)})
        t = t.sort_values(['PRODUCT', '_o']).drop(columns='_o').reset_index(drop=True)
        t['STAGE'] = t['STAGE'].map(STAGE_LABEL)
        t.insert(2, 'UNIT', unit_label if isinstance(unit_label, str) else t['STAGE'].map(unit_label))
        return t
    fab = pivot(['FAB'], 'wafers')
    osat = pivot(['BUMP', 'SORT', 'ASSY', 'FT'], {'Bump': 'wafers', 'Wafer sort (CP)': 'wafers',
                                                   'Assembly': 'units', 'Final test': 'units'})
    tester = pd.DataFrame()
    if not testers.empty:
        t = testers.copy()
        t['m'] = t['MONTH'].dt.strftime('%Y-%m')
        tester = t.pivot_table(index=['TESTER_TYPE'], columns='m', values='hours_required', aggfunc='sum').reindex(
            columns=labels, fill_value=0).round(0).reset_index()
    calendar = pd.DataFrame([
        ('Working day 1-3', 'Planning', 'Refresh demand: actuals, customer forecasts, statistical forecast; review accuracy and bias.', 'Demand plan'),
        ('Working day 4', 'S&OP', 'Agree final demand, scenarios and safety stock with sales and finance.', 'Signed-off demand'),
        ('Working day 5', 'Planning', 'Run the module-level supply plan and tester capacity plan; resolve inside-lead-time and overload alerts.', 'Supply plan'),
        ('Working day 6', 'FAB', 'Send rolling wafer-start forecast (frozen month = firm order). Common standard: RosettaNet PIP 4A1 / 4A3, or Excel/CSV.', 'Fab forecast + PO for frozen month'),
        ('Working day 7', 'OSAT', 'Send rolling loading forecast by stage plus tester-hour demand; place work orders for the frozen month.', 'OSAT forecast + work orders'),
        ('Working day 10', 'FAB / OSAT', 'Suppliers return commits by month (PIP 4A5 forecast reply or commit sheet).', 'Supplier commits'),
        ('Working day 12', 'Planning', 'Compare commits with requests; escalate gaps in frozen and slushy months.', 'Gap list and escalations'),
        ('Daily', 'FAB / OSAT', 'Receive WIP (PIP 7B1) and shipment notices (PIP 3B2) and load them into Plan Yukta.', 'Daily WIP view'),
        ('Weekly', 'Planning', 'WIP review: late lots, duplicates, E&O, capacity flags; update expedites.', 'Weekly action list'),
    ], columns=['When', 'Owner', 'Activity', 'Output'])
    return {'fab': fab, 'osat': osat, 'tester': tester, 'zones': zone_row, 'calendar': calendar, 'labels': labels}


def b2b_workbook(pkg: dict, plan_info: dict) -> bytes:
    """Excel package to send each month: request tabs with commit columns and gap formulas."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head = PatternFill('solid', fgColor='1F3A5F')
    zone_fill = {'Frozen': PatternFill('solid', fgColor='F4CCCC'), 'Slushy': PatternFill('solid', fgColor='FFF2CC'),
                 'Liquid': PatternFill('solid', fgColor='D9EAD3')}
    commit_fill = PatternFill('solid', fgColor='FFF2CC')
    f = lambda **k: Font(**{'name': 'Arial', 'size': 10, **k})

    ws = wb.active
    ws.title = 'Cover'
    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 90
    lines = [('Plan Yukta monthly B2B package', ''), ('Plan start', plan_info['plan_start']),
             ('Horizon', f"{plan_info['horizon']} months"),
             ('Time fences', 'Frozen = firm order, no change; Slushy = change within agreed flex; Liquid = forecast only'),
             ('How to reply', 'Fill the yellow COMMIT rows in each request tab and return by working day 10. GAP rows calculate themselves.'),
             ('Tabs', 'Fab_Request, OSAT_Request, Tester_Hours, Monthly_Workflow')]
    for i, (a, b) in enumerate(lines, start=1):
        ws.cell(row=i, column=1, value=a).font = f(bold=True, size=14 if i == 1 else 10)
        ws.cell(row=i, column=2, value=b).font = f()

    def request_tab(name, df, labels):
        ws = wb.create_sheet(name)
        cols = ['PRODUCT', 'STAGE', 'UNIT', 'LINE'] + labels
        ws.append(['Time fence', '', '', ''] + [pkg['zones'][l] for l in labels])
        ws.append(cols)
        for c in range(1, len(cols) + 1):
            cell = ws.cell(row=2, column=c)
            cell.font = f(bold=True, color='FFFFFF'); cell.fill = head
            z = ws.cell(row=1, column=c)
            z.font = f(bold=True)
            if c > 4:
                z.fill = zone_fill[z.value]
        r = 3
        for _, row in df.iterrows():
            base = [row['PRODUCT'], row['STAGE'], row['UNIT']]
            ws.append(base + ['REQUEST'] + [int(row[l]) for l in labels])
            ws.append(base + ['COMMIT'] + [None for _ in labels])
            ws.append(base + ['GAP (commit - request)'] +
                      [f'=IF({get_column_letter(5 + i)}{r + 1}="","",{get_column_letter(5 + i)}{r + 1}-{get_column_letter(5 + i)}{r})'
                       for i in range(len(labels))])
            for i in range(len(labels)):
                ws.cell(row=r + 1, column=5 + i).fill = commit_fill
                ws.cell(row=r, column=5 + i).number_format = '#,##0'
                ws.cell(row=r + 2, column=5 + i).number_format = '#,##0;[Red]-#,##0'
            for rr in (r, r + 1, r + 2):
                for c in range(1, len(cols) + 1):
                    ws.cell(row=rr, column=c).font = f(bold=(rr == r))
            r += 3
        widths = [14, 18, 8, 22] + [11] * len(labels)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = 'E3'

    request_tab('Fab_Request', pkg['fab'], pkg['labels'])
    request_tab('OSAT_Request', pkg['osat'], pkg['labels'])

    ws = wb.create_sheet('Tester_Hours')
    ws.append(['TESTER_TYPE'] + pkg['labels'])
    for c in range(1, len(pkg['labels']) + 2):
        ws.cell(row=1, column=c).font = f(bold=True, color='FFFFFF'); ws.cell(row=1, column=c).fill = head
    for _, row in pkg['tester'].iterrows():
        ws.append([row['TESTER_TYPE']] + [float(row[l]) for l in pkg['labels']])
    ws.column_dimensions['A'].width = 18

    ws = wb.create_sheet('Monthly_Workflow')
    ws.append(list(pkg['calendar'].columns))
    for c in range(1, 5):
        ws.cell(row=1, column=c).font = f(bold=True, color='FFFFFF'); ws.cell(row=1, column=c).fill = head
    for row in pkg['calendar'].itertuples(index=False):
        ws.append(list(row))
    for col, w in zip('ABCD', (16, 12, 90, 32)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = f(); cell.alignment = Alignment(wrap_text=True, vertical='top')

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_planning(inputs: dict, visibility: dict | None, s: PlanSettings):
    final_demand, accuracy, demand_clean = forecast_demand(inputs['demand'], s)
    params = product_params(inputs['plan_params'], s.overrides)
    wip = {}
    if visibility is not None:
        for _, r in visibility['overview'].iterrows():
            wip[r['MASTER_PRODUCT']] = r.to_dict()
    plan, stages, alerts = supply_plan(final_demand, params, wip, s)
    testers, tester_detail = tester_plan(stages, params, inputs['tester_params'], inputs['tester_capacity'], s,
                                         s.overrides)
    pkg = b2b_package(stages, testers, s)
    for _, t in testers[testers['status'] == 'OVERLOADED'].iterrows():
        alerts.loc[len(alerts)] = [t['TESTER_TYPE'], t['MONTH'].strftime('%Y-%m'), 'Tester overload',
                                   f"{t['hours_required']:,.0f} h needed vs {t['hours_available']:,.0f} h available; "
                                   f"{t['testers_needed']} testers needed."]
    summary = []
    for prod, p in params.items():
        pl = plan[plan['PRODUCT'] == prod]
        st = stages[(stages['PRODUCT'] == prod) & (stages['STAGE'] == 'FAB')]
        summary.append({'PRODUCT': prod, 'demand_total': int(pl['demand'].sum()),
                        'units_per_wafer': round(p['units_per_wafer']),
                        'total_lead_time_wk': p['lt_total_wk'],
                        'wafer_starts_total': int(st['qty'].sum()),
                        'min_weeks_of_supply': pl['weeks_of_supply'].min() if not pl.empty else None,
                        'alerts': int((alerts['PRODUCT'] == prod).sum())})
    return {'settings': s, 'final_demand': final_demand, 'accuracy': accuracy, 'demand_history': demand_clean,
            'params': params, 'plan': plan, 'stages': stages, 'alerts': alerts, 'testers': testers,
            'tester_detail': tester_detail, 'b2b': pkg, 'summary': pd.DataFrame(summary)}


def settings_from_values(values: dict, default_start) -> PlanSettings:
    """Build PlanSettings from the workbook's Settings sheet (missing rows keep defaults)."""
    def num(key, default, lo, hi, cast=float):
        try:
            return cast(max(lo, min(hi, float(values.get(key, default)))))
        except (TypeError, ValueError):
            return cast(default)
    start = values.get('Plan start month')
    try:
        start = month_start(start).date() if start is not None else month_start(default_start).date()
    except Exception:
        start = month_start(default_start).date()
    method = str(values.get('Forecast method', 'BLEND')).strip().upper()
    return PlanSettings(
        plan_start=start,
        horizon_months=num('Horizon (months)', 12, 3, 18, int),
        frozen_months=num('Frozen months', 1, 0, 6, int),
        slushy_months=num('Slushy months', 3, 0, 12, int),
        forecast_method=method if method in ('BLEND', 'CUSTOMER', 'STAT') else 'BLEND',
        demand_uplift_pct=num('Demand uplift %', 0, -90, 300),
        alpha=num('Smoothing alpha', 0.35, 0.05, 0.95),
        beta=num('Smoothing beta', 0.15, 0.01, 0.9),
    )


def worked_example(params: dict, tester_params: pd.DataFrame, product: str, units: float, month) -> dict:
    """Trace one finished-goods requirement backwards through the modules, with every intermediate number."""
    p = params[product]
    m = month_start(month)
    ft_m = m - pd.DateOffset(months=wk_to_m(p['CT_FT_WK']))
    assy_m = m - pd.DateOffset(months=int(p['lt_back_m']))
    dies = units / (p['ASSY_YIELD'] * p['FT_YIELD'])
    ft_in = dies * p['ASSY_YIELD']
    wafers = dies / p['good_die_per_wafer']
    lots = math.ceil(wafers / p['WAFER_LOT'])
    wafers_r = lots * p['WAFER_LOT']
    wafer_m = assy_m - pd.DateOffset(months=int(p['lt_front_m']))
    sort_m = wafer_m + pd.DateOffset(months=wk_to_m(p['CT_FAB_WK'] + p['CT_BUMP_WK']))
    sort_wafers = wafers_r * p['FAB_LINE_YIELD']
    tp = tester_params.copy()
    tp.columns = [str(c).strip().upper() for c in tp.columns]
    tp = tp[tp['PRODUCT'].astype(str).str.strip() == product]
    ft_s, sort_s, ft_names, sort_names = 0.0, 0.0, [], []
    for _, r in tp.iterrows():
        ins = str(r['INSERTION']).upper()
        tt, idx, sites = float(r['TEST_TIME_S']), float(r.get('INDEX_TIME_S', 0) or 0), max(1.0, float(r['SITES']))
        if ins.startswith(('CP', 'WS')):
            step = _pct(r.get('STEPPING_EFF', 1) or 1)
            sort_s += math.ceil(p['GDW'] / sites) / step * (tt + idx) + float(r.get('WAFER_LOAD_S', 0) or 0)
            sort_names.append(ins)
        else:
            ft_s += (tt + idx) / sites
            ft_names.append(ins)
    return {
        'product': product, 'units': units, 'month': m, 'p': p,
        'ft_month': ft_m, 'assy_month': assy_m, 'wafer_month': wafer_m, 'sort_month': sort_m,
        'dies': dies, 'ft_in': ft_in, 'wafers': wafers, 'lots': lots, 'wafers_rounded': wafers_r,
        'surplus_die': wafers_r * p['good_die_per_wafer'] - dies, 'sort_wafers': sort_wafers,
        'ft_seconds': ft_s, 'ft_hours': ft_in * ft_s / 3600, 'ft_insertions': ', '.join(ft_names),
        'sort_seconds': sort_s, 'sort_hours': sort_wafers * sort_s / 3600, 'sort_insertions': ', '.join(sort_names),
    }
