# What Plan Yukta calculates

Plan Yukta turns the reports a fabless company already receives — the foundry's WIP and shipment files and the OSAT's daily WIP report — into one view of where every wafer and die is, by product. Each calculation below names the function in the main dashboard code it mirrors, so the pilot can be checked against it.

## Inputs

| Sheet | One row per | Key columns |
|---|---|---|
| Settings | setting | As-of date, E&O age threshold (months), E&O bin baseline, capacity tolerance |
| Products | master product | Gross die per wafer (GDW) |
| Name_Map | name used by a supplier | Name, source (FAB or OSAT), master product |
| Fab_WIP | foundry lot | Fab product, lot ID, current stage, current qty (wafers), start / committed / projected-out dates |
| Fab_Shipments | shipment line | Ship date, fab product, lot ID, unit (WF = wafers), quantity |
| OSAT_WIP | OSAT report row | Snapshot date, MAIN, OPER, STATE, part name, customer lot, wafer qty, die qty, wafer IDs, date code, bin/location |

The **mother lot** is the first six characters of a lot number. It ties a foundry lot to every OSAT sub-lot made from it.

## 1. Product mapping
*`get_master_customer_products`, `get_confirmed_lots_from_fab1`*

Every supplier name is mapped to a master product through Name_Map. When one OSAT name belongs to more than one product (a bare family name, for example), the row is assigned to the single product whose foundry lots share its mother lot. If no single product owns that mother lot, the row is reported as **UNRESOLVED** rather than guessed.

## 2. Fab WIP
*`get_fab1_wip_data`, `_finalize_fab1_wip_result`*

Fab WIP wafers = Σ Current Qty, where Current Stage ≠ SHIPPED

Shipped lots still listed on the WIP report are excluded, so they are not counted twice with fab shipments. The pilot also lists **late fab lots**: lots where Projected Out Date − Committed Date > 0 days.

## 3. Fab shipments
*`get_fab1_past_shipment_data`*

Wafers shipped = Σ Ship Qty, where UM = WF

Lines in other units (for example LT, a lot count) are ignored.

## 4. OSAT WIP by operation
*`get_operation_data`, `_filter_osat_operation_dataframe`*

| Operation | Rows | Quantity |
|---|---|---|
| Sort (CP) | MAIN = CP | Σ WAFER_QTY |
| Bump | MAIN = BUMP | Σ WAFER_QTY |
| Assembly | MAIN = ASSY | Σ DIE_QTY |
| Testing (FT) | MAIN = FT, OPER ≠ IP, bin not BIN1/GOOD | Σ DIE_QTY |
| Packing | MAIN = FT and (OPER = IP or bin is BIN1/GOOD) | Σ DIE_QTY |

These figures come from the latest snapshot, after de-duplication (section 5).

## 5. OSAT de-duplication
*`osat_transfer_dedup.prepare_osat_dataframe`, used here unchanged*

OSAT reports often list the same wafers more than once while material moves between stages. Five rules remove the extra rows, and each removed row is logged with its rule and reason.

1. **History wafer location.** When a wafer (mother lot + wafer IDs) appears under two MAIN stages, earlier snapshots decide which stage it is really in.
2. **Cross-stage wafer location.** Within one snapshot, an active row beats a TRANSFER row, and an active row beats a FINISH row.
3. **Same-stage transfer duplicate.** In Sort or Bump, a TRANSFER row is dropped when the same wafers also have a live row in that stage.
4. **Stale Sort transfer.** A Sort TRANSFER row is dropped when its mother lot is already in Final Test.
5. **Finished rows.** A FINISH/DONE row is dropped when the same wafer or mother lot is live elsewhere, or live in a later stage.

## 6. Final-test binning
*`get_binning_breakdown`*

Testing and Packing die quantities are grouped by LOCATION (bin), with each bin's share of the total.

## 7. Excess & obsolete (E&O)
*`get_eo_data`*

A row is E&O if either condition holds:

- Its YYWW date code is older than (as-of date − months × 30 days).
- Its bin number is above the baseline bin.

Sort and Bump are counted in wafers; all other operations in dies.

## 8. Gross-die capacity check
*`wip_regression.validate_gross_die_capacity`*

Active die equivalent = (Sort + Bump wafers) × GDW + Assembly + Testing + Packing dies

Capacity = wafers shipped from fab × GDW × tolerance

The check flags **OVER CAPACITY** when the active die equivalent exceeds capacity. That cannot happen physically, so it means something is wrong: rows counted twice, a missing fab shipment, or a wrong GDW. A low active figure is not flagged, because material may already have shipped or been scrapped.

## 9. Lot lead time
*`get_lot_travel_history`*

For each mother lot and stage (Fab, Sort, Bump, Assembly, Testing, Packing):

- **Process days** = last snapshot in stage − first snapshot in stage. For the Fab stage, this is ship date − wafer start date.
- **Wait days** = start of stage − end of the previous stage. Wait before the first OSAT stage is counted from the fab ship date.
- **Lead time** = Σ process days + Σ wait days.

If the lead time comes out longer than the time since the lot started, every stage is scaled down to fit, and the lot is marked as scaled. This matches the dashboard's sanity check.

Lead times are measured in whole days between snapshots, so daily snapshots give daily resolution.

## Differences from the dashboard

