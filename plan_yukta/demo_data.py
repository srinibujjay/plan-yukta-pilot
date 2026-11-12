"""
Synthetic demo data for the Plan Yukta pilot.

Everything here is invented: product names (ORION, VEGA, LYRA, ATLAS, NOVA),
vendors (OSAT-A/B/C), customers (Customer Alpha...), suppliers, lot numbers,
prices and volumes. Nothing comes from any real company. The numbers are set so
the demo shows the interesting cases: a tester crunch in the spring ramp that
pull-in partly covers, a substrate shortage, an NPI qualification risk, a
loss-making end-of-life product and a few held lots.
"""
from __future__ import annotations

import math

from .workspace import SETTINGS

PLAN_MONTHS = [f'{2026 + (10 + i) // 12}-{(10 + i) % 12 + 1:02d}' for i in range(12)]   # 2026-11 .. 2027-10
HIST_MONTHS = [f'{2024 + (10 + i) // 12}-{(10 + i) % 12 + 1:02d}' for i in range(24)]   # 2024-11 .. 2026-10

PRODUCTS = [
    # SKU, desc, pkg, status, gdpw, prio, strategy, ss_wk, pullin, sl, maxpull, wafer$, material, npi start, pull-in weight
    ('ORION', 'Power management IC', 'QFN-32', 'HVM', 9000, 8, 'FORECAST', 2, 'Y', 90, 60, 850, 'Leadframe', None, -0.05),
    ('VEGA', 'Sensor hub', 'WLCSP-25', 'HVM', 24000, 6, 'FORECAST', 2, 'Y', 80, 50, 760, 'None', None, -0.1),
    ('LYRA', 'Connectivity SoC', 'BGA-196', 'HVM', 7400, 9, 'BLEND', 3, 'Y', 100, 80, 980, 'Substrate', None, -0.08),
    ('ATLAS', 'Legacy driver IC', 'QFN-16', 'EOL', 9000, 2, 'ORDERS', 0, 'N', 0, 0, 700, 'Leadframe', None, 0.02),
    ('NOVA', 'Next-gen PMIC (new)', 'WLCSP-36', 'NPI', 9400, 7, 'FORECAST', 2, 'N', 80, 50, 1020, 'None', '2026-12-01', -0.02),
]

FLOWS = {   # operation: (yield, rework, cycle days)
    'ORION': [('Sort', .97, 0, 3), ('Bump', .99, 0, 4), ('Assembly', .985, 0, 6), ('Test1', .92, .06, 3), ('Test2', .97, .04, 2), ('Pack', .998, 0, 2)],
    'VEGA': [('Sort', .93, 0, 3), ('Bump', .985, 0, 4), ('Assembly', .99, 0, 4), ('Test1', .95, .05, 2), ('Pack', .998, 0, 2)],
    'LYRA': [('Sort', .90, 0, 3), ('Bump', .98, 0, 5), ('Assembly', .97, 0, 8), ('Test1', .88, .10, 4), ('Test2', .95, .06, 3), ('Pack', .995, 0, 2)],
    'ATLAS': [('Sort', .96, 0, 2), ('Assembly', .985, 0, 6), ('Test1', .94, .05, 2), ('Pack', .998, 0, 2)],
    'NOVA': [('Sort', .82, 0, 3), ('Bump', .97, 0, 4), ('Assembly', .97, 0, 5), ('Test1', .85, .12, 3), ('Pack', .995, 0, 2)],
}

BINS = {'ORION': [.90, .07, .03], 'VEGA': [.85, .10, .05], 'LYRA': [.80, .15, .05], 'ATLAS': [.95, .05], 'NOVA': [.75, .20, .05]}

FORECAST = {
    'ORION': [2400, 2500, 2600, 2600, 2800, 3300, 3500, 3500, 3200, 3000, 3000, 3000],
    'VEGA': [1800, 1850, 1900, 1900, 1950, 2050, 2150, 2200, 2200, 2150, 2100, 2100],
    'LYRA': [180, 200, 220, 240, 270, 330, 380, 420, 420, 400, 400, 400],
    'ATLAS': [200, 180, 160, 140, 120, 100, 80, 60, 40, 0, 0, 0],
    'NOVA': [0, 0, 0, 0, 0, 60, 120, 200, 300, 350, 400, 400],
}   # thousands of units

VENDORS = [('A', 'OSAT-A', 'North site', 40), ('B', 'OSAT-B', 'East site', 35), ('C', 'OSAT-C', 'South site', 25)]
QUALIFIED = {'ORION': 'ABC', 'VEGA': 'AB', 'LYRA': 'AC', 'ATLAS': 'B', 'NOVA': 'A'}

# step: (test s, sites, index s, oee, step eff, load s, cost consignee, cost non-consignee)
TEST = {
    ('ORION', 'Sort'): (12.0, 16, .6, .85, .95, 90, 18, 26), ('ORION', 'Test1'): (36, 8, 1.0, .85, None, None, .030, .066),
    ('ORION', 'Test2'): (20, 8, 1.0, .85, None, None, .018, .040),
    ('VEGA', 'Sort'): (6.0, 32, .5, .85, .95, 90, 22, 31), ('VEGA', 'Test1'): (14, 4, .8, .85, None, None, .015, .034),
    ('LYRA', 'Sort'): (15.0, 8, .8, .85, .93, 120, 34, 48), ('LYRA', 'Test1'): (55, 4, 1.2, .82, None, None, .085, .170),
    ('LYRA', 'Test2'): (30, 4, 1.2, .82, None, None, .045, .090),
    ('ATLAS', 'Sort'): (8.0, 16, .6, .85, .95, 90, 14, 20), ('ATLAS', 'Test1'): (12, 8, 1.0, .85, None, None, .012, .026),
    ('NOVA', 'Sort'): (14.0, 16, .6, .80, .94, 90, 24, 34), ('NOVA', 'Test1'): (45, 4, 1.0, .80, None, None, .070, .140),
}

