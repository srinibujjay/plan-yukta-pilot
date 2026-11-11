"""Lot-level WIP audit: the first pilot's de-duplication and visibility view, kept as its own page."""
from __future__ import annotations

import base64
import io
from datetime import datetime

import pandas as pd

from plan_yukta.engine import OSAT_OPERATIONS, STAGE_SEQUENCE


def _fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, pd.Timestamp):
        return v.strftime('%Y-%m-%d') if v == v.normalize() else v.strftime('%Y-%m-%d %H:%M')
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, float):
        return f'{v:,.0f}' if v.is_integer() else f'{v:,.1f}'
    if isinstance(v, int):
        return f'{v:,}'
    return str(v)


def _table(df: pd.DataFrame, columns: dict | None = None, limit: int | None = None):
    """DataFrame -> headers, numeric-column flags and formatted rows for the template."""
    if df is None or df.empty:
        return {'headers': [], 'num': [], 'rows': [], 'more': 0}
    view = df[list(columns)] if columns else df
    headers = list(columns.values()) if columns else list(view.columns)
    num = [pd.api.types.is_numeric_dtype(view[c]) for c in view.columns]
    shown = view.head(limit) if limit else view
    rows = [[_fmt(v) for v in rec] for rec in shown.itertuples(index=False)]
    return {'headers': headers, 'num': num, 'rows': rows, 'more': max(0, len(view) - len(shown))}


def results_workbook(res: dict) -> bytes:
    buf = io.BytesIO()
    s = res['settings']
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        pd.DataFrame([
            ('As-of date', s.as_of), ('Latest OSAT snapshot', res['latest_snapshot']),
            ('OSAT snapshots used', res['snapshot_count']), ('E&O age threshold (months)', s.eo_age_months),
            ('E&O bin baseline', s.bin_baseline), ('Capacity tolerance', s.capacity_tolerance),
        ], columns=['Setting', 'Value']).to_excel(xw, sheet_name='Run_Info', index=False)
        res['overview'].to_excel(xw, sheet_name='Overview', index=False)
        res['dedup_effect'].to_excel(xw, sheet_name='Dedup_Effect', index=False)
        (res['dedup_audit'] if not res['dedup_audit'].empty else pd.DataFrame({'note': ['No rows removed']})
         ).to_excel(xw, sheet_name='Dedup_Audit', index=False)
        res['capacity'].to_excel(xw, sheet_name='Capacity_Check', index=False)
        (res['late_lots'] if not res['late_lots'].empty else pd.DataFrame({'note': ['No late fab lots']})
         ).to_excel(xw, sheet_name='Late_Fab_Lots', index=False)
        res['eo_summary'].to_excel(xw, sheet_name='EO_Summary', index=False)
        res['eo_rows'].drop(columns=['_SNAP'], errors='ignore').to_excel(xw, sheet_name='EO_Rows', index=False)
        res['binning'].to_excel(xw, sheet_name='FT_Binning', index=False)
        res['lead_times'].to_excel(xw, sheet_name='Lot_Lead_Times', index=False)
        res['fab_by_stage'].to_excel(xw, sheet_name='Fab_WIP_by_Stage', index=False)
        res['osat_kept'].to_excel(xw, sheet_name='OSAT_WIP_Clean', index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value or '')) for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 45)
            ws.freeze_panes = 'A2'
    return buf.getvalue()


def lead_time_bars(lead: pd.DataFrame):
    """Stacked bars per lot (days per stage) for a dependency-free chart."""
    if lead is None or lead.empty:
        return [], 1
    stages = ['Fab'] + STAGE_SEQUENCE
    bars = []
    for _, r in lead.iterrows():
        if not r['lead_time_days']:
            continue
        segs = [(st, int(r[f'{st} days'])) for st in stages
                if pd.notna(r.get(f'{st} days')) and r[f'{st} days'] > 0]
        bars.append({'lot': r['MOTHER_LOT'], 'product': r['MASTER_PRODUCT'], 'stage': r['current_stage'],
                     'total': int(r['lead_time_days']), 'segments': segs, 'scaled': r['scaled_to_elapsed']})
    scale = max([b['total'] for b in bars] + [1])
    return bars, scale