- The pilot uses the **as-of date** from Settings, where the dashboard uses today's date. Results are therefore reproducible.
- The dashboard decides which OSAT part names are ambiguous from a hard-coded list of names. The pilot works this out from Name_Map: any OSAT name mapped to more than one product is ambiguous.
- For lead times, the pilot runs the same-snapshot de-duplication rules on every snapshot. A leftover TRANSFER row therefore does not stretch a stage the lot has already left.
- Work-order evidence is not available in the pilot. It only changes the wording of one audit reason, not which rows are removed.

## Not in the pilot

- Test yield from Yielddb.
- Work-order scrap.
- OSAT shipment packing lists.
- The dashboard's tester reservation calendar and its e-mails. The pilot plans tester capacity instead; see section 12.
- Commercial invoices.
- The document system.
- Email alerts.

All of these need live connections or the dashboard's database.

---

# Planning modules

The planning modules run on the template's **Demand**, **Plan_Params**, **Tester_Params** and **Tester_Capacity** sheets, together with the planning rows on **Settings**. They use buckets of one calendar month, and 1 month counts as 52 ÷ 12 = 4.33 weeks.

## 10. Demand forecast

**Statistical forecast.** Holt linear exponential smoothing on monthly ACTUAL shipments:

- level(t) = α × actual(t) + (1 − α) × (level(t−1) + trend(t−1))
- trend(t) = β × (level(t) − level(t−1)) + (1 − β) × trend(t−1)
- forecast(t + h) = level(t) + h × trend(t), never below 0

**Accuracy.** Measured on one-step-ahead forecasts over the last 6 months:

- WMAPE = Σ|actual − forecast| ÷ Σ actual
- Bias = Σ(forecast − actual) ÷ Σ actual. A positive bias means the forecast runs high.

**Plan demand.** Depends on the forecast method:

| Method | Plan demand |
|---|---|
| CUSTOMER | Customer forecast |
| STAT | Statistical forecast |
| BLEND | Average of the two |

Months without a customer forecast use the statistical forecast. The result is then multiplied by (1 + demand uplift %).

## 11. Module-level supply plan

Modules, in flow order: fab → bump (optional) → wafer sort → assembly → final test.

**Per product:**

- Good units per wafer = GDW × fab line yield × sort yield × assembly yield × final test yield
- Good die per wafer = GDW × fab line yield × sort yield

**Lead-time offsets, in months.** Each is rounded to the nearest whole month:

- Back offset (die bank → finished goods) = round((assembly + final test weeks) ÷ 4.33)
- Front offset (wafer start → die bank) = round((fab + bump + sort weeks) ÷ 4.33)

**Current WIP.** Each lot is assumed to be half way through its current stage. It becomes finished goods after the remaining cycle time, multiplied by the remaining yields. It also adds load to the downstream modules it still has to pass.

**Each month:**

1. Projected finished goods = previous + WIP receipts − demand.
2. Safety stock target = safety stock weeks × demand ÷ 4.33.
3. If projected finished goods fall below the target, the shortfall becomes a planned receipt.
4. Good die needed = planned receipt ÷ (assembly yield × final test yield). They enter assembly one back offset earlier.
5. Die are taken from the die bank first.
6. Any remaining die need new wafers = die ÷ good die per wafer, rounded **up** to whole wafer lots. These start one front offset before assembly. The extra die from rounding go to the die bank.
7. A start that would fall before the plan's first month is flagged **inside lead time**. Negative projected finished goods are flagged as a **shortage**.

**Module loads:**

| Module | Load |
|---|---|
| Fab | Wafer starts |
| Bump and sort | Wafers × line yield, offset by fab (and bump) cycle time |
| Assembly | Die entering |
| Final test | Units entering, offset by the assembly cycle time |

## 12. Tester (ATE) capacity

**Seconds per unit or wafer:**

- Final test: (test time + index time) ÷ sites
- Wafer sort (CP or WS insertions):
  - touchdowns per wafer = ⌈GDW ÷ sites⌉ ÷ stepping efficiency
  - seconds per wafer = touchdowns × (test time + index time) + wafer load time

**Throughput:** units (or wafers) per hour = 3600 ÷ seconds.

**Hours needed per tester type and month** = Σ over insertions of load × seconds ÷ 3600. Final-test insertions use the final-test load; sort insertions use the sort load.

**Hours available** = testers × hours per week × 4.33 × OEE.

**Status:**

- **Tight** above 85% utilisation.
- **Overloaded** above 100%.
- **Testers needed** = ⌈hours needed ÷ (hours per week × 4.33 × OEE)⌉.

## 13. Monthly B2B package

**Fab request** = fab wafer starts by month.

**OSAT request** = bump, sort, assembly and final-test loads by month.

**Tester hours** = hours needed by tester type and month.

**Time fences:**

| Fence | Months | Meaning |
|---|---|---|
| Frozen | the first *frozen months* | Firm orders |
| Slushy | the next *slushy months* | Changes within agreed flex |
| Liquid | the rest | Forecast only |

**Download.** The workbook has a REQUEST row for each product and module, a yellow COMMIT row for the supplier to fill, and a GAP row = COMMIT − REQUEST that calculates itself.

## 14. Plan_Quick sheet (Excel only)

Gross wafer starts per month = CEILING(customer FORECAST for the month × (1 + uplift) ÷ good units per wafer, wafer lot).

This is a first cut before netting stock and WIP. The web app does the full netting.
