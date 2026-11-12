"""
Workspace: the editable data tables behind every Plan Yukta module.

Each visitor gets their own copy of the demo data (a "workspace"). They can edit
any table on its Data page, upload their own CSV/Excel for a table, or replace
the whole workspace from one workbook. Workspaces are kept as small JSON files
on the server for a day and are never shared between visitors.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

STORE = Path(os.environ.get('WORKSPACE_DIR', '/tmp/planyukta_ws'))
TTL_SECONDS = 24 * 3600
MAX_ROWS = 5000
_lock = threading.Lock()

OPERATIONS = ['Sort', 'Bump', 'Assembly', 'Test1', 'Test2', 'Pack']
WIP_OPERATIONS = ['Sort', 'Bump', 'DieBank', 'Assembly', 'Test1', 'Test2', 'Pack', 'FG']
TEST_STEPS = ['Sort', 'Test1', 'Test2']
YN = ['Y', 'N']


def C(name, typ='text', help='', choices=None, required=True, lo=None, hi=None, readonly=False):
    return {'name': name, 'type': typ, 'help': help, 'choices': choices, 'required': required,
            'lo': lo, 'hi': hi, 'readonly': readonly}


# --------------------------------------------------------------------------------------------
# Table catalogue. 'group' drives the Data page; 'used_by' lists the modules that read it.
# Types: text, int, num, frac (0-1), month (YYYY-MM), date (YYYY-MM-DD), choice.
# --------------------------------------------------------------------------------------------
TABLES = {
    'settings': {
        'title': 'Plan settings', 'group': 'Master data', 'keyed': True,
        'about': 'Run-wide settings: plan start, horizon, ordering rules, tester and forecast options.',
        'used_by': ['All modules'],
        'columns': [C('Setting', readonly=True), C('Value', help='Edit the value; the type depends on the setting.'),
                    C('Notes', required=False, readonly=True)],
    },
    'products': {
        'title': 'Products (SKU master)', 'group': 'Master data', 'key': ['SKU'],
        'about': 'One row per product. Gross die per wafer, priority, build strategy, pull-in and service level, prices.',
        'used_by': ['Testing Starts', 'Assembly', 'Front End', 'FAB PO', 'Cost', 'P&L', 'NPI'],
        'columns': [
            C('SKU', help='Product name used in every other table.'),
            C('Description', required=False),
            C('Package', required=False),
            C('Status', 'choice', choices=['HVM', 'NPI', 'EOL'], help='HVM = volume production, NPI = new product, EOL = end of life.'),
            C('GDPW', 'int', 'Gross die per wafer.', lo=1),
            C('Priority', 'int', 'Higher number = gets scarce testers first.', lo=0, hi=10),
            C('BuildStrategy', 'choice', choices=['FORECAST', 'ORDERS', 'STAT', 'BLEND'],
              help='FORECAST = larger of customer forecast and booked orders; ORDERS = booked orders only; STAT = statistical forecast; BLEND = average of forecast and statistical.'),
            C('SafetyStockWeeks', 'num', 'Finished-goods safety stock in weeks of demand.', lo=0, hi=26),
            C('PullIn', 'choice', choices=YN, help='Y = idle tester time in earlier months may build ahead for later shortfalls.'),
            C('ServiceLevelPct', 'num', 'Share of a future shortfall you are willing to build ahead for.', lo=0, hi=100),
            C('MaxPullInPct', 'num', 'Cap on pull-in as % of the shortfall it covers (cash control).', lo=0, hi=100),
            C('PullInWeight', 'num', 'Pull-in appetite: -0.10 aggressive, -0.05 moderate, -0.02 conservative, 0 neutral (own idle testers only), positive = avoid pull-in.', lo=-0.10, hi=0.05, required=False),
            C('WaferPriceUSD', 'num', 'Foundry price per wafer.', lo=0),
            C('SubstrateType', 'choice', choices=['None', 'Leadframe', 'Substrate'], help='Assembly material that must be on hand.'),
            C('NPIStartDate', 'date', 'NPI only: date engineering wafers start.', required=False),
        ],
    },
    'process_flow': {
        'title': 'Process flow & yields', 'group': 'Master data', 'key': ['SKU', 'Operation'],
        'about': 'Manufacturing steps per product with yield, retest (rework) rate and cycle time.',
        'used_by': ['Testing Starts', 'Assembly', 'Front End', 'Complete Flow', 'Cost', 'NPI'],
        'columns': [
            C('SKU'), C('Operation', 'choice', choices=OPERATIONS), C('Step', 'int', 'Order of the step.', lo=1, hi=20),
            C('Yield', 'frac', 'Good-out share (0-1). Sort and Bump yields are die-level: wafer count does not change.', lo=0.01, hi=1),
            C('ReworkRate', 'frac', 'Test steps: share of units re-inserted (retest). Adds tester load, not output.', lo=0, hi=1),
            C('CycleTimeDays', 'num', 'Days the step takes, used for lead-time offsets.', lo=0, hi=120),
        ],
    },
    'bin_splits': {
        'title': 'Bin splits', 'group': 'Master data', 'key': ['SKU', 'Bin'],
        'about': 'How good units from final test split into bins. Fractions per product should add up to 1.',
        'used_by': ['ATP', 'Complete Flow'],
        'columns': [C('SKU'), C('Bin'), C('Fraction', 'frac', lo=0, hi=1)],
    },
    'vendors': {
        'title': 'OSAT vendors', 'group': 'Master data', 'key': ['Vendor'],
        'about': 'Assembly & test subcontractors and the share of each product\'s volume they get.',
        'used_by': ['Testing Starts', 'OSAT PO', 'B2B'],
        'columns': [C('Vendor'), C('Name', required=False), C('Region', required=False),
                    C('SharePct', 'num', 'Planned share of volume. Re-normalised over the vendors qualified for a product.', lo=0, hi=100),
                    C('Enabled', 'choice', choices=YN)],
    },
    'forecast': {
        'title': 'Customer forecast', 'group': 'Demand', 'key': ['Month', 'SKU'],
        'about': 'Monthly customer forecast in units (all bins).',
        'used_by': ['Demand & Forecast', 'Testing Starts'],
        'columns': [C('Month', 'month'), C('SKU'), C('Units', 'int', lo=0)],
    },
    'orders': {
        'title': 'Customer orders', 'group': 'Demand', 'key': ['OrderID'],
        'about': 'Booked orders (backlog) by customer, bin and requested date. Used for ORDERS build strategy, forecast consumption and P&L by customer.',
        'used_by': ['Demand & Forecast', 'ATP', 'P&L'],
        'columns': [C('OrderID'), C('Customer'), C('SKU'), C('Bin'), C('Month', 'month', 'Ship month.'),
                    C('CRD', 'date', 'Customer requested date.'), C('Qty', 'int', lo=0),
                    C('Status', 'choice', choices=['Confirmed', 'Open', 'Cancelled'])],
    },
    'shipment_history': {
        'title': 'Shipment history', 'group': 'Demand', 'key': ['Month', 'SKU'],
        'about': 'Units shipped per month in the past. Feeds the statistical (Holt) forecast and its accuracy.',
        'used_by': ['Demand & Forecast'],
        'columns': [C('Month', 'month'), C('SKU'), C('Units', 'int', lo=0)],
    },
    'customer_bins': {
        'title': 'Shippable matrix', 'group': 'Demand', 'key': ['Customer', 'SKU', 'Bin'],
        'about': 'Which bins each customer accepts, with minimum order quantity (MOQ).',
        'used_by': ['ATP'],
        'columns': [C('Customer'), C('SKU'), C('Bin'), C('MOQ', 'int', lo=0)],
    },
    'pricing': {
        'title': 'Selling prices', 'group': 'Demand', 'key': ['SKU', 'Customer'],
        'about': 'Average selling price per unit. Customer "*" is the default for anyone not listed.',
        'used_by': ['P&L'],
        'columns': [C('SKU'), C('Customer'), C('ASPUSD', 'num', lo=0)],
    },
    'reservations': {
        'title': 'Reservations', 'group': 'Demand', 'key': ['SalesOrder'],
        'about': 'Finished goods promised to customers. Reserved quantities are taken out of available-to-promise.',
        'used_by': ['ATP'],
        'columns': [C('SalesOrder'), C('Customer'), C('CustomerPO', required=False), C('SKU'), C('Vendor'), C('Bin'),
                    C('Qty', 'int', lo=0), C('CRD', 'date'), C('SSD', 'date', 'Scheduled ship date.'),
                    C('Status', 'choice', choices=['Reserved', 'Shipped', 'Cancelled'])],
    },
    'tester_fleet': {
        'title': 'Tester fleet', 'group': 'Capacity', 'key': ['Vendor', 'Step'],
        'about': 'Testers at each vendor per test step. Consignee = your own testers (cheaper per unit); non-consignee = the OSAT\'s, rented per unit.',
        'used_by': ['Testing Starts', 'Front End', 'Tester Capacity', 'Hardware', 'ATE Economics'],
        'columns': [C('Vendor'), C('Step', 'choice', choices=TEST_STEPS), C('TesterModel', required=False),
                    C('Consignee', 'int', lo=0, hi=500), C('NonConsignee', 'int', lo=0, hi=500),
                    C('HoursPerDay', 'num', 'Scheduled hours per tester per day.', lo=1, hi=24)],
    },
    'fleet_changes': {
        'title': 'Tester arrivals & removals (override)', 'group': 'Capacity', 'key': ['Month', 'Vendor', 'Step'],
        'about': 'Testers added (+) or removed (-) at an OSAT from a month onwards: new consignee testers, extra OSAT (non-consignee) testers, transfers.',
        'used_by': ['Overrides', 'Testing Starts', 'Tester Capacity'],
        'columns': [C('Month', 'month'), C('Vendor'), C('Step', 'choice', choices=TEST_STEPS),
                    C('ConsigneeChange', 'int', lo=-500, hi=500), C('NonConsigneeChange', 'int', lo=-500, hi=500),
                    C('Reason', required=False)],
    },
    'tester_capacity': {
        'title': 'Test times & rates', 'group': 'Capacity', 'key': ['Vendor', 'SKU', 'Step'],
        'about': 'Test time per product, vendor and step, and the price per unit (per wafer for Sort). A row here also means the vendor is qualified.',
        'used_by': ['Testing Starts', 'Front End', 'Tester Capacity', 'Cost', 'ATE Economics'],
        'columns': [
            C('Vendor'), C('SKU'), C('Step', 'choice', choices=TEST_STEPS),
            C('TestTimeSec', 'num', 'Seconds per touchdown.', lo=0.01),
            C('Sites', 'int', 'Devices tested in parallel.', lo=1, hi=1024),
            C('IndexTimeSec', 'num', 'Handler / prober index time per touchdown.', lo=0),
            C('OEE', 'frac', 'Overall equipment effectiveness (0-1).', lo=0.05, hi=1),
            C('StepEff', 'frac', 'Sort only: share of useful touchdowns on a wafer.', lo=0.05, hi=1, required=False),
            C('WaferLoadSec', 'num', 'Sort only: load/align/unload seconds per wafer.', lo=0, required=False),
            C('CostConsigneeUSD', 'num', 'Price per unit (per wafer for Sort) on your own testers.', lo=0),
            C('CostNonConsigneeUSD', 'num', 'Price per unit (per wafer for Sort) on OSAT testers.', lo=0),
        ],
    },
    'yield_overrides': {
        'title': 'Yield changes (override)', 'group': 'Capacity', 'key': ['SKU', 'Vendor', 'Operation', 'EffectiveMonth'],
        'about': 'Vendor-specific yield or retest rate from a month onwards (yield improvement plans, excursions).',
        'used_by': ['Testing Starts', 'Assembly', 'Front End'],
        'columns': [C('SKU'), C('Vendor'), C('Operation', 'choice', choices=OPERATIONS), C('EffectiveMonth', 'month'),
                    C('Yield', 'frac', lo=0.01, hi=1), C('ReworkRate', 'frac', lo=0, hi=1, required=False),
                    C('Note', required=False)],
    },
    'hardware': {
        'title': 'Test hardware (in service)', 'group': 'Capacity', 'key': ['Vendor', 'Step', 'HardwareType'],
        'about': 'Your consigned test hardware in service today (sockets, load boards, probe cards, instrument cards). Each consignee tester needs a full kit. Future deliveries go in Hardware arrivals.',
        'used_by': ['Hardware Readiness', 'Overrides', 'Testing Starts'],
        'columns': [C('Vendor'), C('Step', 'choice', choices=TEST_STEPS), C('HardwareType'),
                    C('PerTester', 'int', 'Units of this item one tester needs.', lo=1),
                    C('InService', 'int', lo=0)],
    },
    'hardware_arrivals': {
        'title': 'Hardware arrivals (override)', 'group': 'Capacity', 'key': ['Month', 'Vendor', 'Step', 'HardwareType'],
        'about': 'Future deliveries (+) or retirements (-) of test hardware, from a month onwards. They change how many consignee testers have a full kit.',
        'used_by': ['Overrides', 'Hardware Readiness', 'Testing Starts'],
        'columns': [C('Month', 'month', 'Month the hardware is available at the OSAT.'), C('Vendor'),
                    C('Step', 'choice', choices=TEST_STEPS), C('HardwareType', help='Must match a type in Test hardware.'),
                    C('Qty', 'int', 'Units arriving (+) or removed (-).', lo=-10000, hi=10000), C('Note', required=False)],
    },
    'capacity_overrides': {
        'title': 'Test time & OEE changes (override)', 'group': 'Capacity', 'key': ['Vendor', 'SKU', 'Step', 'EffectiveMonth'],
        'about': 'From a month onwards, replace the test time, sites, index time or OEE for a product at an OSAT: a new test program, a multi-site handler, an OEE improvement. Leave a field blank to keep the current value.',
        'used_by': ['Overrides', 'Testing Starts', 'Tester Capacity'],
        'columns': [C('Vendor'), C('SKU'), C('Step', 'choice', choices=TEST_STEPS), C('EffectiveMonth', 'month'),
                    C('TestTimeSec', 'num', 'New test time per touchdown (blank = keep).', lo=0.01, required=False),
                    C('Sites', 'int', 'New number of sites (blank = keep).', lo=1, hi=1024, required=False),
                    C('IndexTimeSec', 'num', 'New index time (blank = keep).', lo=0, required=False),
                    C('OEE', 'frac', 'New OEE (blank = keep).', lo=0.05, hi=1, required=False),
                    C('Note', required=False)],
    },
    'osat_wip': {
        'title': 'OSAT WIP snapshot', 'group': 'Inventory', 'key': ['Vendor', 'LotID'],
        'about': 'Every lot at every OSAT, in the vendor\'s own product codes and operation names. Mapped to your SKUs and standard steps, it is the starting supply for the plan.',
        'used_by': ['OSAT WIP', 'Testing Starts', 'Assembly', 'Front End', 'ATP'],
        'columns': [C('Vendor'), C('LotID'), C('VendorProduct', help='Product code as the vendor writes it.'),
                    C('VendorOperation', help='Operation name as the vendor writes it.'),
                    C('State', 'choice', choices=['WAIT', 'RUN', 'HOLD', 'DONE'],
                      help='DONE = finished at this operation, waiting to move. HOLD lots are not counted as supply unless the setting says so.'),
                    C('Wafers', 'int', lo=0, required=False), C('Units', 'int', 'Dies/units. Required from Assembly onwards.', lo=0, required=False),
                    C('Bin', required=False), C('HoldReason', required=False), C('DateCode', required=False)],
    },
    'product_codes': {
        'title': 'Vendor product codes', 'group': 'Inventory', 'key': ['Vendor', 'VendorProduct'],
        'about': 'Maps each vendor\'s product code to your SKU.',
        'used_by': ['OSAT WIP'],
        'columns': [C('Vendor'), C('VendorProduct'), C('SKU')],
    },
    'operation_codes': {
        'title': 'Vendor operation names', 'group': 'Inventory', 'key': ['Vendor', 'VendorOperation'],
        'about': 'Maps each vendor\'s operation names to the standard steps.',
        'used_by': ['OSAT WIP'],
        'columns': [C('Vendor'), C('VendorOperation'), C('Operation', 'choice', choices=WIP_OPERATIONS)],
    },
    'fab_wip': {
        'title': 'Fab WIP', 'group': 'Inventory', 'key': ['LotID'],
        'about': 'Wafers in the foundry with their expected out date. They arrive at sort after the transit time.',
        'used_by': ['Front End', 'FAB PO'],
        'columns': [C('LotID'), C('SKU'), C('Wafers', 'int', lo=0), C('Stage', required=False),
                    C('StartDate', 'date', required=False), C('ExpectedOutDate', 'date')],
    },
    'substrates': {
        'title': 'Substrate & lead frame stock', 'group': 'Inventory', 'key': ['SKU', 'Vendor', 'Supplier', 'ArrivalMonth'],
        'about': 'Assembly material on hand or arriving, with expiry. Consigned = you supplied it (not charged by the OSAT).',
        'used_by': ['Substrate & Lead Frame', 'OSAT PO', 'Cost'],
        'columns': [C('SKU'), C('Vendor'), C('Supplier'), C('ArrivalMonth', 'month'), C('Units', 'int', lo=0),
                    C('ExpiryMonth', 'month'), C('Consigned', 'choice', choices=YN)],
    },
    'osat_costs': {
        'title': 'OSAT price list', 'group': 'Procurement', 'key': ['Vendor', 'Operation', 'SKU'],
        'about': 'Price per wafer (Bump) or per unit (Assembly, Pack). SKU "*" applies to every product without its own row. Test prices are on Test times & rates.',
        'used_by': ['OSAT PO', 'Cost', 'P&L'],
        'columns': [C('Vendor'), C('Operation', 'choice', choices=['Bump', 'Assembly', 'Pack']),
                    C('SKU', help='Product, or * for all products.'),
                    C('Unit', 'choice', choices=['wafer', 'unit']), C('CostUSD', 'num', lo=0)],
    },
    'cross_flow': {
        'title': 'Cross-flow rules', 'group': 'Procurement', 'key': ['SKU', 'AfterOperation', 'FromVendor', 'ToVendor'],
        'about': 'Material moved between vendors after a step (e.g. assembled at A, tested at B).',
        'used_by': ['Cross Flow'],
        'columns': [C('SKU'), C('AfterOperation', 'choice', choices=OPERATIONS), C('FromVendor'), C('ToVendor'),
                    C('Percent', 'num', lo=0, hi=100), C('TransitDays', 'int', lo=0, hi=60),
                    C('CostPer1000USD', 'num', 'Logistics cost per 1,000 units (or wafers) moved.', lo=0),
                    C('Status', 'choice', choices=['Active', 'Inactive'])],
    },
    'npi_milestones': {
        'title': 'NPI qualification plan', 'group': 'Monitoring', 'key': ['SKU', 'Milestone'],
        'about': 'Reliability qualification milestones for new products, run one after another after the first lots finish.',
        'used_by': ['NPI'],
        'columns': [C('SKU'), C('Milestone'), C('Order', 'int', lo=1), C('CycleDays', 'int', lo=0), C('ReadoutDays', 'int', lo=0),
                    C('Status', 'choice', choices=['Planned', 'Running', 'Passed', 'Failed'], required=False,
                      help='Blank = Planned. A Failed milestone flags the product at risk.'),
                    C('ActualEnd', 'date', 'Actual readout date once done; later milestones re-plan from it.', required=False)],
    },
    'vendor_issues': {
        'title': 'Vendor issues log', 'group': 'Vendors & customers', 'key': ['IssueID'],
        'about': 'Supplier issues for QBR follow-up (8D style): what happened, severity, owner, due date, root cause, corrective action and status.',
        'used_by': ['Vendor QBR'],
        'columns': [C('IssueID'), C('Vendor', help='OSAT code (A, B, C) or FAB.'), C('Opened', 'date'),
                    C('Category', 'choice', choices=['Quality', 'Delivery', 'Capacity', 'Cost', 'Communication']),
                    C('Severity', 'choice', choices=['Critical', 'Major', 'Minor']), C('Title'),
                    C('SKU', required=False), C('Owner', required=False), C('Due', 'date', required=False),
                    C('Status', 'choice', choices=['Open', 'In progress', 'Closed']), C('Closed', 'date', required=False),
                    C('RootCause', required=False), C('Action', required=False)],
    },
    'qbr_weights': {
        'title': 'QBR scorecard weights', 'group': 'Vendors & customers', 'key': ['Category'],
        'about': 'How much each category counts in the vendor score, and the target that earns full marks.',
        'used_by': ['Vendor QBR'],
        'columns': [C('Category', 'choice', choices=['Quality', 'Delivery', 'Cost', 'Capacity', 'Responsiveness']),
                    C('WeightPct', 'num', lo=0, hi=100), C('Target', 'num', 'Score 100 at or above this (see notes).', lo=0, hi=1000),
                    C('Notes', required=False)],
    },
    'order_history': {
        'title': 'Agreed-order history', 'group': 'Vendors & customers', 'key': ['OrderID'],
        'about': 'Orders agreed with customers in the past and what the customer then did: took them as agreed, pushed out, pulled in, reduced or cancelled. Drives the customer rating.',
        'used_by': ['Customer Rating'],
        'columns': [C('OrderID'), C('Customer'), C('SKU'), C('AgreedMonth', 'month'), C('AgreedQty', 'int', lo=0),
                    C('Outcome', 'choice', choices=['Accepted', 'Pushed out', 'Pulled in', 'Reduced', 'Cancelled']),
                    C('ActualMonth', 'month', required=False), C('ActualQty', 'int', lo=0, required=False), C('Reason', required=False)],
    },
    'test_results': {
        'title': 'Test results (lot / wafer)', 'group': 'Test data', 'key': ['Step', 'LotID', 'WaferID'],
        'about': 'Units tested and passed per lot (or wafer) and test step, from the OSATs or your yield analytics tool. Feed it by file or by the test-data API.',
        'used_by': ['Post-Silicon Analysis'],
        'columns': [C('TestDate', 'date'), C('Vendor'), C('SKU'), C('Step', 'choice', choices=['Sort', 'Test1', 'Test2']), C('LotID'),
                    C('WaferID', help='Wafer number, or - for a lot-level row.'), C('TesterID', required=False),
                    C('Tested', 'int', lo=0), C('Passed', 'int', lo=0)],
    },
    'test_bins': {
        'title': 'Test bin counts', 'group': 'Test data', 'key': ['Step', 'LotID', 'Bin'],
        'about': 'Units per bin for each lot and step. Pass bins are sellable grades; fail bins are rejects by failure mode.',
        'used_by': ['Post-Silicon Analysis'],
        'columns': [C('Step', 'choice', choices=['Sort', 'Test1', 'Test2']), C('LotID'), C('Bin'), C('Count', 'int', lo=0),
                    C('Pass', 'choice', choices=YN), C('Description', required=False)],
    },
    'plan_snapshot': {
        'title': 'Frozen plan (past months)', 'group': 'Monitoring', 'key': ['Month', 'Vendor', 'SKU', 'Operation'],
        'about': 'The plan you committed to for past months, to compare with what the vendors delivered.',
        'used_by': ['Plan vs Actual'],
        'columns': [C('Month', 'month'), C('Vendor'), C('SKU'), C('Operation', 'choice', choices=OPERATIONS),
                    C('PlannedUnits', 'int', lo=0)],
    },
    'actuals': {
        'title': 'Vendor actuals', 'group': 'Monitoring', 'key': ['Month', 'Vendor', 'SKU', 'Operation'],
        'about': 'What each vendor delivered, with OEE components and disruptions.',
        'used_by': ['Plan vs Actual'],
        'columns': [C('Month', 'month'), C('Vendor'), C('SKU'), C('Operation', 'choice', choices=OPERATIONS),
                    C('ActualUnits', 'int', lo=0), C('AvailabilityPct', 'num', lo=0, hi=100),
                    C('PerformancePct', 'num', lo=0, hi=100), C('QualityPct', 'num', lo=0, hi=100),
                    C('DisruptionDays', 'num', lo=0, hi=31),
                    C('Disruption', 'choice', choices=['None', 'Tester down', 'Material shortage', 'Yield excursion', 'Hold', 'Logistics'])],
    },
}

GROUPS = ['Master data', 'Demand', 'Capacity', 'Inventory', 'Procurement', 'Monitoring', 'Vendors & customers', 'Test data']

# Settings: name -> (type, default, notes, lo, hi)
SETTINGS = {
    'As-of date': ('date', '2026-11-10', 'Today for the plan: PO status, lot ages and NPI dates are measured from here.', None, None),
    'Plan start month': ('month', '2026-11', 'First month of the plan.', None, None),
    'Horizon months': ('int', 12, 'Months planned (3-18).', 3, 18),
    'Working days per month': ('num', 30.4, 'Tester days per month (30.4 = running every day).', 15, 31),
    'Demand uplift %': ('num', 0, 'Scenario lever on all plan demand.', -90, 300),
    'Pull-in horizon months': ('int', 6, 'How far ahead idle testers may build for (limits obsolescence risk).', 0, 12),
    'Allow non-consignee testers': ('choice:Y,N', 'Y', 'N = plan on your own (consignee) testers only.', None, None),
    'Apply overrides': ('choice:Y,N', 'Y', 'N = plan without any tester, hardware, test-time or yield overrides (the baseline).', None, None),
    'Limit testers to hardware-ready': ('choice:Y,N', 'N', 'Y = consignee testers are capped by the kits in Test hardware.', None, None),
    'Count held lots as supply': ('choice:Y,N', 'N', 'Y = lots on HOLD count as available WIP.', None, None),
    'Fab cycle time weeks': ('num', 12, 'Wafer start to wafer out at the foundry.', 1, 40),
    'Fab to OSAT transit days': ('int', 7, 'Wafer out to arrival at sort.', 0, 60),
    'Wafer lot size': ('int', 25, 'Fab starts are rounded up to whole lots.', 1, 100),
    'Fab capacity wafers per month': ('int', 1600, 'Allocated foundry capacity; starts above it are flagged.', 0, 1000000),
    'Fab order cutoff day': ('int', 5, 'PO for a wafer-start month must be placed by this day of the month before.', 1, 28),
    'Fab semi-cutoff day': ('int', 20, 'Capacity reservation by this day, two months before the start month.', 1, 28),
    'OSAT order cutoff day': ('int', 10, 'OSAT PO for a month must be placed by this day of the month before.', 1, 28),
    'OSAT semi-cutoff day': ('int', 25, 'OSAT capacity reservation by this day, two months before.', 1, 28),
    'Frozen months': ('int', 1, 'B2B time fence: firm orders.', 0, 6),
    'Slushy months': ('int', 3, 'B2B time fence: changes within agreed flex.', 0, 12),
    'Holt alpha': ('num', 0.35, 'Statistical forecast: weight of the latest level (0.05-0.95).', 0.05, 0.95),
    'Holt beta': ('num', 0.15, 'Statistical forecast: weight of the latest trend (0-0.9).', 0, 0.9),
    'Tester price USD': ('num', 400000, 'ATE Economics: price of one new consignee tester.', 0, 1e9),
    'Tester running cost USD per month': ('num', 4000, 'ATE Economics: support, calibration and floor cost per tester.', 0, 1e8),
    'Discount rate %': ('num', 8, 'ATE Economics: annual rate for NPV.', 0, 50),
    'Analysis months': ('int', 60, 'ATE Economics: payback analysis period.', 6, 120),
    'Excess threshold weeks': ('num', 13, 'Inventory Health: stock above this many weeks of demand is excess.', 1, 104),
    'Obsolete age months': ('int', 18, 'Inventory Health: date codes older than this are obsolete risk.', 1, 120),
    'SPC sigma': ('num', 3, 'Post-Silicon: control limits at mean ± this many standard deviations.', 1, 6),
    'Capacity buffer %': ('num', 15, 'Tester Capacity: headroom you want above the plan.', 0, 100),
}


# --------------------------------------------------------------------------------------------
# Value coercion and validation
# --------------------------------------------------------------------------------------------
MONTH_RE = re.compile(r'^(\d{4})-(\d{1,2})(?:-\d{1,2})?')


def norm_month(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == '':
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return f'{v.year:04d}-{v.month:02d}'
    m = MONTH_RE.match(str(v).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError('use YYYY-MM')
    return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}'


def norm_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == '':
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return f'{v.year:04d}-{v.month:02d}-{v.day:02d}'
    s = str(v).strip()[:10]
    try:
        d = datetime.strptime(s, '%Y-%m-%d')
    except ValueError:
        try:
            d = pd.Timestamp(s).to_pydatetime()
        except Exception:
            raise ValueError('use YYYY-MM-DD')
    return d.strftime('%Y-%m-%d')


def coerce(value, col):
    """Return (value, error). Empty optional cells become None."""
    t = col['type']
    if isinstance(value, str):
        value = value.strip()
    empty = value is None or value == '' or (isinstance(value, float) and pd.isna(value))
    if empty:
        return None, ('required' if col['required'] else None)
    try:
        if t == 'int':
            f = float(str(value).replace(',', ''))
            if abs(f - round(f)) > 1e-9:
                raise ValueError('whole number')
            v = int(round(f))
        elif t in ('num', 'frac'):
            s = str(value).replace(',', '')
            pct = s.endswith('%')
            v = float(s.rstrip('%'))
            if t == 'frac' and (pct or v > 1) and v <= 100:
                v = v / 100.0          # accept 95 or 95% for a yield
        elif t == 'month':
            v = norm_month(value)
        elif t == 'date':
            v = norm_date(value)
        elif t == 'choice':
            v = str(value).strip()
            match = next((c for c in col['choices'] if c.lower() == v.lower()), None)
            if match is None:
                raise ValueError('one of ' + ', '.join(col['choices']))
            v = match
        else:
            v = str(value)[:120]
    except ValueError as exc:
        msg = str(exc)
        if t in ('int', 'num', 'frac') and ('convert' in msg or 'invalid literal' in msg or not msg):
            msg = 'enter a number' if t != 'int' else 'enter a whole number'
        return value, msg or 'invalid value'
    if t in ('int', 'num', 'frac'):
        if col['lo'] is not None and v < col['lo']:
            return v, f'at least {col["lo"]}'
        if col['hi'] is not None and v > col['hi']:
            return v, f'at most {col["hi"]}'
    return v, None


def setting_col(name):
    typ, _default, _notes, lo, hi = SETTINGS[name]
    if typ.startswith('choice:'):
        return C('Value', 'choice', choices=typ.split(':', 1)[1].split(','))
    return C('Value', typ, lo=lo, hi=hi)


def validate_rows(table: str, rows: list[dict]):
    """Coerce every cell. Returns (clean_rows, errors) where errors = [(row_index, column, message)]."""
    meta = TABLES[table]
    cols = meta['columns']
    clean, errors = [], []
    if len(rows) > MAX_ROWS:
        return [], [(0, '', f'Too many rows ({len(rows):,}). The pilot keeps up to {MAX_ROWS:,} per table.')]
    seen = {}
    for i, raw in enumerate(rows):
        if table == 'settings':
            name = str(raw.get('Setting', '')).strip()
            if name not in SETTINGS:
                errors.append((i, 'Setting', f'unknown setting "{name}"'))
                continue
            v, err = coerce(raw.get('Value'), setting_col(name))
            if err:
                errors.append((i, 'Value', err))
            clean.append({'Setting': name, 'Value': v, 'Notes': SETTINGS[name][2]})
            continue
        if all((raw.get(c['name']) in (None, '') or (isinstance(raw.get(c['name']), float) and pd.isna(raw.get(c['name']))))
               for c in cols):
            continue                                  # skip fully blank rows
        out = {}
        for c in cols:
            v, err = coerce(raw.get(c['name']), c)
            if err:
                errors.append((i, c['name'], err))
            out[c['name']] = v
        key = tuple(str(out.get(k)).upper() for k in meta.get('key', []))
        if meta.get('key'):
            if key in seen:
                errors.append((i, meta['key'][0], f'duplicate of row {seen[key] + 1} ({", ".join(meta["key"])} must be unique)'))
            else:
                seen[key] = i
        clean.append(out)
    if table == 'settings':
        have = {r['Setting'] for r in clean}
        for name in SETTINGS:
            if name not in have:
                typ, default, notes, _, _ = SETTINGS[name]
                clean.append({'Setting': name, 'Value': default, 'Notes': notes})
        order = list(SETTINGS)
        clean.sort(key=lambda r: order.index(r['Setting']))
    return clean, errors


# --------------------------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------------------------
def _path(wsid: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', wsid or ''):
        raise ValueError('bad workspace id')
    return STORE / f'{wsid}.json'


def new_id() -> str:
    return secrets.token_urlsafe(18)


def _cleanup():
    now = time.time()
    try:
        for p in STORE.glob('*.json'):
            if now - p.stat().st_mtime > TTL_SECONDS:
                p.unlink(missing_ok=True)
    except OSError:
        pass


def load(wsid: str):
    try:
        with open(_path(wsid), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save(wsid: str, ws: dict):
    STORE.mkdir(parents=True, exist_ok=True)
    ws['version'] = ws.get('version', 0) + 1
    ws['saved_at'] = datetime.utcnow().isoformat(timespec='seconds')
    tmp = _path(wsid).with_suffix('.tmp')
    with _lock:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(ws, fh, separators=(',', ':'), default=str)
        os.replace(tmp, _path(wsid))
    if secrets.randbelow(20) == 0:
        _cleanup()
    return ws


def demo_workspace():
    from .demo_data import build
    tables = build()
    for name in TABLES:
        tables.setdefault(name, [])
        clean, errors = validate_rows(name, tables[name])
        assert not errors, (name, errors[:3])
        tables[name] = clean
    return {'tables': tables, 'version': 0, 'snapshots': [], 'source': 'Demo data (synthetic)'}


def settings_dict(ws: dict) -> dict:
    out = {name: spec[1] for name, spec in SETTINGS.items()}
    for r in ws['tables'].get('settings', []):
        if r.get('Setting') in out and r.get('Value') is not None:
            out[r['Setting']] = r['Value']
    return out


# --------------------------------------------------------------------------------------------
# Import / export
# --------------------------------------------------------------------------------------------
def frame(ws: dict, table: str) -> pd.DataFrame:
    cols = [c['name'] for c in TABLES[table]['columns']]
    return pd.DataFrame(ws['tables'].get(table, []), columns=cols)


def read_upload(filename: str, data: bytes, sheet: str | None = None) -> dict[str, list[dict]]:
    """CSV -> {None: rows}; Excel -> {sheet_name: rows} for every sheet."""
    name = filename.lower()
    if name.endswith('.csv'):
        for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        return {None: _records(df)}
    if name.endswith(('.xlsx', '.xlsm')):
        book = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=object, keep_default_na=False, na_values=[''])
        return {str(k): _records(v) for k, v in book.items()}
    raise ValueError('Upload a .csv or .xlsx file.')


def _records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how='all')
    out = []
    for rec in df.to_dict('records'):
        out.append({k: (None if (isinstance(v, float) and pd.isna(v)) else
                        (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v)) for k, v in rec.items()})
    return out


def match_columns(table: str, rows: list[dict]):
    """Map uploaded headings to the table's columns, ignoring case/spaces. Returns (rows, missing_required)."""
    cols = TABLES[table]['columns']
    if not rows:
        return [], []
    norm = lambda s: re.sub(r'[^a-z0-9]', '', str(s).lower())
    have = {norm(k): k for k in rows[0].keys()}
    mapping = {c['name']: have.get(norm(c['name'])) for c in cols}
    missing = [c['name'] for c in cols if c['required'] and not mapping[c['name']] and not c['readonly']]
    out = [{c: (r.get(src) if src else None) for c, src in mapping.items()} for r in rows]
    return out, missing


