"""
Upload format for the Plan Yukta workbook: one entry per sheet and column.
Used by the /format page and by the chat assistant, so both always agree with the code.
"""

SHEETS = [
    {
        'sheet': 'Settings', 'module': 'All', 'required': True,
        'purpose': 'Run settings. Two columns: Setting and Value. Keep the setting names exactly as in the template.',
        'columns': [
            ('As-of date', 'Yes', 'date', '2026-11-06', 'Date the WIP view is run for. E&O age and lead times are measured to this date.'),
            ('E&O age threshold (months)', 'Yes', 'number', '24', 'Stock with a YYWW date code older than this counts as excess/obsolete.'),
            ('E&O bin baseline', 'Yes', 'text', 'BIN1', 'Bins above this (BIN2, BIN3 ...) count as E&O.'),
            ('Capacity tolerance', 'Yes', 'number', '1.05', 'Headroom for the gross-die capacity check.'),
            ('Plan start month', 'For planning', 'date (1st of month)', '2026-11-01', 'First month of the forecast and supply plan.'),
            ('Horizon (months)', 'For planning', 'number 3-18', '12', 'Months to plan.'),
            ('Frozen months / Slushy months', 'For planning', 'number', '1 / 3', 'B2B time fences.'),
            ('Forecast method', 'For planning', 'BLEND, CUSTOMER or STAT', 'BLEND', 'How plan demand is built.'),
            ('Demand uplift %', 'For planning', 'number', '0', 'Scenario lever on final demand.'),
            ('Smoothing alpha / beta', 'Optional', 'number', '0.35 / 0.15', 'Weights for the statistical forecast.'),
        ],
    },
    {
        'sheet': 'Products', 'module': 'Material now', 'required': True,
        'purpose': 'One row per product you plan.',
        'columns': [
            ('MASTER_PRODUCT', 'Yes', 'text', 'NOVA A0', 'Your own product name, used everywhere else.'),
            ('GROSS_DIE_PER_WAFER', 'Yes', 'number', '8500', 'Gross die per wafer (GDW).'),
        ],
    },
    {
        'sheet': 'Name_Map', 'module': 'Material now', 'required': True,
        'purpose': 'Every name your foundry and OSAT use for each product.',
        'columns': [
            ('NAME', 'Yes', 'text', 'NV1000A0-P1', 'Product name exactly as it appears in the supplier report.'),
            ('SOURCE', 'Yes', 'FAB or OSAT', 'OSAT', 'Which report uses this name.'),
            ('MASTER_PRODUCT', 'Yes', 'text', 'NOVA A0', 'The product it belongs to. One OSAT name may map to two products; it is resolved through fab lot numbers.'),
        ],
    },
    {
        'sheet': 'Fab_WIP', 'module': 'Material now', 'required': True,
        'purpose': "Your foundry's WIP report, one row per lot. Vendor headings such as Lot ID or Customer Product are recognised.",
        'columns': [
            ('Fab Product', 'Yes', 'text', 'NV1000A0', 'Product name used by the foundry.'),
            ('Fab Lot ID', 'Yes', 'text', 'XN0001.1', 'Foundry lot. The first 6 characters are the mother lot.'),
            ('Current Stage', 'Yes', 'text', 'METAL3', 'SHIPPED rows are excluded from WIP.'),
            ('Current Qty', 'Yes', 'number (wafers)', '12', 'Wafers in the lot.'),
            ('Wafer Start Date', 'Optional', 'date', '2026-09-01', 'Used for the fab leg of lead time.'),
            ('Committed Date', 'Optional', 'date', '2026-12-01', 'Used for late-lot checks.'),
            ('Projected Out Date', 'Optional', 'date', '2026-12-04', 'Used for late-lot checks.'),
        ],
    },
    {
        'sheet': 'Fab_Shipments', 'module': 'Material now', 'required': True,
        'purpose': 'Foundry shipment lines.',
        'columns': [
            ('Ship Date', 'Yes', 'date', '2026-10-20', ''),
            ('Fab Product', 'Yes', 'text', 'NV1000A0', ''),
            ('Fab Lot ID', 'Yes', 'text', 'XN0001.1', ''),
            ('UM', 'Yes', 'WF or other', 'WF', 'Only WF (wafer) lines count as shipped wafers.'),
            ('Ship Qty', 'Yes', 'number', '12', ''),
        ],
    },
    {
        'sheet': 'OSAT_WIP', 'module': 'Material now', 'required': True,
        'purpose': 'One or more daily OSAT WIP reports stacked together. Four to eight weeks of history give the best de-duplication and lead times.',
        'columns': [
            ('SNAPSHOT_DATE', 'Yes', 'date-time', '2026-11-02 08:00', 'Date of the report the row comes from.'),
            ('MAIN', 'Yes', 'CP, BUMP, ASSY, FT', 'ASSY', 'Main operation.'),
            ('OPER', 'Yes', 'text', 'DA', 'Sub-operation. FT with OPER = IP counts as Packing.'),
            ('STATE', 'Yes', 'text', 'PROCESS', 'WAIT, PROCESS, HOLD, TRANSFER or FINISH.'),
            ('PARTNAME', 'Yes', 'text', 'NV1000A0-P1', 'OSAT product name (mapped through Name_Map).'),
            ('C_LOT_NUMBER', 'Yes', 'text', 'XN0001.01.EA', 'Customer lot; first 6 characters = mother lot.'),
            ('WAFER_QTY', 'Yes', 'number', '6', 'Used for Sort and Bump.'),
            ('DIE_QTY', 'Yes', 'number', '48450', 'Used for Assembly, Test and Packing.'),
            ('WAFER_ID', 'Yes', 'text', '1,2,3', 'Wafer numbers as the OSAT reports them.'),
            ('DATECODE', 'Optional', 'YYWW', '2543', 'For E&O ageing.'),
            ('LOCATION', 'Optional', 'text', 'BIN1', 'Bin; BIN1 or GOOD on FT counts as Packing.'),
        ],
    },
    {
        'sheet': 'Demand', 'module': 'Planning', 'required': False,
        'purpose': 'Monthly shipment history and customer forecast, one row per product and month.',
        'columns': [
            ('PRODUCT', 'Yes', 'text', 'NOVA A0', 'Master product.'),
            ('MONTH', 'Yes', 'date (1st of month)', '2026-12-01', ''),
            ('TYPE', 'Yes', 'ACTUAL or FORECAST', 'FORECAST', 'ACTUAL = history shipped; FORECAST = customer forecast.'),
            ('QTY', 'Yes', 'number (units)', '150000', ''),
        ],
    },
    {
        'sheet': 'Plan_Params', 'module': 'Planning', 'required': False,
        'purpose': 'Yields, cycle times and stock for each product.',
        'columns': [
            ('PRODUCT', 'Yes', 'text', 'NOVA A0', ''),
            ('GDW', 'Yes', 'number', '8500', 'Gross die per wafer.'),
            ('FAB_LINE_YIELD', 'Yes', '0-1', '0.98', 'Share of started wafers that reach sort.'),
            ('SORT_YIELD', 'Yes', '0-1', '0.90', 'Wafer sort die yield.'),
            ('ASSY_YIELD', 'Yes', '0-1', '0.99', 'Assembly yield.'),
            ('FT_YIELD', 'Yes', '0-1', '0.97', 'Final test yield.'),
            ('CT_FAB_WK, CT_BUMP_WK, CT_SORT_WK, CT_ASSY_WK, CT_FT_WK', 'Yes', 'weeks', '12, 0, 2, 3, 2', 'Cycle time per module; 0 for bump if not bumped.'),
            ('WAFER_LOT', 'Yes', 'number', '25', 'Wafer starts are rounded up to this lot size.'),
            ('SAFETY_STOCK_WK', 'Yes', 'weeks', '4', 'Finished-goods safety stock in weeks of demand.'),
            ('FG_ON_HAND', 'Yes', 'units', '100000', 'Finished goods today.'),
            ('DIE_BANK_ON_HAND', 'Yes', 'good die', '50000', 'Sorted good die in the die bank today.'),
        ],
    },
    {
        'sheet': 'Tester_Params', 'module': 'Planning', 'required': False,
        'purpose': 'Test time per product and insertion. CP/WS insertions are wafer sort; FT insertions are final test.',
        'columns': [
            ('PRODUCT', 'Yes', 'text', 'NOVA A0', ''),
            ('INSERTION', 'Yes', 'CP1, CP2, FT1, FT2 ...', 'FT1', ''),
            ('TESTER_TYPE', 'Yes', 'text', 'FT-ATE', 'Must match Tester_Capacity.'),
            ('TEST_TIME_S', 'Yes', 'seconds', '2.5', 'Test time per touchdown.'),
            ('SITES', 'Yes', 'number', '4', 'Devices tested in parallel.'),
            ('INDEX_TIME_S', 'Yes', 'seconds', '0.5', 'Handler or prober index time.'),
            ('STEPPING_EFF', 'Sort only', '0-1', '0.92', 'Share of useful touchdowns on a wafer.'),
            ('WAFER_LOAD_S', 'Sort only', 'seconds', '90', 'Load, align and unload time per wafer.'),
        ],
    },
    {
        'sheet': 'Tester_Capacity', 'module': 'Planning', 'required': False,
        'purpose': 'Testers available at the OSAT, one row per tester type.',
        'columns': [
            ('TESTER_TYPE', 'Yes', 'text', 'FT-ATE', ''),
            ('OSAT', 'Optional', 'text', 'OSAT test site', ''),
            ('QTY_TESTERS', 'Yes', 'number', '1', ''),
            ('HOURS_PER_WEEK', 'Yes', 'hours', '150', 'Scheduled hours per tester per week.'),
            ('OEE', 'Yes', '0-1', '0.70', 'Overall equipment effectiveness.'),
        ],
    },
]

RULES = [
    'Start from the template: keep sheet names and column headings exactly as they are.',
    'Material now needs Settings, Products, Name_Map, Fab_WIP, Fab_Shipments and OSAT_WIP.',
    'Planning (forecast, supply plan, testers, B2B package) runs when Demand, Plan_Params, Tester_Params and Tester_Capacity are also filled.',
    'Delete the grey example rows, or overwrite them with your data.',
    'Leave the grey "(calc)" columns alone; they are Excel formulas.',
    'Dates can be Excel dates or text such as 2026-11-01.',
    'Yields can be fractions (0.95) or percentages (95).',
    'Up to 25 MB per upload. Use anonymised data if you are not allowed to share the real figures.',
]


def as_text() -> str:
    """Plain-text version for the chat assistant."""
    lines = ['UPLOAD FORMAT'] + [f'- {r}' for r in RULES]
    for s in SHEETS:
        lines.append(f"\nSheet {s['sheet']} ({'required' if s['required'] else 'optional, for planning'}): {s['purpose']}")
        for c in s['columns']:
            lines.append(f'  {c[0]} | required: {c[1]} | type: {c[2]} | example: {c[3]} | {c[4]}')
    return '\n'.join(lines)
