# How Plan Yukta calculates

Plan Yukta plans a fabless supply chain **backwards from customer demand**, one manufacturing step at a time, at every OSAT. Monthly buckets; month 0 is the plan start month. Every number on every page comes from the data tables and the formulas below.

```
demand ─▶ finished goods ─▶ Pack ─▶ Test 2 ─▶ Test 1 ─▶ Assembly ─▶ Bump ─▶ Sort ─▶ fab outs ─▶ fab wafer starts
                                     └────── tester capacity ──────┘                └ prober capacity ┘
```

## 1. Plan demand

Per product and month, by its **build strategy** (Products):

| Strategy | Plan demand |
|---|---|
| FORECAST | max(customer forecast, booked orders) |
| ORDERS | booked orders (Confirmed + Open) |
| STAT | max(statistical forecast, booked orders) |
| BLEND | max((customer forecast + statistical) ÷ 2, booked orders) |

Then × (1 + demand uplift %). Beyond the last forecast month the plan holds the last value, for lead-time purposes only.

**Statistical forecast.** Holt's linear trend exponential smoothing on monthly shipment history:

- level(t) = α × actual(t) + (1 − α) × (level(t−1) + trend(t−1))
- trend(t) = β × (level(t) − level(t−1)) + (1 − β) × trend(t−1)
- forecast(t + h) = level(t) + h × trend(t), never below 0

**Accuracy** on one-step forecasts over the last 6 months: WMAPE = Σ|actual − forecast| ÷ Σ actual; bias = Σ(forecast − actual) ÷ Σ actual.

## 2. Vendor split

A product is planned at every enabled OSAT that has test times for **all** its test steps (Test times & rates). Volume is split by the OSATs' SharePct, re-normalised over those qualified OSATs.

## 3. Finished goods and safety stock

- Safety-stock target(m) = safety stock weeks × demand(m + 1) ÷ 4.33
- Finished goods needed(m) = demand(m) + target(m) − target(m − 1)
- Finished goods on hand (FG lots in OSAT WIP) are used first, earliest month first.

## 4. Supply already in the line (OSAT WIP)

Each lot is mapped from the vendor's own product code and operation name to a SKU and a standard step (Vendor product codes, Vendor operation names). Lots on HOLD are left out unless the setting says otherwise; unmapped lots are left out and listed in Data checks.

- Output available now at a step = units in process × step yield + units DONE at that step.
- Sort and Bump lots count in wafers (die-level yields: the wafer count does not change). Die bank wafers count as sorted, bumped wafers.
- Tester load now = units waiting at a test step × (1 + retest rate), half of it for lots already running.

## 5. Backward pass, step by step

For each OSAT and product, from Pack back to Sort:

1. Requirement for the step's output, netted against the output already available (section 4), earliest month first.
2. Starts = requirement ÷ step yield (Sort and Bump: wafers, no division).
3. Offset: each step starts `round(cumulative cycle days from the step to shipment ÷ 30.4)` months before the shipment it feeds.
4. Between Assembly and Bump, die become wafers: wafers = die ÷ (GDPW × sort yield × bump yield).
5. A start that falls before month 0 is **inside lead time**: it is made in month 0 and flagged.

Yield overrides (per vendor, from a month) replace the process-flow yield and retest rate from that month on.

## 6. Tester capacity and allocation (Sort, Test 1, Test 2)

**Throughput**

- Final test: seconds per unit = (test time + index time) ÷ sites
- Sort: seconds per wafer = ⌈GDPW ÷ sites⌉ ÷ stepping efficiency × (test time + index) + wafer load time
- Units per tester-month = hours per day × 3600 × OEE × working days per month ÷ seconds per unit

**Load** = starts × (1 + retest rate) + WIP load now (month 0).

**Testers available** = consignee + non-consignee from Tester fleet, plus Tester fleet changes from their month. Non-consignee testers are dropped if "Allow non-consignee testers" = N; consignee testers are capped at the hardware-ready count if "Limit testers to hardware-ready" = Y.

**Allocation**, per OSAT, step and month, in tester-months:

1. Products in priority order (highest first) get the tester time they need: consignee first, then non-consignee.
2. **Pull-in.** For each later shortfall, idle tester time in earlier months builds ahead, latest month first, no more than the pull-in horizon back and never earlier than `fab start offset − step offset` months (material must still be buildable). The amount is capped at min(service level %, max pull-in %) × weight intensity × shortfall.

   **Pull-in weight** (per product, Pull-in Setup) sets the appetite for building ahead:

   | Weight | Strategy | Share of the cap used | Testers it may use |
   |---|---|---|---|
   | −0.10 … −0.08 | Aggressive | 25% + 75% × \|w\| ÷ 0.10 → up to 100% | consignee, then non-consignee |
   | −0.07 … −0.04 | Moderate | 55% – 78% | consignee, then non-consignee from −0.05 |
   | −0.03 … −0.01 | Conservative | 33% – 48% | consignee (own) only |
   | 0 | Neutral | 25% | consignee (own) only |
   | > 0 (up to +0.05) | Avoid | 0%: shortfalls are made late | none |

   The Pull-in Setup preview re-plans the whole supply chain with the slider values and compares total gap, pull-in production, forecast achievement (demand shipped on time ÷ demand), peak build-ahead stock and customer shortfall with the saved settings.
3. **Catch-up.** What is still short is made in the following months with idle tester time; it reaches customers late.

Upstream steps are planned from the starts the testers can actually make, so a tester shortfall reduces material demand upstream instead of piling WIP in front of the tester.

Load % = Σ load ÷ units per tester-month ÷ testers available. Above 85% is tight; above 100% the month cannot be made on time.

## 6a. Overrides: future testers, hardware, test time and yield

Four tables hold dated changes, entered on **Tester & Capacity Overrides**:

| Override | Effect from its month onwards |
|---|---|
| Tester arrivals & removals | consignee / non-consignee testers at an OSAT and step change by ± n |
| Hardware arrivals | in-service hardware of a type changes by ± n; hardware-ready testers = min over types ⌊quantity ÷ per tester⌋ |
| Test time & OEE changes | test time, sites, index time and/or OEE for a product at an OSAT are replaced, so units per tester-month change |
| Yield changes | yield and retest rate for a product, OSAT and step are replaced |

Each override applies to its own month and every later month. When two overrides of the same kind fall in the same month for the same resource, adding the second replaces the first. Allocation, pull-in and catch-up (section 6) run on the capacity of each month after overrides, so a tester arriving in July changes how much is built ahead in March to June.

**Baseline.** The same plan with all four tables ignored. The overrides page shows both plans side by side: testers, load %, pull-in, units made late, customer shortfall and revenue lost. The setting "Apply overrides" = N makes every module show the baseline.

**Build-ahead stock** (Pull-in & Service Level page) = cumulative (made − needed) at a test step, when positive, converted to good units: ÷ (1 + retest) × yield. **Still owed** = cumulative shortfall not yet caught up.

## 7. Fab wafers

- Wafers needed at sort, per product, = Σ over OSATs of Sort starts, moved earlier by the fab-to-OSAT transit.
- Fab WIP arrives in the month of its expected out date + transit. It first covers needs that are already late, then the current month.
- A need new starts can still meet is ordered `round((cumulative OSAT days + transit + fab cycle weeks × 7) ÷ 30.4)` months before shipment; one they cannot meet is backlogged until WIP arrives, or until starts placed in month 0 arrive. Those wafers are listed under **Expedite**.
- Wafer starts are rounded up to whole lots (Wafer lot size); the rounding extra carries forward.
- Starts above "Fab capacity wafers per month" are flagged.

## 8. Shipments and customer shortfall

Every shortfall (tester gap, inside lead time, late wafers) is converted to finished units through the yields after it, at the shipment month it would have fed. Then, month by month:

- Available = finished goods on hand + pack output (after shortfalls)
- Shipped = min(demand + backlog, available); backlog = what is still owed
- Finished goods end of month = available − shipped

Safety stock absorbs a shortfall before a customer sees it.

## 9. Available to promise

- Supply(bin, m) = FG on hand in that bin + Σ planned pack output × bin fraction, cumulative to month m
- ATP(m) = min over t ≥ m of [cumulative supply(t) − cumulative reservations(t)]
- An order line is checked against the shippable matrix (accepted bins, MOQ round-up), then promised from the OSATs with the most ATP on the requested date, and any remainder in the first later month with ATP.

## 10. Purchase orders

