# Plan Yukta pilot

A planning cockpit for fabless semiconductor supply chains. All modules sit in a sidebar, every module reads the same data tables, and visitors can edit any table in the browser. Save a change and the whole plan recalculates.

The demo data is synthetic: products (ORION, VEGA, LYRA, ATLAS, NOVA), vendors (OSAT-A/B/C), customers, lots and prices are invented.

## Modules

| Group | Module | What it does |
|---|---|---|
| | Cockpit | KPIs, plan flow for any month, tester load heatmap, alerts |
| Planning | Demand & Forecast | Customer forecast, orders, Holt statistical forecast, build strategy per product |
| | M1 · Testing Starts | Final-test starts per OSAT, tester allocation (consignee first), pull-in, catch-up |
| | ↳ Dashboard | Module 1 analytics: gap vs pull-in, cumulative achievement, root cause, recovery plan, vendor split optimisation |
| | ↳ Pull-in Setup | Pull-in weight, service level and cash-cap sliders with live preview; build-ahead plan and stock by process |
| | M2 · Assembly Starts | Die into assembly and sorted wafers, netted against WIP |
| | M3 · Front End & Wafers | Bump and sort starts, prober capacity, fab WIP netting, wafer starts in lots |
| | M4 · Complete Flow | Every product × OSAT × month from wafer start to customer shipment |
| | ↳ Dashboard | Output by OSAT and product, starts by process, wafers, fill rate |
| | M5 · Available to Promise | Order check by bin and MOQ, reservations, cumulative ATP |
| Capacity & engineering | Tester & Capacity Overrides | Future tester arrivals, hardware deliveries, test-time / sites / OEE and yield changes by month; plan with vs without them |
| | Tester Capacity | Load and utilisation by OSAT, step and month; throughput per product |
| | Hardware Readiness | Sockets, load boards, probe cards against the consignee fleet |
| | ATE Economics | Buy or rent: payback, NPV and ROI for 1–4 new testers, capacity slack |
| | NPI Management | Engineering lot timeline, qualification Gantt, risk against first demand |
| Procurement & B2B | FAB PO Schedule | Wafer POs with cutoff and reservation dates, expedite list, XML |
| | OSAT PO Schedule | Monthly work orders and cost per OSAT, XML |
| | Substrate & Lead Frame | FIFO with expiry against the assembly plan |
| | Cross Flow | Inter-OSAT moves, cost and rule checks (overlay) |
| | Monthly B2B Package | Time-fenced supplier forecasts, REQUEST / COMMIT / GAP workbook |
| Analytics & monitoring | Plan vs Actual | Attainment, OEE, reliability score, recovery actions |
| | Snapshot Comparison | Save the plan, change data, see what moved |
| | Cost Planning | Spend by supplier and process; standard cost roll-up through yields |
| | Profit & Loss | Revenue, COGS and margin by product and customer; lost revenue |
| | OSAT WIP Snapshot | Vendor codes mapped to SKUs and steps; holds you can release |
| | Lot-level WIP Audit | Upload raw fab and OSAT reports to de-duplicate rows and measure lead times |
| Data & setup | Data Tables | 28 editable tables, CSV/Excel upload and download per table |
| | SKU Setup Wizard | Clone a product into every table in one step |
| | Data Checks | Problems that change or stop the plan |
| | Import / Export | Whole workspace as one Excel workbook, up and down |

Every formula is in [CALCULATIONS.md](CALCULATIONS.md), also shown in the app under **How It Calculates**.

## Code

| Path | What it is |
|---|---|
| `app.py` | Flask routes: pages, data editing, uploads, ATP, snapshots, exports, chat, access codes |
| `plan_yukta/workspace.py` | Table catalogue, validation, per-visitor workspace storage, Excel import/export |
| `plan_yukta/demo_data.py` | The synthetic demo dataset |
| `plan_yukta/cockpit.py` | Planning engine: backward pass, tester allocation, fab, FG, and every module's results |
| `plan_yukta/views.py` | Page builders (KPIs, charts, month grids, tables) |
| `plan_yukta/charts.py` | Server-rendered SVG charts |
| `plan_yukta/modules.py` | Sidebar, module descriptions, demo tour |
| `plan_yukta/exports.py` | B2B workbook, XML messages, full plan workbook |
| `plan_yukta/assistant.py` | "Ask Plan Yukta" chat (help search, or Claude if `ANTHROPIC_API_KEY` is set) |
| `plan_yukta/engine.py`, `osat_transfer_dedup.py`, `audit_view.py` | Lot-level WIP audit |
| `templates/`, `static/` | Pages, styles (dark and light), scripts, audit template and sample |

## Run locally

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

## Deploy on Render

`render.yaml` is a Blueprint. Every push to `main` redeploys. Set `PILOT_ACCESS` to `name:code` pairs for invited testers (empty = open). Optional: `FEEDBACK_URL`, `ANTHROPIC_API_KEY`.

Workspaces are small JSON files in `/tmp` (one per browser session, deleted after 24 hours). On Render's free instance they also disappear when the service restarts; testers keep their work by downloading the workspace from Import / Export.