def results_context(res: dict, source_name: str, is_sample: bool) -> dict:
    ov = res['overview']
    ops = [k for k, _, _ in OSAT_OPERATIONS]
    totals = ov[[c for c in ov.columns if c != 'MASTER_PRODUCT']].sum() if not ov.empty else pd.Series(dtype=float)
    removed = int(res['osat_rows_latest'] - res['osat_rows_kept'])
    flags = res['capacity'][res['capacity']['status'].str.startswith('OVER')] if not res['capacity'].empty else pd.DataFrame()
    kpis = [
        ('Fab WIP', f"{int(totals.get('fab_wip_wafers', 0)):,}", 'wafers at the foundry'),
        ('Shipped from fab', f"{int(totals.get('shipped_wafers', 0)):,}", 'wafers'),
        ('OSAT wafers', f"{int(totals.get('SORT', 0) + totals.get('BUMP', 0)):,}", 'in Sort and Bump'),
        ('OSAT dies', f"{int(sum(totals.get(k, 0) for k in ('ASSEMBLY', 'TESTING', 'PACKING'))):,}", 'in Assembly, Test, Packing'),
        ('Duplicate rows removed', f'{removed:,}', f"of {res['osat_rows_latest']:,} in the latest snapshot"),
        ('Checks to review', f"{len(flags) + len(res['late_lots']) + len(res['unmapped_partnames'])}",
         'capacity, late lots, names'),
    ]
    op_labels = {k: f'{label} ({unit})' for k, label, unit in OSAT_OPERATIONS}
    overview_cols = {'MASTER_PRODUCT': 'Product', 'fab_wip_wafers': 'Fab WIP (wafers)', 'fab_lots': 'Fab lots',
                     'shipped_wafers': 'Shipped from fab (wafers)', **{k: op_labels[k] for k in ops}}
    bars, scale = lead_time_bars(res['lead_times'])
    audit = res['dedup_audit']
    audit_labels = {'DEDUP_RULE': 'Rule', 'DEDUP_REASON': 'Why it was removed', 'C_LOT_NUMBER': 'Lot',
                    'MAIN': 'Main', 'OPER': 'Oper', 'STATE': 'State', 'WAFER_ID': 'Wafer IDs',
                    'WAFER_QTY': 'Wafers', 'DIE_QTY': 'Dies'}
    audit_cols = {c: label for c, label in audit_labels.items() if c in audit.columns}
    eo_cols = {c: c for c in ['MASTER_PRODUCT', 'C_LOT_NUMBER', 'MAIN', 'OPER', 'DIE_QTY', 'WAFER_QTY',
                              'DATECODE', 'LOCATION', 'EO_REASON'] if c in res['eo_rows'].columns}
    xlsx = base64.b64encode(results_workbook(res)).decode()
    return dict(
        res=res, source_name=source_name, is_sample=is_sample, kpis=kpis,
        overview=_table(ov, overview_cols),
        dedup_effect=_table(res['dedup_effect'], {'operation': 'Operation', 'unit': 'Unit',
                                                  'before_dedup': 'As reported', 'after_dedup': 'After de-dup',
                                                  'removed': 'Removed'}),
        audit=_table(audit, audit_cols, limit=200),
        capacity=_table(res['capacity'], {'MASTER_PRODUCT': 'Product', 'gross_die_per_wafer': 'GDW',
                                          'shipped_wafers': 'Shipped wafers',
                                          'active_die_equivalent': 'Active die equivalent',
                                          'capacity_dies': 'Capacity (dies)', 'status': 'Result'}),
        late=_table(res['late_lots'], {'MASTER_PRODUCT': 'Product', 'Fab Lot ID': 'Lot', 'Current Stage': 'Stage',
                                       'Current Qty': 'Wafers', 'commit': 'Committed', 'projected': 'Projected out',
                                       'slip_days': 'Days late'}),
        eo_summary=_table(res['eo_summary'], {'operation': 'Operation', 'rows': 'Rows', 'qty': 'Quantity', 'unit': 'Unit'}),
        eo_rows=_table(res['eo_rows'], eo_cols, limit=100),
        binning=_table(res['binning'], {'LOCATION': 'Bin / location', 'dies': 'Dies', 'share_pct': 'Share %'}),
        lead=_table(res['lead_times'], {'MOTHER_LOT': 'Mother lot', 'MASTER_PRODUCT': 'Product',
                                        'current_stage': 'Current stage', 'process_days': 'Process days',
                                        'wait_days': 'Wait days', 'lead_time_days': 'Lead time (days)',
                                        'scaled_to_elapsed': 'Scaled'}),
        bars=bars, bar_scale=scale, stage_names=['Fab'] + STAGE_SEQUENCE,
        fab_stage=_table(res['fab_by_stage'], {'MASTER_PRODUCT': 'Product', 'Current Stage': 'Stage', 'wafers': 'Wafers'}),
        xlsx_b64=xlsx,
    )


def apply_playground(settings, form):
    """Let testers change the sample's settings from the page instead of editing Excel."""
    try:
        if form.get('as_of'):
            settings.as_of = datetime.strptime(form['as_of'], '%Y-%m-%d').date()
        if form.get('eo_age_months'):
            settings.eo_age_months = max(1.0, min(120.0, float(form['eo_age_months'])))
        if form.get('bin_baseline'):
            settings.bin_baseline = form['bin_baseline'].strip().upper()[:6]
        if form.get('capacity_tolerance'):
            settings.capacity_tolerance = max(0.5, min(2.0, float(form['capacity_tolerance'])))
    except ValueError:
        pass


