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
- The tester-capacity planner.
- Commercial invoices.
- The document system.
- Email alerts.

All of these need live connections or the dashboard's database.