FLEET = {   # (vendor, step): (model, consignee, non-consignee)
    ('A', 'Sort'): ('Prober P-200', 2, 1), ('A', 'Test1'): ('ATE T-700', 6, 2), ('A', 'Test2'): ('ATE T-700', 3, 1),
    ('B', 'Sort'): ('Prober P-200', 1, 1), ('B', 'Test1'): ('ATE T-700', 5, 2), ('B', 'Test2'): ('ATE T-500', 2, 1),
    ('C', 'Sort'): ('Prober P-100', 1, 1), ('C', 'Test1'): ('ATE T-500', 2, 2), ('C', 'Test2'): ('ATE T-500', 2, 0),
}

CUSTOMERS = ['Customer Alpha', 'Customer Beta', 'Customer Gamma', 'Customer Delta']


def _wave(i, amp=0.04, period=6.0, phase=0.0):
    return 1 + amp * math.sin(2 * math.pi * i / period + phase)


def build() -> dict:
    t = {}
    t['settings'] = [{'Setting': k, 'Value': v[1], 'Notes': v[2]} for k, v in SETTINGS.items()]
    t['products'] = [dict(SKU=p[0], Description=p[1], Package=p[2], Status=p[3], GDPW=p[4], Priority=p[5],
                          BuildStrategy=p[6], SafetyStockWeeks=p[7], PullIn=p[8], ServiceLevelPct=p[9],
                          MaxPullInPct=p[10], WaferPriceUSD=p[11], SubstrateType=p[12], NPIStartDate=p[13], PullInWeight=p[14])
                     for p in PRODUCTS]
    t['process_flow'] = [dict(SKU=s, Operation=op, Step=i + 1, Yield=y, ReworkRate=rw, CycleTimeDays=ct)
                         for s, flow in FLOWS.items() for i, (op, y, rw, ct) in enumerate(flow)]
    t['bin_splits'] = [dict(SKU=s, Bin=f'BIN_{i + 1}', Fraction=f) for s, fr in BINS.items() for i, f in enumerate(fr)]
    t['vendors'] = [dict(Vendor=v, Name=n, Region=r, SharePct=sh, Enabled='Y') for v, n, r, sh in VENDORS]

    t['forecast'] = [dict(Month=m, SKU=s, Units=int(q * 1000)) for s, qs in FORECAST.items()
                     for m, q in zip(PLAN_MONTHS, qs) if q > 0]

    # shipment history: trends with a little seasonality, deterministic
    t['shipment_history'] = []
    for i, m in enumerate(HIST_MONTHS):
        series = {'ORION': (1600 + 32 * i) * _wave(i, .05, 6, .3),
                  'VEGA': (1450 + 15 * i) * _wave(i, .07, 12, 1.1),
                  'LYRA': (15 + 14 * (i - 12)) * _wave(i, .06, 4) if i >= 12 else None,
                  'ATLAS': (460 - 9 * i) * _wave(i, .05, 5, 2.0)}
        for s, q in series.items():
            if q is not None:
                t['shipment_history'].append(dict(Month=m, SKU=s, Units=int(round(q)) * 1000))

    # orders: high coverage near term, falling away; ATLAS is order-driven
    orders, n = [], 1
    split = {'ORION': [('Customer Alpha', 'BIN_1', .48), ('Customer Beta', 'BIN_1', .30), ('Customer Beta', 'BIN_2', .05),
                       ('Customer Delta', 'BIN_3', .02)],
             'VEGA': [('Customer Alpha', 'BIN_1', .50), ('Customer Delta', 'BIN_1', .25), ('Customer Delta', 'BIN_3', .03)],
             'LYRA': [('Customer Gamma', 'BIN_1', .60), ('Customer Beta', 'BIN_1', .25), ('Customer Gamma', 'BIN_2', .08)],
             'ATLAS': [('Customer Gamma', 'BIN_1', .92), ('Customer Gamma', 'BIN_2', .04)]}
    coverage = [1.0, .95, .80, .60, .40, .25]
    atlas_orders = [190, 175, 160, 135, 110, 90, 70, 0]
    for s, parts in split.items():
        for mi, m in enumerate(PLAN_MONTHS[:8]):
            base = FORECAST[s][mi] * 1000
            cov = coverage[mi] if mi < len(coverage) else 0
            if s == 'ATLAS':
                base, cov = atlas_orders[mi] * 1000, 1.0
            for ci, (cust, b, share) in enumerate(parts):
                qty = int(round(base * cov * share / 1000.0)) * 1000
                if qty <= 0:
                    continue
                day = 10 + (ci * 5) % 18
                orders.append(dict(OrderID=f'SO-{26000 + n}', Customer=cust, SKU=s, Bin=b, Month=m,
                                   CRD=f'{m}-{day:02d}', Qty=qty, Status='Confirmed' if mi < 3 else 'Open'))
                n += 1
    t['orders'] = orders

    t['customer_bins'] = [
        dict(Customer='Customer Alpha', SKU='ORION', Bin='BIN_1', MOQ=3000),
        dict(Customer='Customer Alpha', SKU='VEGA', Bin='BIN_1', MOQ=5000),
        dict(Customer='Customer Alpha', SKU='LYRA', Bin='BIN_1', MOQ=1000),
        dict(Customer='Customer Beta', SKU='ORION', Bin='BIN_1', MOQ=3000),
        dict(Customer='Customer Beta', SKU='ORION', Bin='BIN_2', MOQ=3000),
        dict(Customer='Customer Beta', SKU='LYRA', Bin='BIN_1', MOQ=1000),
        dict(Customer='Customer Gamma', SKU='LYRA', Bin='BIN_1', MOQ=1000),
        dict(Customer='Customer Gamma', SKU='LYRA', Bin='BIN_2', MOQ=1000),
        dict(Customer='Customer Gamma', SKU='ATLAS', Bin='BIN_1', MOQ=2500),
        dict(Customer='Customer Gamma', SKU='ATLAS', Bin='BIN_2', MOQ=2500),
        dict(Customer='Customer Delta', SKU='ORION', Bin='BIN_3', MOQ=2000),
        dict(Customer='Customer Delta', SKU='VEGA', Bin='BIN_1', MOQ=5000),
        dict(Customer='Customer Delta', SKU='VEGA', Bin='BIN_3', MOQ=5000),
        dict(Customer='Customer Delta', SKU='NOVA', Bin='BIN_1', MOQ=2000),
        dict(Customer='Customer Alpha', SKU='NOVA', Bin='BIN_1', MOQ=2000),
    ]
    t['pricing'] = [
        dict(SKU='ORION', Customer='*', ASPUSD=0.62), dict(SKU='ORION', Customer='Customer Alpha', ASPUSD=0.58),
        dict(SKU='ORION', Customer='Customer Delta', ASPUSD=0.41),
        dict(SKU='VEGA', Customer='*', ASPUSD=0.21), dict(SKU='VEGA', Customer='Customer Alpha', ASPUSD=0.19),
        dict(SKU='LYRA', Customer='*', ASPUSD=1.60), dict(SKU='LYRA', Customer='Customer Gamma', ASPUSD=1.52),
        dict(SKU='ATLAS', Customer='*', ASPUSD=0.14),
        dict(SKU='NOVA', Customer='*', ASPUSD=0.55),
    ]
    t['reservations'] = [
        dict(SalesOrder='RS-1001', Customer='Customer Alpha', CustomerPO='CPO-A-7701', SKU='ORION', Vendor='A', Bin='BIN_1',
             Qty=420000, CRD='2026-11-12', SSD='2026-11-12', Status='Reserved'),
        dict(SalesOrder='RS-1002', Customer='Customer Beta', CustomerPO='CPO-B-5520', SKU='ORION', Vendor='B', Bin='BIN_1',
             Qty=300000, CRD='2026-11-17', SSD='2026-11-17', Status='Reserved'),
        dict(SalesOrder='RS-1003', Customer='Customer Alpha', CustomerPO='CPO-A-7702', SKU='VEGA', Vendor='A', Bin='BIN_1',
             Qty=500000, CRD='2026-11-12', SSD='2026-11-14', Status='Reserved'),
        dict(SalesOrder='RS-1004', Customer='Customer Gamma', CustomerPO='CPO-G-3301', SKU='LYRA', Vendor='A', Bin='BIN_1',
             Qty=60000, CRD='2026-11-20', SSD='2026-11-20', Status='Reserved'),
        dict(SalesOrder='RS-1005', Customer='Customer Gamma', CustomerPO='CPO-G-3290', SKU='ATLAS', Vendor='B', Bin='BIN_1',
             Qty=90000, CRD='2026-11-08', SSD='2026-11-08', Status='Reserved'),
        dict(SalesOrder='RS-0998', Customer='Customer Delta', CustomerPO='CPO-D-1180', SKU='VEGA', Vendor='B', Bin='BIN_3',
             Qty=40000, CRD='2026-10-28', SSD='2026-10-30', Status='Shipped'),
    ]

    t['tester_fleet'] = [dict(Vendor=v, Step=st, TesterModel=m, Consignee=c, NonConsignee=nc, HoursPerDay=24)
                         for (v, st), (m, c, nc) in FLEET.items()]
    t['fleet_changes'] = [
        dict(Month='2027-02', Vendor='C', Step='Test1', ConsigneeChange=0, NonConsigneeChange=1, Reason='Short-term rental agreed with OSAT-C'),
        dict(Month='2027-07', Vendor='A', Step='Test1', ConsigneeChange=2, NonConsigneeChange=0, Reason='Two new consignee testers installed'),
        dict(Month='2027-09', Vendor='B', Step='Test2', ConsigneeChange=-1, NonConsigneeChange=0, Reason='Tester transferred to another program'),
    ]
    cap = []
    for s, vends in QUALIFIED.items():
        steps = [op for op, *_ in FLOWS[s] if op in ('Sort', 'Test1', 'Test2')]
        for v in vends:
            for st in steps:
                tt, sites, idx, oee, se, load, cc, cn = TEST[(s, st)]
                bump = {'A': 1.0, 'B': 1.04, 'C': 0.97}[v]
                cap.append(dict(Vendor=v, SKU=s, Step=st, TestTimeSec=tt, Sites=sites, IndexTimeSec=idx,
                                OEE=round(oee - (0.03 if v == 'C' else 0), 2), StepEff=se, WaferLoadSec=load,
                                CostConsigneeUSD=round(cc * bump, 4), CostNonConsigneeUSD=round(cn * bump, 4)))
    t['tester_capacity'] = cap
    t['yield_overrides'] = [
        dict(SKU='ORION', Vendor='A', Operation='Test1', EffectiveMonth='2027-01', Yield=.94, ReworkRate=.05,
             Note='Yield improvement plan: new test program release'),
        dict(SKU='LYRA', Vendor='C', Operation='Test1', EffectiveMonth='2026-12', Yield=.84, ReworkRate=.12,
             Note='Excursion containment: extra screen at OSAT-C'),
    ]
    hw = []
    for (v, st), (m, c, nc) in FLEET.items():
        if st == 'Sort':
            hw.append(dict(Vendor=v, Step=st, HardwareType='Probe card', PerTester=1, InService=c))
            continue
        hw.append(dict(Vendor=v, Step=st, HardwareType='Socket kit', PerTester=8, InService=8 * c))
        hw.append(dict(Vendor=v, Step=st, HardwareType='Load board', PerTester=1, InService=c))
        hw.append(dict(Vendor=v, Step=st, HardwareType='Instrument card', PerTester=4, InService=4 * c))
    for r in hw:
        if (r['Vendor'], r['Step'], r['HardwareType']) == ('A', 'Test1', 'Instrument card'):
            r['InService'] = 22                       # only 5 full kits until more cards arrive
        if (r['Vendor'], r['Step'], r['HardwareType']) == ('C', 'Test1', 'Load board'):
            r['InService'] = 1                        # one load board out for repair
    t['hardware'] = hw
    t['hardware_arrivals'] = [
        dict(Month='2027-01', Vendor='C', Step='Test1', HardwareType='Load board', Qty=1, Note='Repaired load board returns'),
        dict(Month='2027-02', Vendor='A', Step='Test1', HardwareType='Instrument card', Qty=10, Note='Instrument cards on PO'),
        dict(Month='2027-06', Vendor='A', Step='Test1', HardwareType='Socket kit', Qty=16, Note='Kits for the two new testers'),
        dict(Month='2027-06', Vendor='A', Step='Test1', HardwareType='Load board', Qty=2, Note='Kits for the two new testers'),
    ]
    t['capacity_overrides'] = [
        dict(Vendor='A', SKU='ORION', Step='Test1', EffectiveMonth='2027-05', TestTimeSec=32, Sites=None, IndexTimeSec=None, OEE=None,
             Note='Test-time reduction: new test program release'),
        dict(Vendor='B', SKU='VEGA', Step='Test1', EffectiveMonth='2027-06', TestTimeSec=None, Sites=8, IndexTimeSec=1.0, OEE=None,
             Note='Octal-site handler upgrade'),
        dict(Vendor='C', SKU='ORION', Step='Test1', EffectiveMonth='2027-03', TestTimeSec=None, Sites=None, IndexTimeSec=None, OEE=0.86,
             Note='OEE improvement plan at OSAT-C'),
    ]

    # ---------------- OSAT WIP snapshot, in each vendor's own codes ----------------
    pcode = {'A': {'ORION': 'ORN-A0', 'VEGA': 'VGA-A0', 'LYRA': 'LYR-A0', 'NOVA': 'NOV-A0'},
             'B': {'ORION': 'OR9000B', 'VEGA': 'VG2400B', 'ATLAS': 'AT9000B'},
             'C': {'ORION': 'PRD_ORION_C', 'LYRA': 'PRD_LYRA_C'}}
    ocode = {'A': ['CP', 'BUMP', 'DBANK', 'ASSY', 'FT1', 'FT2', 'PACK', 'FGS'],
             'B': ['Wafer Sort', 'Bumping', 'Die Bank', 'Assembly', 'Final Test 1', 'Final Test 2', 'Packing', 'Finished Goods'],
             'C': ['SORT1', 'BUMP1', 'DIEBANK', 'ASM', 'TEST1', 'TEST2', 'PACKLINE', 'WAREHOUSE']}
    std = ['Sort', 'Bump', 'DieBank', 'Assembly', 'Test1', 'Test2', 'Pack', 'FG']
    t['product_codes'] = [dict(Vendor=v, VendorProduct=c, SKU=s) for v, d in pcode.items() for s, c in d.items()]
    t['operation_codes'] = [dict(Vendor=v, VendorOperation=o, Operation=std[i]) for v, ops in ocode.items() for i, o in enumerate(ops)]
    # (sku, vendor): wafers at Sort, Bump, DieBank ; units (k) at Assembly, Test1, Test2, Pack, FG
    wip_plan = {
        ('ORION', 'A'): (50, 25, 50, 300, 450, 300, 120, 520), ('ORION', 'B'): (50, 25, 25, 250, 380, 260, 100, 430),
        ('ORION', 'C'): (25, 25, 25, 175, 260, 180, 60, 300),
        ('VEGA', 'A'): (25, 25, 0, 250, 300, 0, 120, 600), ('VEGA', 'B'): (25, 0, 25, 220, 260, 0, 90, 480),
        ('LYRA', 'A'): (12, 12, 13, 40, 60, 30, 20, 90), ('LYRA', 'C'): (12, 13, 0, 25, 40, 20, 10, 55),
        ('ATLAS', 'B'): (25, 0, 0, 60, 90, 0, 30, 140),
        ('NOVA', 'A'): (0, 0, 0, 0, 0, 0, 0, 0),
    }
    lots, seq = [], {'A': 1, 'B': 1, 'C': 1}
    holds = {('ORION', 'B', 'Test1'): 'Yield excursion at final test 1: engineering review',
             ('LYRA', 'C', 'Assembly'): 'Substrate warpage: supplier deviation pending',
             ('VEGA', 'A', 'FG'): 'Customer label change: awaiting approval'}
    datecodes = ['2641', '2642', '2643', '2644', '2645']
    for (s, v), qty in wip_plan.items():
        flow_ops = {op for op, *_ in FLOWS[s]} | {'DieBank', 'FG'}
        for i, op in enumerate(std):
            q = qty[i]
            if q <= 0 or (op not in flow_ops) or (op == 'Test2' and 'Test2' not in flow_ops) or (op == 'Bump' and 'Bump' not in flow_ops):
                continue
            if i < 3:   # wafer stages: 25-wafer lots, last lot may be partial
                pieces = [25] * (q // 25) + ([q % 25] if q % 25 else [])
            else:
                total = q * 1000
                n_lots = max(1, round(total / 90000))
                base = total // n_lots
                pieces = [base] * (n_lots - 1) + [total - base * (n_lots - 1)]
            for j, p in enumerate(pieces):
                lot = f'PY{v}{seq[v]:04d}'
                seq[v] += 1
                state = 'DONE' if op in ('DieBank', 'FG') else ('RUN' if j % 2 == 0 else 'WAIT')
                hold = holds.get((s, v, op)) if j == 0 else None
                row = dict(Vendor=v, LotID=lot, VendorProduct=pcode[v][s], VendorOperation=ocode[v][i],
                           State='HOLD' if hold else state, HoldReason=hold, DateCode=datecodes[(j + i) % 5])
                if i < 3:
                    row.update(Wafers=p, Units=None, Bin=None)
                elif op == 'FG':
                    fr = BINS[s]
                    for b, f in enumerate(fr):
                        part = int(round(p * f / 100.0)) * 100
                        if part <= 0:
                            continue
                        r2 = dict(row, LotID=f'{lot}{chr(65 + b)}', Units=part, Wafers=None, Bin=f'BIN_{b + 1}')
                        if b > 0:
                            r2.update(State='DONE', HoldReason=None)
                        lots.append(r2)
                    continue
                else:
                    row.update(Wafers=round(p / (FORECAST_GDPW[s])) or None, Units=p, Bin=None)
                lots.append(row)
    # one lot booked under a product code nobody mapped, to show the data check
    lots.append(dict(Vendor='B', LotID=f'PYB{seq["B"]:04d}', VendorProduct='OR9000B-ENG', VendorOperation='Final Test 1',
                     State='WAIT', Wafers=None, Units=24000, Bin=None, HoldReason=None, DateCode='2644'))
    # aged ATLAS finished goods from a cancelled program (date code early 2025): excess and obsolete-risk story
    for j, (q, dc) in enumerate([(240000, '2507'), (180000, '2511'), (150000, '2602')]):
        lots.append(dict(Vendor='B', LotID=f'PYB{seq["B"] + 1 + j:04d}', VendorProduct='AT9000B', VendorOperation='Finished Goods',
                         State='DONE', Wafers=None, Units=q, Bin='BIN_1', HoldReason=None, DateCode=dc))
    t['osat_wip'] = lots

    fab = []
    fab_plan = {'ORION': [('2026-11-12', 4), ('2026-11-26', 4), ('2026-12-10', 5), ('2026-12-24', 4), ('2027-01-07', 6), ('2027-01-21', 5)],
                'VEGA': [('2026-11-19', 2), ('2026-12-10', 3), ('2027-01-14', 3)],
                'LYRA': [('2026-11-20', 2), ('2027-01-08', 2)],
                'ATLAS': [('2026-12-03', 1)]}
    k = 1
    for s, items in fab_plan.items():
        for out, nlots in items:
            for _ in range(nlots):
                y, mth, d = (int(x) for x in out.split('-'))
                start_m = mth - 3 if mth > 3 else mth + 9
                start_y = y if mth > 3 else y - 1
                fab.append(dict(LotID=f'PYF{k:04d}', SKU=s, Wafers=25,
                                Stage=['Front-end', 'Metal 1', 'Metal 3', 'Passivation'][k % 4],
                                StartDate=f'{start_y}-{start_m:02d}-{d:02d}', ExpectedOutDate=out))
                k += 1
    t['fab_wip'] = fab

    t['substrates'] = [
        dict(SKU='ORION', Vendor='A', Supplier='Leadframe Supplier L1', ArrivalMonth='2026-10', Units=2500000, ExpiryMonth='2027-10', Consigned='N'),
        dict(SKU='ORION', Vendor='A', Supplier='Leadframe Supplier L1', ArrivalMonth='2027-01', Units=4000000, ExpiryMonth='2028-01', Consigned='N'),
        dict(SKU='ORION', Vendor='A', Supplier='Leadframe Supplier L1', ArrivalMonth='2027-04', Units=5500000, ExpiryMonth='2028-04', Consigned='N'),
        dict(SKU='ORION', Vendor='A', Supplier='Leadframe Supplier L1', ArrivalMonth='2027-07', Units=5000000, ExpiryMonth='2028-07', Consigned='N'),
        dict(SKU='ORION', Vendor='B', Supplier='Leadframe Supplier L2', ArrivalMonth='2026-10', Units=2200000, ExpiryMonth='2027-10', Consigned='N'),
        dict(SKU='ORION', Vendor='B', Supplier='Leadframe Supplier L2', ArrivalMonth='2027-01', Units=3600000, ExpiryMonth='2028-01', Consigned='N'),
        dict(SKU='ORION', Vendor='B', Supplier='Leadframe Supplier L2', ArrivalMonth='2027-04', Units=4800000, ExpiryMonth='2028-04', Consigned='N'),
        dict(SKU='ORION', Vendor='B', Supplier='Leadframe Supplier L2', ArrivalMonth='2027-07', Units=4500000, ExpiryMonth='2028-07', Consigned='N'),
        dict(SKU='ORION', Vendor='C', Supplier='Leadframe Supplier L1', ArrivalMonth='2026-10', Units=1600000, ExpiryMonth='2027-10', Consigned='N'),
        dict(SKU='ORION', Vendor='C', Supplier='Leadframe Supplier L1', ArrivalMonth='2027-01', Units=2600000, ExpiryMonth='2028-01', Consigned='N'),
        dict(SKU='ORION', Vendor='C', Supplier='Leadframe Supplier L1', ArrivalMonth='2027-04', Units=3400000, ExpiryMonth='2028-04', Consigned='N'),
        dict(SKU='ORION', Vendor='C', Supplier='Leadframe Supplier L1', ArrivalMonth='2027-07', Units=3200000, ExpiryMonth='2028-07', Consigned='N'),
        dict(SKU='LYRA', Vendor='A', Supplier='Substrate Supplier S1', ArrivalMonth='2026-09', Units=60000, ExpiryMonth='2026-12', Consigned='Y'),
        dict(SKU='LYRA', Vendor='A', Supplier='Substrate Supplier S1', ArrivalMonth='2026-11', Units=700000, ExpiryMonth='2027-08', Consigned='Y'),
        dict(SKU='LYRA', Vendor='A', Supplier='Substrate Supplier S2', ArrivalMonth='2027-03', Units=1600000, ExpiryMonth='2027-12', Consigned='Y'),
        dict(SKU='LYRA', Vendor='C', Supplier='Substrate Supplier S2', ArrivalMonth='2026-11', Units=340000, ExpiryMonth='2027-08', Consigned='Y'),
        dict(SKU='LYRA', Vendor='C', Supplier='Substrate Supplier S2', ArrivalMonth='2027-03', Units=900000, ExpiryMonth='2027-12', Consigned='Y'),
        dict(SKU='ATLAS', Vendor='B', Supplier='Leadframe Supplier L2', ArrivalMonth='2026-08', Units=900000, ExpiryMonth='2027-08', Consigned='N'),
    ]
    t['osat_costs'] = []
    for v, mult in (('A', 1.0), ('B', 0.96), ('C', 1.05)):
        t['osat_costs'] += [
            dict(Vendor=v, Operation='Bump', SKU='*', Unit='wafer', CostUSD=round(95 * mult, 2)),
            dict(Vendor=v, Operation='Assembly', SKU='ORION', Unit='unit', CostUSD=round(.040 * mult, 4)),
            dict(Vendor=v, Operation='Assembly', SKU='VEGA', Unit='unit', CostUSD=round(.012 * mult, 4)),
            dict(Vendor=v, Operation='Assembly', SKU='LYRA', Unit='unit', CostUSD=round(.28 * mult, 4)),
            dict(Vendor=v, Operation='Assembly', SKU='ATLAS', Unit='unit', CostUSD=round(.038 * mult, 4)),
            dict(Vendor=v, Operation='Assembly', SKU='NOVA', Unit='unit', CostUSD=round(.014 * mult, 4)),
            dict(Vendor=v, Operation='Pack', SKU='*', Unit='unit', CostUSD=round(.004 * mult, 4)),
        ]
    t['cross_flow'] = [
        dict(SKU='ORION', AfterOperation='Assembly', FromVendor='A', ToVendor='B', Percent=15, TransitDays=2, CostPer1000USD=4.5, Status='Active'),
        dict(SKU='LYRA', AfterOperation='Test1', FromVendor='C', ToVendor='A', Percent=20, TransitDays=3, CostPer1000USD=9.0, Status='Active'),
        dict(SKU='ORION', AfterOperation='Bump', FromVendor='C', ToVendor='A', Percent=10, TransitDays=3, CostPer1000USD=120.0, Status='Inactive'),
    ]
    t['npi_milestones'] = [dict(SKU='NOVA', Milestone=m, Order=i + 1, CycleDays=c, ReadoutDays=r) for i, (m, c, r) in enumerate([
        ('Preconditioning (MSL3)', 5, 0), ('HAST 96 h', 7, 2), ('Temperature cycling 500 cycles', 10, 2),
        ('Temperature cycling 1000 cycles', 10, 2), ('HTSL 500 h', 21, 2), ('HTOL 168 h', 7, 2), ('HTOL 500 h', 14, 2),
        ('HTOL 1000 h', 21, 3), ('ESD and latch-up', 5, 2), ('Solderability', 3, 2)])]

    # ---------------- frozen plan and actuals for Aug-Oct 2026 ----------------
    snap, act = [], []
    past = ['2026-08', '2026-09', '2026-10']
    base_k = {'ORION': 2250, 'VEGA': 1780, 'LYRA': 160, 'ATLAS': 240}
    shares = {'ORION': {'A': .40, 'B': .35, 'C': .25}, 'VEGA': {'A': .533, 'B': .467}, 'LYRA': {'A': .615, 'C': .385}, 'ATLAS': {'B': 1.0}}
    events = {('2026-08', 'A', 'ORION', 'Test1'): ('Yield excursion', 4, 0.86),
              ('2026-09', 'B', 'ORION', 'Test1'): ('Tester down', 3, 0.89), ('2026-09', 'B', 'VEGA', 'Test1'): ('Tester down', 3, 0.91),
              ('2026-10', 'C', 'LYRA', 'Test1'): ('Material shortage', 6, 0.78), ('2026-10', 'C', 'LYRA', 'Pack'): ('Material shortage', 6, 0.80),
              ('2026-10', 'B', 'ATLAS', 'Pack'): ('Hold', 2, 0.93)}
    for mi, m in enumerate(past):
        for s, sh in shares.items():
            for v, f in sh.items():
                for op in ('Test1', 'Pack'):
                    planned = int(round(base_k[s] * f * (1 + .03 * mi) * (1.06 if op == 'Test1' else 1.0))) * 1000
                    snap.append(dict(Month=m, Vendor=v, SKU=s, Operation=op, PlannedUnits=planned))
                    ev = events.get((m, v, s, op))
                    att = ev[2] if ev else 0.97 + 0.02 * math.sin(mi + len(v) + len(s))
                    avail = 0.93 - (ev[1] * 0.025 if ev else 0) + 0.01 * math.cos(mi + len(s))
                    perf = 0.95 + 0.015 * math.sin(len(s) + mi)
                    qual = 0.985 - (0.06 if ev and ev[0] == 'Yield excursion' else 0)
                    act.append(dict(Month=m, Vendor=v, SKU=s, Operation=op, ActualUnits=int(round(planned * att / 1000.0)) * 1000,
                                    AvailabilityPct=round(avail * 100, 1), PerformancePct=round(perf * 100, 1),
                                    QualityPct=round(qual * 100, 1), DisruptionDays=ev[1] if ev else 0,
                                    Disruption=ev[0] if ev else 'None'))
    t['plan_snapshot'] = snap
    t['actuals'] = act
    t['vendor_issues'] = _issues()
    t['qbr_weights'] = [
        dict(Category='Quality', WeightPct=30, Target=99.5, Notes='Average of test yield vs plan and reported quality %. 99.5 or better = full marks.'),
        dict(Category='Delivery', WeightPct=30, Target=98, Notes='Output attainment vs the frozen plan, %.'),
        dict(Category='Cost', WeightPct=15, Target=100, Notes='Price index: 100 = lowest price among OSATs for the same work.'),
        dict(Category='Capacity', WeightPct=15, Target=99.9, Notes='Share of the forward test load the OSAT can make on time, %.'),
        dict(Category='Responsiveness', WeightPct=10, Target=14, Notes='Average days to close an issue; at or under target = full marks. Overdue and open critical issues cost points.'),
    ]
    t['order_history'] = _order_history()
    t['test_results'], t['test_bins'] = _test_data()
    return t


def _issues():
    rows = [
        ('VI-0101', 'A', '2026-08-06', 'Quality', 'Critical', 'ORION final test 1 yield excursion: contact resistance', 'ORION', 'OSAT-A quality', '2026-08-20', 'Closed', '2026-08-18',
         'Worn pogo pins on two handlers', 'Pin replacement on all T-700 handlers; contact check added to daily PM'),
        ('VI-0102', 'B', '2026-09-09', 'Delivery', 'Major', 'Final test 1 tester down 3 days (power supply)', 'ORION', 'OSAT-B ops', '2026-09-16', 'Closed', '2026-09-14',
         'Instrument power supply failure', 'Spare supply stocked on site'),
        ('VI-0103', 'C', '2026-10-05', 'Delivery', 'Major', 'LYRA assembly stopped: substrate shortage', 'LYRA', 'Supply planning', '2026-10-20', 'Closed', '2026-10-24',
         'Late substrate delivery from supplier S2', 'Two-week buffer stock agreed'),
        ('VI-0104', 'C', '2026-10-21', 'Quality', 'Major', 'LYRA substrate warpage: lots on hold', 'LYRA', 'OSAT-C quality', '2026-11-04', 'Open', None,
         'Under investigation', 'Supplier deviation request raised'),
        ('VI-0105', 'C', '2026-09-30', 'Communication', 'Minor', 'Daily WIP report arriving after 10:00', None, 'OSAT-C planner', '2026-10-15', 'Open', None, None,
         'Automate the report export'),
        ('VI-0106', 'B', '2026-10-28', 'Quality', 'Major', 'ORION lot on hold after final test 1 yield drop', 'ORION', 'OSAT-B quality', '2026-11-11', 'In progress', None,
         'Suspected probe-card wear at sort', 'Engineering review of sort data'),
        ('VI-0107', 'A', '2026-10-12', 'Cost', 'Minor', 'Assembly price increase request (+4%)', None, 'Procurement', '2026-11-30', 'Open', None, None,
         'Negotiate against volume ramp'),
        ('VI-0108', 'FAB', '2026-08-25', 'Delivery', 'Major', 'Wafer outs one week late on two VEGA lots', 'VEGA', 'Foundry manager', '2026-09-05', 'Closed', '2026-09-03',
         'Litho tool down at the foundry', 'Foundry moved lots to a backup tool'),
        ('VI-0109', 'A', '2026-07-14', 'Delivery', 'Minor', 'Packing labels wrong on one shipment', 'VEGA', 'OSAT-A logistics', '2026-07-21', 'Closed', '2026-07-17',
         'Template not updated', 'Label template locked in MES'),
        ('VI-0110', 'B', '2026-07-22', 'Capacity', 'Minor', 'Second final-test shift not staffed in August', None, 'OSAT-B ops', '2026-08-01', 'Closed', '2026-08-05',
         'Hiring delay', 'Temporary staff from another line'),
        ('VI-0111', 'A', '2026-11-02', 'Capacity', 'Major', 'Instrument cards for the 6th tester not yet delivered', 'ORION', 'Test engineering', '2026-12-15', 'Open', None, None,
         'Cards on PO, due February; plan uses non-consignee time'),
        ('VI-0112', 'C', '2026-08-18', 'Quality', 'Minor', 'Marking smudge on LYRA trays', 'LYRA', 'OSAT-C quality', '2026-08-30', 'Closed', '2026-09-12',
         'Ink viscosity', 'Ink change and inspection step'),
    ]
    keys = ['IssueID', 'Vendor', 'Opened', 'Category', 'Severity', 'Title', 'SKU', 'Owner', 'Due', 'Status', 'Closed', 'RootCause', 'Action']
    return [dict(zip(keys, r)) for r in rows]


def _order_history():
    months = ['2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10']
    plan = {   # customer: list of (sku, qty k) per month, and the behaviour pattern by month index
        'Customer Alpha': ([('ORION', 1100), ('VEGA', 900)], {}),
        'Customer Beta': ([('ORION', 700), ('LYRA', 40)], {1: ('Pushed out', 1, None, 'End-customer launch slipped'),
                                                           3: ('Pushed out', 1, None, 'Inventory correction'),
                                                           4: ('Reduced', 0, .7, 'Lower sell-through')}),
        'Customer Gamma': ([('LYRA', 110), ('ATLAS', 200)], {2: ('Cancelled', 0, 0, 'Platform end of life'),
                                                             4: ('Reduced', 0, .6, 'EOL last-time-buy smaller than agreed'),
                                                             5: ('Pushed out', 1, None, 'Line move at their factory')}),
        'Customer Delta': ([('VEGA', 450), ('ORION', 50)], {0: ('Pulled in', -1, None, 'Asked for earlier delivery'),
                                                            3: ('Pulled in', -1, None, 'Promotion build'),
                                                            5: ('Reduced', 0, .6, 'Promotion ended early')}),
    }
    rows, n = [], 1
    for cust, (items, pattern) in plan.items():
        for mi, m in enumerate(months):
            for si, (sku, q) in enumerate(items):
                qty = int(q * 1000 * (1 + 0.03 * ((mi + si) % 3)))
                out, shift, frac, why = ('Accepted', 0, None, None)
                if mi in pattern:
                    out, shift, frac, why = pattern[mi]
                y, mm = int(m[:4]), int(m[5:])
                t = y * 12 + mm - 1 + shift
                actual_m = f'{t // 12}-{t % 12 + 1:02d}' if out != 'Cancelled' else None
                aq = 0 if out == 'Cancelled' else (int(qty * frac) if frac else qty)
                rows.append(dict(OrderID=f'AO-{25000 + n}', Customer=cust, SKU=sku, AgreedMonth=m, AgreedQty=qty, Outcome=out,
                                 ActualMonth=actual_m, ActualQty=aq, Reason=why))
                n += 1
    return rows


def _test_data():
    """Lot-level test results Jun-Oct 2026 for the OSATs' sort and final test, with two real stories:
    an ORION Test1 yield excursion at OSAT-A in August (contact failures) and a weak tester at OSAT-B."""
    import random
    rnd = random.Random(42)
    testers = {'A': [f'T7-A0{i}' for i in range(1, 9)], 'B': [f'T7-B0{i}' for i in range(1, 8)], 'C': [f'T5-C0{i}' for i in range(1, 5)]}
    fail_bins = [('HB5', 'Continuity / open-short'), ('HB6', 'Leakage'), ('HB7', 'Functional'), ('HB8', 'Parametric Idd / Vdd'), ('HB9', 'Retest limit')]
    base_mix = [0.22, 0.18, 0.30, 0.22, 0.08]
    results, bins = [], []
    lot_no = 1
    days = [f'2026-{m:02d}-{d:02d}' for m in (6, 7, 8, 9, 10) for d in (3, 10, 17, 24)]
    for sku, vends in QUALIFIED.items():
        if sku == 'NOVA':
            continue
        flow = {op: (y, rw) for op, y, rw, ct in FLOWS[sku]}
        for v in vends:
            for di, day in enumerate(days):
                if sku == 'ATLAS' and di % 2:
                    continue
                lot = f'PYT{lot_no:05d}'
                lot_no += 1
                for step in ('Sort', 'Test1', 'Test2'):
                    if step not in flow:
                        continue
                    y = flow[step][0]
                    if sku == 'LYRA' and v == 'C' and step == 'Test1' and day >= '2026-10-01':
                        y = 0.84
                    excursion = sku == 'ORION' and v == 'A' and step == 'Test1' and '2026-08-03' <= day <= '2026-08-17'
                    if excursion:
                        y = 0.855
                    tester = testers[v][di % len(testers[v])]
                    if v == 'B' and tester == 'T7-B05' and step != 'Sort':
                        y -= 0.025
                    y = max(0.5, min(0.995, y + rnd.gauss(0, 0.008 if step != 'Sort' else 0.012)))
                    if step == 'Sort':
                        tested = 25 * FORECAST_GDPW[sku]
                    else:
                        tested = int(rnd.choice([80000, 90000, 100000]) if sku != 'LYRA' else rnd.choice([20000, 24000]))
                    passed = int(round(tested * y))
                    results.append(dict(TestDate=day, Vendor=v, SKU=sku, Step=step, LotID=lot, WaferID='-',
                                        TesterID=tester if step != 'Sort' else f'PR-{v}0{1 + di % 2}', Tested=tested, Passed=passed))
                    if step == 'Test1':
                        fr = BINS[sku]
                        left = passed
                        for bi, f in enumerate(fr):
                            c = left if bi == len(fr) - 1 else int(round(passed * f))
                            left -= c
                            bins.append(dict(Step=step, LotID=lot, Bin=f'BIN_{bi + 1}', Count=c, Pass='Y', Description=f'Grade {bi + 1}'))
                        fails = tested - passed
                        mix = list(base_mix)
                        if excursion:
                            mix = [0.62, 0.10, 0.14, 0.10, 0.04]
                        left = fails
                        for k, ((b, desc), f) in enumerate(zip(fail_bins, mix)):
                            c = left if k == len(mix) - 1 else int(round(fails * f))
                            left -= c
                            bins.append(dict(Step=step, LotID=lot, Bin=b, Count=max(0, c), Pass='N', Description=desc))
    return results, bins


FORECAST_GDPW = {'ORION': 9000, 'VEGA': 24000, 'LYRA': 7400, 'ATLAS': 9000, 'NOVA': 9400}