def export_workbook(ws: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    readme = wb.active
    readme.title = 'README'
    head = Font(name='Arial', bold=True, color='FFFFFF')
    fill = PatternFill('solid', fgColor='1F3A5F')
    base = Font(name='Arial', size=10)
    readme['A1'] = 'Plan Yukta workspace'
    readme['A1'].font = Font(name='Arial', bold=True, size=14)
    readme['A2'] = ('One sheet per data table. Edit the values, keep the sheet names and column headings, '
                    'then upload the file on Import / Export to load it into the app. Blue headings are required columns.')
    readme['A2'].font = base
    readme['A2'].alignment = Alignment(wrap_text=True)
    readme.column_dimensions['A'].width = 28
    readme.column_dimensions['B'].width = 26
    readme.column_dimensions['C'].width = 90
    readme.append([])
    readme.append(['Sheet', 'Group', 'What it holds'])
    for c in readme[4]:
        c.font, c.fill = head, fill
    for name, meta in TABLES.items():
        readme.append([name, meta['group'], meta['about']])
        for c in readme[readme.max_row]:
            c.font = base
            c.alignment = Alignment(wrap_text=True, vertical='top')
    for name, meta in TABLES.items():
        sh = wb.create_sheet(name[:31])
        cols = meta['columns']
        sh.append([c['name'] for c in cols])
        for i, c in enumerate(cols, start=1):
            cell = sh.cell(row=1, column=i)
            cell.font = head
            cell.fill = PatternFill('solid', fgColor='1F3A5F' if c['required'] else '6F7F91')
        for r in ws['tables'].get(name, []):
            sh.append([r.get(c['name']) for c in cols])
        for i, c in enumerate(cols, start=1):
            width = max([len(c['name'])] + [len(str(r.get(c['name']) or '')) for r in ws['tables'].get(name, [])[:300]])
            sh.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 48)
            for row in sh.iter_rows(min_row=2, min_col=i, max_col=i):
                row[0].font = base
        sh.freeze_panes = 'A2'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def table_csv(ws: dict, table: str) -> bytes:
    return frame(ws, table).to_csv(index=False).encode('utf-8-sig')
