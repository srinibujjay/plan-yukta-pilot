"""
Generate the synthetic sample data for the Plan Yukta pilot.

Everything here is invented: company, products, lots and quantities. It is
built to exercise every calculation, including each OSAT de-duplication rule,
an ambiguous OSAT part name, E&O rows, a late fab lot and a capacity flag.

    python -m sample.make_sample      (from the pilot folder)
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pandas as pd

AS_OF = date(2026, 11, 6)
FIRST_SNAPSHOT = AS_OF - timedelta(days=41)  # six weeks of daily OSAT reports

PRODUCT_MAP = pd.DataFrame([
    # MASTER_PRODUCT, FAB_PRODUCT, OSAT_PARTNAME, GROSS_DIE_PER_WAFER
    ('ORION A0', 'OR1100A0', 'OR1100A0-P1', 8200),
    ('ORION A0', None, 'ORION', 8200),          # generic OSAT name shared by A0 and B0
    ('ORION B0', 'OR1100B0', 'OR1100B0-P1', 8200),
    ('ORION B0', None, 'ORION', 8200),
    ('VEGA A0', 'VG2200A0', 'VG2200A0-W1', 21500),
], columns=['MASTER_PRODUCT', 'FAB_PRODUCT', 'OSAT_PARTNAME', 'GROSS_DIE_PER_WAFER'])

FAB = {'ORION A0': 'OR1100A0', 'ORION B0': 'OR1100B0', 'VEGA A0': 'VG2200A0'}
PART = {'ORION A0': 'OR1100A0-P1', 'ORION B0': 'OR1100B0-P1', 'VEGA A0': 'VG2200A0-W1'}
GDW = {'ORION A0': 8200, 'ORION B0': 8200, 'VEGA A0': 21500}

# Lots that reach the OSAT: (mother, product, wafers, fab ship day offset from first snapshot,
#   uses bump, days in Sort, Bump, Assembly, Testing, Packing)
OSAT_LOTS = [
    ('KA1001', 'ORION A0', 12, -20, False, (6, 0, 9, 7, 4)),
    ('KA1002', 'ORION A0', 10, -8, False, (7, 0, 10, 8, 4)),
    ('KA1003', 'ORION A0', 8, 10, False, (5, 0, 9, 8, 4)),
    ('KA1004', 'ORION A0', 12, 18, False, (6, 0, 8, 9, 4)),
    ('KA1005', 'ORION A0', 12, 27, False, (6, 0, 10, 8, 4)),
    ('KA1006', 'ORION A0', 10, 35, False, (7, 0, 9, 8, 4)),
    ('KB2001', 'ORION B0', 10, -12, False, (6, 0, 10, 9, 4)),
    ('KB2002', 'ORION B0', 9, 12, False, (7, 0, 9, 8, 4)),
    ('KB2003', 'ORION B0', 11, 24, False, (6, 0, 9, 8, 4)),
    ('KB2004', 'ORION B0', 10, 36, False, (6, 0, 9, 8, 4)),
    ('KV3001', 'VEGA A0', 6, -15, True, (5, 6, 9, 8, 4)),
    ('KV3002', 'VEGA A0', 6, 8, True, (6, 7, 9, 7, 4)),
    ('KV3003', 'VEGA A0', 8, 26, True, (5, 6, 10, 8, 4)),
    ('KV3004', 'VEGA A0', 8, 33, True, (5, 7, 9, 8, 4)),
]
# Lots still at the fab: (lot, product, stage, wafers, start offset days before AS_OF, commit, projected)
FAB_LOTS = [
    ('KA1007.1', 'ORION A0', 'METAL4', 12, 48, 30, 30),
    ('KA1008.1', 'ORION A0', 'POLY', 12, 21, 58, 66),   # projected 8 days after commit
    ('KB2005.1', 'ORION B0', 'CONTACT', 10, 33, 42, 42),
    ('KB2006.1', 'ORION B0', 'STI', 10, 9, 70, 70),
    ('KV3005.1', 'VEGA A0', 'PASSIVATION', 8, 66, 9, 15),  # projected 6 days late
    ('KV3006.1', 'VEGA A0', 'METAL2', 8, 25, 50, 50),
]


def _wafer_ids(n):
    return ','.join(str(i) for i in range(1, n + 1))


def _row(snap, main, oper, state, part, lot, sub, wafers, dies, wafer_id, datecode=None, location=None):
    return {'SNAPSHOT_DATE': snap, 'MAIN': main, 'OPER': oper, 'STATE': state, 'PARTNAME': part,
            'C_LOT_NUMBER': f'{lot}.{sub}', 'WAFER_QTY': wafers, 'DIE_QTY': dies,
            'WAFER_ID': wafer_id, 'DATECODE': datecode, 'LOCATION': location}


def build():
    rng = random.Random(7)
    snapshots = [datetime.combine(FIRST_SNAPSHOT + timedelta(days=d), datetime.min.time()) + timedelta(hours=8)
                 for d in range(42)]
    osat_rows, ship_rows = [], []

    for mother, product, wafers, ship_offset, bump, days in OSAT_LOTS:
        fab_ship = FIRST_SNAPSHOT + timedelta(days=ship_offset)
        ship_rows.append({'Ship Date': fab_ship, 'Fab Product': FAB[product], 'Fab Lot ID': f'{mother}.1',
                          'UM': 'WF', 'Ship Qty': wafers})
        ship_rows.append({'Ship Date': fab_ship, 'Fab Product': FAB[product], 'Fab Lot ID': f'{mother}.1',
                          'UM': 'LT', 'Ship Qty': 1})  # lot-count line, excluded (UM <> WF)
        # Sort starts 2-4 days after the fab ships
        cursor = fab_ship + timedelta(days=rng.randint(2, 4))
        plan = [('CP', days[0])]
        if bump:
            plan.append(('BUMP', days[1]))
        plan += [('ASSY', days[2]), ('FT', days[3]), ('PK', days[4])]
        windows = []
        for stage, length in plan:
            windows.append((stage, cursor, cursor + timedelta(days=length - 1)))
            cursor += timedelta(days=length + rng.randint(0, 2))  # queue time between stages

        good_dies = int(wafers * GDW[product] * 0.92)
        part = PART[product]
        # Two ORION lots are reported by the OSAT under the bare family name
        if mother in ('KA1002', 'KB2002'):
            part = 'ORION'
        wid = _wafer_ids(wafers)
        dc = f'26{(fab_ship + timedelta(days=30)).isocalendar()[1]:02d}'

        for snap in snapshots:
            day = snap.date()
            for stage, start, end in windows:
                if not (start <= day <= end):
                    continue
                state = 'WAIT' if day == start else ('HOLD' if (mother == 'KB2001' and stage == 'ASSY') else 'PROCESS')
                if stage == 'CP':
                    osat_rows.append(_row(snap, 'CP', 'WS1', state, part, mother, '1', wafers, 0, wid))
                elif stage == 'BUMP':
                    osat_rows.append(_row(snap, 'BUMP', 'BP', state, part, mother, '1', wafers, 0, wid))
                elif stage == 'ASSY':
                    half = wafers // 2
                    osat_rows.append(_row(snap, 'ASSY', 'DA', state, part, mother, '01.EA', half,
                                          int(half * GDW[product] * 0.95), wid))
                    osat_rows.append(_row(snap, 'ASSY', 'WB', state, part, mother, '02.EA', wafers - half,
                                          int((wafers - half) * GDW[product] * 0.95), wid))
                elif stage == 'FT':
                    osat_rows.append(_row(snap, 'FT', 'FT1', state, part, mother, '01.EA', 0,
                                          int(good_dies * 0.5), None, dc))
                    osat_rows.append(_row(snap, 'FT', 'FT1', state, part, mother, '02.EA', 0,
                                          good_dies - int(good_dies * 0.5), None, dc))
                elif stage == 'PK':
                    osat_rows.append(_row(snap, 'FT', 'IP', state, part, mother, '01.EA', 0,
                                          good_dies, None, dc, 'BIN1'))

    osat = pd.DataFrame(osat_rows)
    latest = snapshots[-1]
    prev = snapshots[-2]

    def add(rows):
        nonlocal osat
        osat = pd.concat([osat, pd.DataFrame(rows)], ignore_index=True)

    # --- Report artefacts the de-duplication rules exist to remove -------------
    live = osat[osat['SNAPSHOT_DATE'] == latest]

    def lot_at(main):
        rows = live[live['MAIN'] == main]
        return rows.iloc[0] if not rows.empty else None

    assy = lot_at('ASSY')
    cp = lot_at('CP')
    ft = lot_at('FT')
    bump = lot_at('BUMP')
    extra = []
    if assy is not None:   # stale Sort transfer for a wafer set already in Assembly (cross-stage)
        m = assy['C_LOT_NUMBER'][:6]
        n = len(str(assy['WAFER_ID']).split(','))
        extra.append(_row(prev, 'CP', 'TF', 'TRANSFER', assy['PARTNAME'], m, '1', n, 0, assy['WAFER_ID']))
        extra.append(_row(latest, 'CP', 'TF', 'TRANSFER', assy['PARTNAME'], m, '1', n, 0, assy['WAFER_ID']))
    if cp is not None:     # same wafers shown twice inside Sort: WAIT row plus TRANSFER row
        extra.append(_row(latest, 'CP', 'TF', 'TRANSFER', cp['PARTNAME'], cp['C_LOT_NUMBER'][:6], '1',
                          cp['WAFER_QTY'], 0, cp['WAFER_ID']))
    if ft is not None:     # leftover Sort transfer for a lot already in Final Test (no wafer match)
        extra.append(_row(latest, 'CP', 'TF', 'TRANSFER', ft['PARTNAME'], ft['C_LOT_NUMBER'][:6], '1',
                          2, 0, '11,12'))
    vega_ft = live[(live['MAIN'] == 'FT') & live['PARTNAME'].eq(PART['VEGA A0'])]
    if not vega_ft.empty:  # Bump still shows FINISH for a lot that is already in Final Test
        r = vega_ft.iloc[0]
        extra.append(_row(latest, 'BUMP', 'BP', 'FINISH', r['PARTNAME'], r['C_LOT_NUMBER'][:6], '1',
                          6, 0, _wafer_ids(6)))
    # --- Aged and downgraded stock for the E&O view ----------------------------
    extra.append(_row(latest, 'FT', 'BANK', 'WAIT', PART['ORION A0'], 'KA0901', '03.EA', 0, 4200, None, '2331', 'BIN1'))
    extra.append(_row(latest, 'FT', 'BANK', 'WAIT', PART['ORION B0'], 'KB1907', '02.EA', 0, 1850, None, '2604', 'BIN3'))
    extra.append(_row(latest, 'FT', 'BANK', 'WAIT', PART['VEGA A0'], 'KV2902', '01.EA', 0, 960, None, '2412', 'BIN2'))
    add(extra)

    osat = osat.sort_values(['SNAPSHOT_DATE', 'C_LOT_NUMBER', 'MAIN']).reset_index(drop=True)

    # Two VEGA lots are missing from the fab shipment file, so the capacity check fires
    ship = pd.DataFrame(ship_rows)
    ship = ship[~ship['Fab Lot ID'].isin(['KV3002.1', 'KV3003.1'])].sort_values('Ship Date').reset_index(drop=True)

    fab_rows = []
    for lot, product, stage, wafers, age, commit_in, proj_in in FAB_LOTS:
        start = AS_OF - timedelta(days=age)
        fab_rows.append({'Fab Product': FAB[product], 'Fab Lot ID': lot, 'Current Stage': stage,
                         'Current Qty': wafers, 'Wafer Start Date': start,
                         'Committed Date': AS_OF + timedelta(days=commit_in),
                         'Projected Out Date': AS_OF + timedelta(days=proj_in)})
    # A lot the fab already shipped still appears with stage SHIPPED: excluded from fab WIP
    fab_rows.append({'Fab Product': 'OR1100A0', 'Fab Lot ID': 'KA1006.1', 'Current Stage': 'SHIPPED',
                     'Current Qty': 10, 'Wafer Start Date': AS_OF - timedelta(days=80),
                     'Committed Date': FIRST_SNAPSHOT + timedelta(days=35),
                     'Projected Out Date': FIRST_SNAPSHOT + timedelta(days=35)})
    fab = pd.DataFrame(fab_rows)

    return {'as_of': AS_OF, 'product_map': PRODUCT_MAP, 'fab_wip': fab, 'fab_ship': ship, 'osat_wip': osat,
            **planning_inputs()}


def planning_inputs():
    """Demand history, customer forecast and planning parameters for the planning modules."""
    import math as _m
    rng = random.Random(11)
    first_hist = pd.Timestamp(2024, 11, 1)          # 24 months of actuals up to Oct 2026
    plan_start = pd.Timestamp(2026, 11, 1)
    rows = []
    for i in range(24):
        m = first_hist + pd.DateOffset(months=i)
        season = 1 + 0.08 * _m.sin(2 * _m.pi * (m.month - 3) / 12)
        a0 = max(0, 260_000 - 7_000 * i) * season * rng.uniform(0.93, 1.07)              # older revision, declining
        b0 = (0 if i < 8 else 40_000 + 16_000 * (i - 8)) * season * rng.uniform(0.92, 1.08)  # new revision ramping
        vg = 300_000 * season * rng.uniform(0.9, 1.1)                                       # steady product
        for prod, q in (('ORION A0', a0), ('ORION B0', b0), ('VEGA A0', vg)):
            rows.append((prod, m, 'ACTUAL', round(q, -2)))
    customer = {   # customer forecasts for the next six months (not every month is covered)
        'ORION A0': [95_000, 90_000, 80_000, 70_000, 60_000, 50_000],
        'ORION B0': [300_000, 340_000, 380_000, 420_000, 460_000, 500_000],
        'VEGA A0': [310_000, 320_000, 300_000, None, None, None],
    }
    for prod, qs in customer.items():
        for i, q in enumerate(qs):
            if q is not None:
                rows.append((prod, plan_start + pd.DateOffset(months=i), 'FORECAST', q))
    demand = pd.DataFrame(rows, columns=['PRODUCT', 'MONTH', 'TYPE', 'QTY'])

    plan_params = pd.DataFrame([
        # PRODUCT, GDW, yields: line, sort, assy, FT; cycle time weeks: fab, bump, sort, assy, FT;
        # wafer lot, safety stock weeks, FG on hand, die bank on hand
        ('ORION A0', 8200, 0.98, 0.90, 0.995, 0.97, 12, 0, 2, 3, 2, 25, 4, 150_000, 250_000),
        ('ORION B0', 8200, 0.97, 0.86, 0.99, 0.95, 12, 0, 2, 3, 2, 25, 4, 650_000, 1_100_000),
        ('VEGA A0', 21500, 0.98, 0.92, 0.995, 0.98, 14, 3, 2, 3, 2, 25, 6, 700_000, 1_400_000),
    ], columns=['PRODUCT', 'GDW', 'FAB_LINE_YIELD', 'SORT_YIELD', 'ASSY_YIELD', 'FT_YIELD',
                'CT_FAB_WK', 'CT_BUMP_WK', 'CT_SORT_WK', 'CT_ASSY_WK', 'CT_FT_WK',
                'WAFER_LOT', 'SAFETY_STOCK_WK', 'FG_ON_HAND', 'DIE_BANK_ON_HAND'])

    tester_params = pd.DataFrame([
        # PRODUCT, INSERTION, TESTER_TYPE, TEST_TIME_S, SITES, INDEX_TIME_S, STEPPING_EFF, WAFER_LOAD_S
        ('ORION A0', 'CP1', 'Sort-ATE-A', 1.10, 16, 0.40, 0.92, 90),
        ('ORION A0', 'FT1', 'FT-ATE-B', 2.4, 4, 0.5, None, None),
        ('ORION B0', 'CP1', 'Sort-ATE-A', 1.30, 16, 0.40, 0.92, 90),
        ('ORION B0', 'FT1', 'FT-ATE-B', 4.0, 4, 0.5, None, None),
        ('ORION B0', 'FT2', 'FT-ATE-B', 2.5, 4, 0.5, None, None),
        ('VEGA A0', 'CP1', 'Sort-ATE-A', 0.70, 32, 0.40, 0.90, 90),
        ('VEGA A0', 'FT1', 'FT-ATE-B', 2.2, 4, 0.5, None, None),
    ], columns=['PRODUCT', 'INSERTION', 'TESTER_TYPE', 'TEST_TIME_S', 'SITES', 'INDEX_TIME_S',
                'STEPPING_EFF', 'WAFER_LOAD_S'])

    tester_capacity = pd.DataFrame([
        ('Sort-ATE-A', 'OSAT-1 Test', 1, 150, 0.75),
        ('FT-ATE-B', 'OSAT-1 Test', 1, 140, 0.70),
    ], columns=['TESTER_TYPE', 'OSAT', 'QTY_TESTERS', 'HOURS_PER_WEEK', 'OEE'])

    return {'demand': demand, 'plan_params': plan_params, 'tester_params': tester_params,
            'tester_capacity': tester_capacity, 'plan_start': plan_start.date()}


if __name__ == '__main__':
    d = build()
    for k in ('fab_wip', 'fab_ship', 'osat_wip'):
        print(k, d[k].shape)