- **FAB:** one line per product and wafer-start month. Order cutoff = Fab order cutoff day of the month before the start; capacity reservation (semi-cutoff) = Fab semi-cutoff day two months before. Status from the as-of date: PAST CUTOFF, ORDER NOW (after the semi-cutoff), UPCOMING (within 14 days of it), PLANNED.
- **OSAT:** one line per OSAT, product and month with every step's quantity; same rule with the OSAT cutoff days.
- XML downloads are simplified RosettaNet-style forecast (PIP 4A3-like) and purchase-order (PIP 3A4-like) messages, for illustration.

## 11. Substrate and lead frame

Need = die into assembly, for products whose SubstrateType is not None. Batches are used first-in first-out from their arrival month, skipped after their expiry month, and written off if they expire unused. Shortfall severity: CRITICAL ≥ 50% of the month's need, HIGH ≥ 25%, else MEDIUM.

## 12. Cost and P&L

- **Spend** = wafer starts × wafer price + sort wafers × sort rate + bump wafers × bump price + assembly units × assembly price + test insertions × test rate (consignee or non-consignee by the testers used) + pack units × pack price.
- **Standard cost per good unit**: wafer price ÷ (GDPW × all yields), plus each step's price ÷ the product of yields from that step to finished goods (test steps × (1 + retest)). Test rates are blended by the plan's share of non-consignee units.
- **P&L**: revenue = shipped units × ASP (booked orders at each customer's price, the rest at the default price "*"); COGS = shipped units × standard cost (× yield-loss sensitivity); gross margin = revenue − COGS. Revenue lost = units short × default ASP.

## 13. Hardware, ATE economics, NPI, plan vs actual

- **Hardware-ready testers** = min over hardware types of ⌊(in service + on order once arrived) ÷ per tester⌋.
- **ATE economics**: units moved = min(average non-consignee units per month, new testers × units one tester makes for the current product mix); monthly saving = units moved × (non-consignee − consignee rate) − testers × running cost; payback = price × testers ÷ monthly saving; NPV = −price × testers + Σ saving ÷ (1 + r/12)^t.
- **NPI**: samples ready = NPI start + fab cycle + transit + Σ OSAT cycle days; qualification end = samples + Σ (cycle + readout days); risk when qualification ends after the first month with demand. Each milestone has a Status (Planned / Running / Passed / Failed) and an ActualEnd date: an ActualEnd replaces the planned readout and every later milestone re-plans from it; a Running milestone past its planned readout cannot finish before the as-of date; a Failed milestone flags the product at risk until a re-test milestone is added.
- **Plan vs actual**: attainment = actual ÷ frozen plan; OEE = availability × performance × quality; reliability score = 50% attainment (capped at 100) + 30% OEE + 20% (100 − disruption days ÷ 30.4 × 100).

## 14. Cross flow

Moved quantity = step output at the source OSAT × rule %; logistics cost = moved ÷ 1,000 × cost per 1,000. Active rules from one OSAT and step must not exceed 100%. Cross flow is an overlay in the pilot: the tester plan does not re-route the load.

## 15. Dashboards

- **Module 1 Dashboard:** production by OSAT and product, gap vs pull-in by month, cumulative forecast / demand / shipments, tester-months used. Recovery action for a short month: if another OSAT qualified for the product has idle testers covering at least 30% of the gap, move the load there; otherwise add ⌈gap ÷ units per tester-month⌉ testers. Vendor split optimisation spreads each product's Test 1 shortfall over OSATs with idle capacity in the short months, in proportion to that capacity.
- **Module 4 Dashboard:** output (Pack) by OSAT and product, starts by process and month, OSAT wafer starts against fab starts, fill rate by product.

## 16. Vendor QBR scorecard

Per enabled OSAT, over the review period (last 3 months of actuals, or a quarter):

| Category | Measure | Score |
|---|---|---|
| Quality | average of test yield ÷ planned yield (Σ passed ÷ Σ tested × base yield, capped at 100%) and average reported QualityPct | 100 at or above target, −5 points per % below |
| Delivery | Σ min(actual, plan) ÷ Σ plan, from Vendor actuals and the frozen plan | same |
| Cost | price index: for every step and product quoted by two or more OSATs (OSAT price list, consignee test rate), lowest price ÷ this OSAT's price × 100, averaged | same |
| Capacity | (planned test load − units still short after pull-in) ÷ planned test load over the horizon | same |
| Responsiveness | average days from Opened to Closed | 100 at or under target days, −3 per day over; −10 per overdue open issue, −15 per open critical issue |

Total = Σ score × weight ÷ Σ weights of the categories with data (QBR scorecard weights). Grade A ≥ 90, B ≥ 80, C ≥ 70, D below. The monthly trend recomputes quality and delivery for each month. Any category under 90 goes onto the QBR agenda with the measure behind it. The QBR pack (Excel) keeps weights and category scores as inputs and the total and grade as live formulas.

## 17. Customer rating

From Agreed-order history, by agreed quantity: pushed out % = pushed-out agreed qty ÷ total agreed; cancelled % likewise; reduced % = Σ(agreed − actual) on reduced orders ÷ total agreed; taken as agreed % = accepted + pulled-in agreed qty ÷ total agreed.

Score = 100 − (pushed out % × 0.6 + cancelled % × 1.0 + reduced % × 0.8). Excellent ≥ 95 (commit fully), Good ≥ 85 (commit, review monthly), Fair ≥ 70 (firm PO before building beyond the frozen months), Risk below (build to firm PO; NCNR terms or deposit).

Open orders (Customer orders not cancelled, from the plan start) at risk = open units × (pushed out % + cancelled % + reduced %) ÷ 100; revenue at risk uses each customer's ASP.

## 18. Post-silicon (test data) analysis

- **Lot yield** = Σ passed ÷ Σ tested over the lot's wafers at the step.
- **Control limits**: centre = median lot yield; σ = 1.4826 × median absolute deviation; limits = centre ± k·σ, k = SPC sigma (Plan settings). Robust statistics keep an excursion from widening its own limits.
- **Failure signature**: for a lot below the LCL, the fail bin whose share of the lot's fails is furthest above its share across all lots. 15 points or more above normal = a single failure mode (hardware or assembly); otherwise the loss is spread across bins (a process or material shift).
- **Tester outlier**: tester yield ≥ 1.5 points below the other testers at the same OSAT over 3 or more lots. Lots with a single-failure-mode signature are excluded from this comparison.
- **Sustained shift**: mean of the last 5 lots at an OSAT more than 2 points below the plan yield.
- **Use in plan**: adds a Yield override (product, OSAT, step, from the plan start month) at the last-5-lot mean. **Update bin splits** replaces the product's bin fractions with the actual pass-bin mix.
- **Test-data API**: `POST /api/v1/test-results` with `Authorization: Bearer <token>` (shown on the page, an HMAC of the workspace id) and JSON `{"results": [...], "bins": [...]}` using the table column names. Rows replace existing rows with the same key; validation is the same as an upload; up to 5,000 rows per list.

## 19. Inventory health

- **FG-equivalent** of a lot = quantity × yields of the steps still to come (wafer stages: wafers × GDPW × every yield).
- **Value** = FG-equivalent × standard cost of the completed steps (section 12); cost complete % = completed ÷ total standard cost.
- **Days of supply**: walk the plan demand month by month (working days per month) until the stock is used up.
- **Excess** = FG + WIP FG-equivalent − demand over (Excess threshold weeks + the product's total cycle time); valued at finished-goods standard cost first, then at the WIP average.
- **Aging** from the YYWW date code (ISO week): 0–3, 3–6, 6–12, 12+ months, and obsolete risk above Obsolete age months.

## 21. Portfolio and roadmaps

Monthly buckets from the plan start for "Portfolio horizon months"; quarters follow "Portfolio quarter start month".

- **Capacity**: headcount[pool, m] = FTE + Σ capacity changes from their month. Demand[pool, m] = Σ project FTE whose From ≤ m ≤ To. Utilisation = demand ÷ headcount; target capacity = headcount × target utilisation.
- **Investment**: FTE-years = Σ FTE × months ÷ 12 over each demand row; cost = FTE-years × pool cost per FTE-year.
- **Priority score**: criteria on 1-5 — value scaled across live projects (1 + 4 × (v − min) ÷ (max − min)), strategic fit, customer demand, time criticality, and 6 − technical risk. Score = Σ criterion × weight ÷ Σ weights × 20.
- **Funding line**: committed projects load capacity first. Proposed projects in score order are tried at start shifts of 0-12 months; the first shift where every pool-month stays at or below target capacity is kept ("Fits now" or "Fits if k months later") and its demand is added; otherwise "Above the line".
- **Forecast release** = G5 Release forecast (or planned) date. **Dependency margin** = To's forecast release − (From's forecast release + lag); below 0 = conflict.
- **Health** (worst of four): Schedule red if any open gate forecast slips more than 2 months or is overdue, amber for any slip; Capacity red if the project draws on a pool more than 5% over target in 4+ months, amber 1+; Risk red for an open RAID item with P×I ≥ 15, amber ≥ 9; Dependencies red on a conflict.
- **Capacity ask** per quarter and pool = max over its months of (demand − target capacity), costed at the pool cost ÷ 4.
- **Gate recommendation**: no readiness = assess first; Approve when readiness ≥ 85% and no open issue (capacity counts only for G1 and G2 of proposed projects; high risk; dependency conflict); Approve with conditions at ≥ 70%; otherwise Defer. Recording a decision sets the gate status (Passed, Conditional, Deferred, Failed), adds a decision-log row, and an approved G1/G2 makes the project Committed.
- **Scenarios** apply in Seq order: Delay months (dates, open gates and demand), Stop, Fund, Scale demand %, Add FTE (a capacity change from a month).
- **Roadmap to silicon**: a project's LinkedSKU is checked against NPI Management's qualification date; the need date is the earlier of its own release and (dependent release − lag).
- **Jira sync**: epics from the JQL plus every project's JiraKey; children by `parent = KEY`, counted by status category. **Confluence**: the board pack is created or updated (next version) as one page in the space.

## 21a. FTE ramp-up, productivity and capacity risk

- **Ramp factor** of a cohort in its k-th month (k = 0 first month) = start + (steady − start) × min(1, k ÷ ramp months), from FTE ramp-up profiles by type. Capacity changes map to types: Hiring plan → Permanent hire, Contractors → Contractor, Partner → Partner, Transfer → Transfer; scenario Add FTE → Contractor, Hire FTE → Permanent hire. Leavers (negative changes) leave at full output.
- **Levers** apply to cohorts joining from their From month (Shorter ramp: ramp months − value; Higher start factor: start + value, capped at steady) or to the whole pool from that month (Productivity uplift %). Which statuses count is set in Plan settings.
- **Effective FTE** = (existing FTE + Σ cohort FTE × factor) × (1 + Σ uplift). With ramp-up on, every capacity, funding, scenario and board result uses effective FTE; headcount is shown alongside.
- **FTE-months lost per new person** = Σ over the ramp months of (steady − factor). Lever gain = effective FTE-months with the lever alone − without any lever; worth = gain × pool cost per FTE-month.
- **Covering a gap**: people needed = gap FTE ÷ factor in the gap month after the option's lead time (permanent: pool hiring lead; contractor 1 month; partner 2; transfer 1); 12-month cost = people × pool cost × (1 + premium).
- **Attrition drag** (risk-adjusted plan) = FTE × attrition % ÷ 12 × (hiring lead months + ramp months × (steady − (start + steady) ÷ 2)), taken off the pool from the plan start.
- **Risk register**: attrition (P from the rate, I from the risk-adjusted peak gap ÷ pool FTE: ≥ 8% = 5, ≥ 4% = 4, ≥ 1.5% = 3); hiring lead time (requisitions must open by first over-target month − hiring lead − months to 80% output; already past = P5); ramp-up timing (a cohort below its steady output in an over-target month); contractor dependency (≥ 15% of effective capacity); site concentration (≥ 80% in one country); burnout (4+ consecutive months at or near target); key person (a key role with no backup; impact 5 on committed projects scoring ≥ 70).
- **Stress tests**: attrition multiplier, hiring freeze (Hiring plan rows removed), contractors and partners leaving from a month, and losing a country's share of every pool from a month.

## 22. Data checks

Errors and warnings that change or stop the plan: products without a flow or without qualified OSATs, test times without testers, bin fractions that do not add up to 1, unmapped WIP lots, missing prices, cross-flow rules over 100%, references to unknown products or vendors, test results that pass more than they test, closed issues without dates, NPI milestones past their readout without a status, QBR weights that do not add up to 100, portfolio rows that name unknown projects or pools, demand rows that end before they start, and projects that launch before they start.

---

# Lot-level WIP audit (upload page)

The audit page works on raw supplier reports, lot by lot, independently of the planning modules. It turns the foundry WIP and shipment files and the OSAT daily WIP report into one de-duplicated view of where every wafer and die is.

### Audit inputs

| Sheet | One row per | Key columns |
|---|---|---|
| Settings | setting | As-of date, E&O age threshold (months), E&O bin baseline, capacity tolerance |
| Products | master product | Gross die per wafer (GDW) |
| Name_Map | name used by a supplier | Name, source (FAB or OSAT), master product |
| Fab_WIP | foundry lot | Fab product, lot ID, current stage, current qty (wafers), start / committed / projected-out dates |
| Fab_Shipments | shipment line | Ship date, fab product, lot ID, unit (WF = wafers), quantity |
| OSAT_WIP | OSAT report row | Snapshot date, MAIN, OPER, STATE, part name, customer lot, wafer qty, die qty, wafer IDs, date code, bin/location |

The **mother lot** is the first six characters of a lot number. It ties a foundry lot to every OSAT sub-lot made from it.

### A1. Product mapping

Every supplier name is mapped to a master product through Name_Map. When one OSAT name belongs to more than one product (a bare family name, for example), the row is assigned to the single product whose foundry lots share its mother lot. If no single product owns that mother lot, the row is reported as **UNRESOLVED** rather than guessed.

### A2. Fab WIP

Fab WIP wafers = Σ Current Qty, where Current Stage ≠ SHIPPED

Shipped lots still listed on the WIP report are excluded, so they are not counted twice with fab shipments. The pilot also lists **late fab lots**: lots where Projected Out Date − Committed Date > 0 days.

### A3. Fab shipments

Wafers shipped = Σ Ship Qty, where UM = WF

Lines in other units (for example LT, a lot count) are ignored.

### A4. OSAT WIP by operation

| Operation | Rows | Quantity |
|---|---|---|
| Sort (CP) | MAIN = CP | Σ WAFER_QTY |
| Bump | MAIN = BUMP | Σ WAFER_QTY |
| Assembly | MAIN = ASSY | Σ DIE_QTY |
| Testing (FT) | MAIN = FT, OPER ≠ IP, bin not BIN1/GOOD | Σ DIE_QTY |
| Packing | MAIN = FT and (OPER = IP or bin is BIN1/GOOD) | Σ DIE_QTY |

These figures come from the latest snapshot, after de-duplication (rule A5).

### A5. OSAT de-duplication
*`osat_transfer_dedup.prepare_osat_dataframe`, used here unchanged*

OSAT reports often list the same wafers more than once while material moves between stages. Five rules remove the extra rows, and each removed row is logged with its rule and reason.

1. **History wafer location.** When a wafer (mother lot + wafer IDs) appears under two MAIN stages, earlier snapshots decide which stage it is really in.
2. **Cross-stage wafer location.** Within one snapshot, an active row beats a TRANSFER row, and an active row beats a FINISH row.
3. **Same-stage transfer duplicate.** In Sort or Bump, a TRANSFER row is dropped when the same wafers also have a live row in that stage.
4. **Stale Sort transfer.** A Sort TRANSFER row is dropped when its mother lot is already in Final Test.
5. **Finished rows.** A FINISH/DONE row is dropped when the same wafer or mother lot is live elsewhere, or live in a later stage.

### A6. Final-test binning

Testing and Packing die quantities are grouped by LOCATION (bin), with each bin's share of the total.

### A7. Excess & obsolete (E&O)

A row is E&O if either condition holds:

- Its YYWW date code is older than (as-of date − months × 30 days).
- Its bin number is above the baseline bin.

Sort and Bump are counted in wafers; all other operations in dies.

### A8. Gross-die capacity check

Active die equivalent = (Sort + Bump wafers) × GDW + Assembly + Testing + Packing dies

Capacity = wafers shipped from fab × GDW × tolerance

The check flags **OVER CAPACITY** when the active die equivalent exceeds capacity. That cannot happen physically, so it means something is wrong: rows counted twice, a missing fab shipment, or a wrong GDW. A low active figure is not flagged, because material may already have shipped or been scrapped.

### A9. Lot lead time

For each mother lot and stage (Fab, Sort, Bump, Assembly, Testing, Packing):

- **Process days** = last snapshot in stage − first snapshot in stage. For the Fab stage, this is ship date − wafer start date.
- **Wait days** = start of stage − end of the previous stage. Wait before the first OSAT stage is counted from the fab ship date.
- **Lead time** = Σ process days + Σ wait days.

If the lead time comes out longer than the time since the lot started, every stage is scaled down to fit, and the lot is marked as scaled. 

Lead times are measured in whole days between snapshots, so daily snapshots give daily resolution.


### Not in the audit

Test yield databases, work-order scrap, OSAT packing lists, commercial invoices and e-mail alerts need live system connections and are not part of the pilot.
