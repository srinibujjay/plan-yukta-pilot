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
| | NPI Management | Engineering lot timeline, qualification Gantt with milestone status and actual dates, risk against first demand |
| Procurement & B2B | FAB PO Schedule | Wafer POs with cutoff and reservation dates, expedite list, XML |
| | OSAT PO Schedule | Monthly work orders and cost per OSAT, XML |
| | Substrate & Lead Frame | FIFO with expiry against the assembly plan |
| | Cross Flow | Inter-OSAT moves, cost and rule checks (overlay) |
| | Monthly B2B Package | Time-fenced supplier forecasts, REQUEST / COMMIT / GAP workbook |
| Vendors, customers & quality | Vendor QBR & Issues | OSAT ranking on quality, delivery, cost, capacity, responsiveness; QBR agenda and Excel pack; 8D issues log |
| | Customer Rating | How reliably each customer takes agreed orders; commit policy; risk-adjusted open orders |
| | Post-Silicon Analysis | Lot yield control chart, failure signatures, tester outliers, fail-bin Pareto, bin split; push results by API; feed yields into the plan |
| Portfolio & roadmaps | Portfolio Overview | Executive summary, investment by BU and category, value vs priority, capacity heatmap, portfolio health |
| | ↳ Roadmap | Swimlane roadmap with gates, slips and dependencies; roadmap vs Jira; roadmap to silicon (links to the supply plan) |
| | ↳ Resource Requests | Demand intake: soft and hard booking, recommendations, decision cycle time |
| | ↳ Capacity vs Demand | Engineering FTE by skill pool vs project demand, hires and attrition, capacity asks |
| | ↳ FTE Ramp & Productivity | New people from about 0.5 to 1.0 FTE: ramp curves, output lost, a month-by-month onboarding plan, productivity levers, hire vs contract |
| | ↳ Capacity Risk Management | Attrition, hiring lead time, ramp-up, contractor, site and key-person risks; stress tests by attrition, hiring freeze, contractor exit, country loss |
| | ↳ Prioritisation & Funding Line | Value-based score and a capacity-driven funding line with earliest start per proposal |
| | ↳ Scenario Planner | Delay, stop, fund, scale demand, add FTE; compare with baseline; save scenarios |
| | ↳ Stage Gates & Portfolio Board | Gate recommendations, decisions, decision log, board pack (Excel, Confluence) |
| | ↳ RAID & Dependencies | Risk heatmap, RAID log, dependency checks |
| | ↳ Operating Model | Operating model, planning cadence, RACI, roadmap standards (decision-ready score), investment balance, planning KPIs |
| | ↳ Jira & Confluence | Pull epic status from Jira Cloud, publish the board pack to Confluence Cloud |
| Learn & practice | Role Capability Map | Each responsibility and skill of a portfolio and product planning director role, mapped to a page, live evidence and a talking point |
| | Daily Practice | A new daily set: concept, live data drill, leadership question, executive narrative; timer and streak |
| | ERM & Portfolio Glossary | Enterprise resource and portfolio management vocabulary, linked to where it lives |
| Analytics & monitoring | Plan vs Actual | Attainment, OEE, reliability score, recovery actions |
| | Inventory Health | WIP and FG at standard cost, days of supply, excess, date-code aging and obsolete risk |
| | Snapshot Comparison | Save the plan, change data, see what moved |
| | Cost Planning | Spend by supplier and process; standard cost roll-up through yields |
| | Profit & Loss | Revenue, COGS and margin by product and customer; lost revenue |
| | OSAT WIP Snapshot | Vendor codes mapped to SKUs and steps; holds you can release |
| | Lot-level WIP Audit | Upload raw fab and OSAT reports to de-duplicate rows and measure lead times |
| Data & setup | Data Tables | 48 editable tables, CSV/Excel upload and download per table |
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
| `plan_yukta/insights.py` | Vendor QBR scorecard, customer rating, post-silicon analysis, inventory health |
| `plan_yukta/portfolio.py`, `pf_views.py`, `portfolio_demo.py` | Portfolio engine, pages and demo portfolio |
| `plan_yukta/learn.py` | Capability map, daily practice drills and glossary |
| `plan_yukta/workforce.py` | FTE ramp-up economics, levers, hire vs contract, stress tests, capacity risk register |
| `plan_yukta/integrations.py` | Jira and Confluence Cloud connectors and the board pack |
| `plan_yukta/views.py` | Page builders (KPIs, charts, month grids, tables) |
| `plan_yukta/charts.py` | Server-rendered SVG charts |
| `plan_yukta/modules.py` | Sidebar, module descriptions, demo tour |
| `plan_yukta/exports.py` | B2B workbook, XML messages, full plan workbook |
| `plan_yukta/assistant.py` | "Ask Plan Yukta" chat (help search, or Claude if `ANTHROPIC_API_KEY` is set) |
| `plan_yukta/engine.py`, `osat_transfer_dedup.py`, `audit_view.py` | Lot-level WIP audit |
| `templates/`, `static/` | Pages, styles (dark and light), scripts, audit template and sample |

## Test-data API

`POST /api/v1/test-results` takes `{"results": [...], "bins": [...]}` (column names as in the Test results and Test bin counts tables) with `Authorization: Bearer <token>`. The token is shown on Post-Silicon Analysis and belongs to that browser's workspace. It is a generic JSON endpoint for an export job from a yield-analytics tool, an OSAT feed or a script; it is not a connector to any specific product.

## Run locally

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

## Deploy on Render

`render.yaml` is a Blueprint. Every push to `main` redeploys. Set `PILOT_ACCESS` to `name:code` pairs for invited testers (empty = open). Optional: `FEEDBACK_URL`, `ANTHROPIC_API_KEY`, and for a permanent Atlassian connection `ATLASSIAN_SITE`, `ATLASSIAN_EMAIL`, `ATLASSIAN_TOKEN`, `CONFLUENCE_SPACE`, `JIRA_EPIC_JQL`.

Workspaces are small JSON files in `/tmp` (one per browser session, deleted after 24 hours). On Render's free instance they also disappear when the service restarts; testers keep their work by downloading the workspace from Import / Export.
