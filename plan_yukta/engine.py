"""
Plan Yukta pilot engine.

A standalone port of the planning/visibility calculations in the Plan Yukta
Django dashboard (dashboard/data_processor.py, osat_transfer_dedup.py,
wip_regression.py). It works on plain DataFrames read from the pilot Excel
template, with no database, email, OneDrive or Yielddb dependencies.

Each calculation names the dashboard function it mirrors, so behaviour can be
checked against the production code.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .osat_transfer_dedup import prepare_osat_dataframe

# ---------------------------------------------------------------------------
# Column aliases: the template uses these names, but exports straight from a
# foundry or OSAT portal often use the vendor's own headings.
# ---------------------------------------------------------------------------
FAB_WIP_ALIASES = {
    'Fab Product': ['Fab Product', 'Current Customer Product', 'Customer Product'],
    'Fab Lot ID': ['Fab Lot ID', 'FAB1 Lot ID', 'Lot ID', 'Lot Number'],
    'Current Stage': ['Current Stage', 'Stage'],
    'Current Qty': ['Current Qty', 'Wafer Qty', 'Wafer Quantity', 'Quantity', 'Qty', 'Wafers', 'WIP'],
    'Wafer Start Date': ['Wafer Start Date', 'Start Date'],
    'Committed Date': ['Committed Date', 'Commit Date'],
    'Projected Out Date': ['Projected Out Date', 'Projected Out'],
}
FAB_SHIP_ALIASES = {
    'Ship Date': ['Ship Date', 'Invoice Date'],
    'Fab Product': ['Fab Product', 'Customer Product', 'Current Customer Product'],
    'Fab Lot ID': ['Fab Lot ID', 'FAB1 Lot ID', 'Lot ID', 'Comment'],
    'UM': ['UM', 'Unit'],
    'Ship Qty': ['Ship Qty', 'Shipped Quantity', 'Quantity', 'Qty'],
}
OSAT_REQUIRED = ['SNAPSHOT_DATE', 'MAIN', 'OPER', 'STATE', 'PARTNAME', 'C_LOT_NUMBER',
                 'WAFER_QTY', 'DIE_QTY', 'WAFER_ID']
OSAT_OPTIONAL = ['DATECODE', 'LOCATION']

# Display order for OSAT operations (dashboard card order)
OSAT_OPERATIONS = [
    # key,        label,       unit
    ('SORT', 'Sort (CP)', 'wafers'),
    ('BUMP', 'Bump', 'wafers'),
    ('ASSEMBLY', 'Assembly', 'dies'),
    ('TESTING', 'Testing (FT)', 'dies'),
    ('PACKING', 'Packing', 'dies'),
]
STAGE_SEQUENCE = ['Sort (CP)', 'Bump', 'Assembly', 'Testing (FT)', 'Packing']


@dataclass
class Settings:
    as_of: date = field(default_factory=date.today)
    eo_age_months: float = 24
    bin_baseline: str = 'BIN1'
    capacity_tolerance: float = 1.05


class TemplateError(ValueError):
    """Raised when an uploaded workbook is missing something the engine needs."""


# ---------------------------------------------------------------------------
# Reading the template
# ---------------------------------------------------------------------------
def _clean_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how='all')
    return df


def _apply_aliases(df: pd.DataFrame, aliases: dict, sheet: str, required: list[str]) -> pd.DataFrame:
    df = _clean_headers(df)
    lower = {c.lower(): c for c in df.columns}
    rename = {}
    for canonical, options in aliases.items():
        if canonical in df.columns:
            continue
        for opt in options:
            if opt.lower() in lower:
                rename[lower[opt.lower()]] = canonical
                break
    df = df.rename(columns=rename)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise TemplateError(f"Sheet '{sheet}' is missing column(s): {', '.join(missing)}")
    return df


def read_workbook(source) -> dict:
    """Read the pilot template (path or file-like) into DataFrames + Settings."""
    try:
        book = pd.read_excel(source, sheet_name=None)
    except Exception as exc:  # noqa: BLE001
        raise TemplateError('Could not open the workbook. Save it from Excel as .xlsx and upload it again.') from exc

    sheets = {name.strip(): df for name, df in book.items()}
    needed = ['Products', 'Name_Map', 'Fab_WIP', 'Fab_Shipments', 'OSAT_WIP']
    missing = [s for s in needed if s not in sheets]
    if missing:
        raise TemplateError(f"Workbook is missing sheet(s): {', '.join(missing)}. "
                            'Start from the Plan Yukta template.')

    settings = Settings()
    if 'Settings' in sheets:
        s = _clean_headers(sheets['Settings'])
        if {'Setting', 'Value'}.issubset(s.columns):
            values = {str(k).strip(): v for k, v in zip(s['Setting'], s['Value']) if pd.notna(k)}
            if pd.notna(values.get('As-of date')):
                settings.as_of = pd.to_datetime(values['As-of date']).date()
            if pd.notna(values.get('E&O age threshold (months)')):
                settings.eo_age_months = float(values['E&O age threshold (months)'])
            if pd.notna(values.get('E&O bin baseline')):
                settings.bin_baseline = str(values['E&O bin baseline']).strip().upper()
            if pd.notna(values.get('Capacity tolerance')):
                settings.capacity_tolerance = float(values['Capacity tolerance'])

    products = _clean_headers(sheets['Products'])
    names = _clean_headers(sheets['Name_Map'])
    for sheet, df, cols in (('Products', products, ['MASTER_PRODUCT', 'GROSS_DIE_PER_WAFER']),
                            ('Name_Map', names, ['NAME', 'SOURCE', 'MASTER_PRODUCT'])):
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise TemplateError(f"Sheet '{sheet}' is missing column(s): {', '.join(missing)}")
    pmap = product_map_from_sheets(products, names)

    fab_wip = _apply_aliases(sheets['Fab_WIP'], FAB_WIP_ALIASES, 'Fab_WIP',
                             ['Fab Product', 'Fab Lot ID', 'Current Stage', 'Current Qty'])
    fab_wip = fab_wip[fab_wip['Fab Lot ID'].notna() & (fab_wip['Fab Lot ID'].astype(str).str.strip() != '')]
    fab_ship = _apply_aliases(sheets['Fab_Shipments'], FAB_SHIP_ALIASES, 'Fab_Shipments',
                              ['Ship Date', 'Fab Product', 'Fab Lot ID', 'UM', 'Ship Qty'])
    fab_ship = fab_ship[fab_ship['Fab Product'].notna() & (fab_ship['Fab Product'].astype(str).str.strip() != '')]

    osat = _clean_headers(sheets['OSAT_WIP'])
    osat.columns = [c.upper() for c in osat.columns]
    missing = [c for c in OSAT_REQUIRED if c not in osat.columns]
    if missing:
        raise TemplateError(f"Sheet 'OSAT_WIP' is missing column(s): {', '.join(missing)}")
    for c in OSAT_OPTIONAL:
        if c not in osat.columns:
            osat[c] = pd.NA
    # Keep only the input columns: the template's "(calc)" helper columns are Excel-side only
    osat = osat[OSAT_REQUIRED + OSAT_OPTIONAL]
    osat = osat[osat['MAIN'].notna() & (osat['MAIN'].astype(str).str.strip() != '')].reset_index(drop=True)
    if osat.empty:
        raise TemplateError("Sheet 'OSAT_WIP' has no rows.")

    return {'settings': settings, 'product_map': pmap, 'fab_wip': fab_wip,
            'fab_ship': fab_ship, 'osat_wip': osat}


# ---------------------------------------------------------------------------
# Product mapping (data_processor.get_master_customer_products +
# get_confirmed_lots_from_fab1 ambiguous-name resolution)
# ---------------------------------------------------------------------------
def product_map_from_sheets(products: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
    """Turn the template's Products + Name_Map sheets into one row per name."""
    products = products[products['MASTER_PRODUCT'].notna()]
    gdw = {str(p).strip(): g for p, g in zip(products['MASTER_PRODUCT'], products['GROSS_DIE_PER_WAFER'])}
    rows = []
    for _, r in names.iterrows():
        if pd.isna(r['NAME']) or pd.isna(r['MASTER_PRODUCT']):
            continue
        master = str(r['MASTER_PRODUCT']).strip()
        source = str(r['SOURCE']).strip().upper()
        rows.append({'MASTER_PRODUCT': master,
                     'FAB_PRODUCT': str(r['NAME']).strip() if source == 'FAB' else None,
                     'OSAT_PARTNAME': str(r['NAME']).strip() if source == 'OSAT' else None,
                     'GROSS_DIE_PER_WAFER': gdw.get(master)})
    for master, g in gdw.items():  # products with no names still carry their GDW
        rows.append({'MASTER_PRODUCT': master, 'FAB_PRODUCT': None, 'OSAT_PARTNAME': None,
                     'GROSS_DIE_PER_WAFER': g})
    return pd.DataFrame(rows, columns=['MASTER_PRODUCT', 'FAB_PRODUCT', 'OSAT_PARTNAME', 'GROSS_DIE_PER_WAFER'])


def _mother(lot) -> str:
    s = str(lot or '').strip().upper()
    return s[:6] if len(s) >= 6 else s


def build_maps(pmap: pd.DataFrame):
    fab_to_master = {}
    osat_to_masters: dict[str, set] = {}
    gdw = {}
    for _, r in pmap.iterrows():
        master = r['MASTER_PRODUCT']
        if pd.notna(r['FAB_PRODUCT']) and r['FAB_PRODUCT']:
            fab_to_master[str(r['FAB_PRODUCT']).upper()] = master
        if pd.notna(r['OSAT_PARTNAME']) and r['OSAT_PARTNAME']:
            osat_to_masters.setdefault(str(r['OSAT_PARTNAME']).upper(), set()).add(master)
        g = pd.to_numeric(r['GROSS_DIE_PER_WAFER'], errors='coerce')
        if pd.notna(g) and g > 0:
            gdw[master] = float(g)
    return fab_to_master, osat_to_masters, gdw


def map_osat_products(osat: pd.DataFrame, osat_to_masters, lot_owner) -> pd.Series:
    """
    Exact OSAT part names map directly. A part name shared by several master
    products (a bare family name, for example) is resolved through the fab
    files: the six-character mother lot must be confirmed for exactly one
    master product, otherwise the row stays UNRESOLVED.
    """
    def resolve(row):
        name = str(row['PARTNAME'] or '').strip().upper()
        masters = osat_to_masters.get(name)
        if not masters:
            return 'UNMAPPED'
        if len(masters) == 1:
            return next(iter(masters))
        owners = lot_owner.get(_mother(row['C_LOT_NUMBER']), set()) & masters
        return next(iter(owners)) if len(owners) == 1 else 'UNRESOLVED'
    return osat.apply(resolve, axis=1)


# ---------------------------------------------------------------------------
# OSAT operation classification (data_processor._filter_osat_operation_dataframe)
# ---------------------------------------------------------------------------
def _completed_bin(value) -> bool:
    return str(value or '').strip().upper().replace(' ', '') in {'BIN1', 'GOOD'}


def classify_operation(df: pd.DataFrame) -> pd.Series:
    main = df['MAIN'].astype(str).str.strip().str.upper()
    oper = df['OPER'].astype(str).str.strip().str.upper()
    done_bin = df['LOCATION'].apply(_completed_bin)
    out = pd.Series('OTHER', index=df.index)
    out[main.eq('CP')] = 'SORT'
    out[main.eq('BUMP')] = 'BUMP'
    out[main.eq('ASSY')] = 'ASSEMBLY'
    ft = main.eq('FT')
    out[ft] = 'TESTING'
    out[ft & (oper.eq('IP') | done_bin)] = 'PACKING'
    return out


# ---------------------------------------------------------------------------
# De-duplication across snapshots (data_processor._prepare_osat_wip_snapshot)
# ---------------------------------------------------------------------------
def _snapshot_key(value) -> pd.Timestamp:
    return pd.to_datetime(value, errors='coerce')


def dedupe_latest_snapshot(osat: pd.DataFrame):
    """
    Run the production de-duplication on the latest snapshot, giving it the
    earlier snapshots as file history exactly as the dashboard does with its
    folder of daily OSAT reports.
    """
    osat = osat.copy()
    osat['_SNAP'] = osat['SNAPSHOT_DATE'].apply(_snapshot_key)
    if osat['_SNAP'].isna().all():
        raise TemplateError("OSAT_WIP: SNAPSHOT_DATE has no valid dates.")
    osat = osat[osat['_SNAP'].notna()]
    snaps = sorted(osat['_SNAP'].unique())
    latest = snaps[-1]

    with tempfile.TemporaryDirectory() as tmp:
        frames = {}
        paths = {}
        for i, snap in enumerate(snaps):
            stamp = pd.Timestamp(snap).strftime('%Y%m%d%H%M%S')
            path = Path(tmp) / f'osat_snapshot_{stamp}.xlsx'
            path.touch()  # placeholder: history reader returns the in-memory frame
            frames[str(path.resolve())] = (osat[osat['_SNAP'] == snap]
                                           .drop(columns=['_SNAP']).reset_index(drop=True))
            paths[snap] = path
        date_of = {str(p.resolve()): pd.Timestamp(s).to_pydatetime() for s, p in paths.items()}

        history = {
            'folder': tmp,
            'read_df': lambda p: frames.get(str(Path(p).resolve())),
            'get_date': lambda p: date_of[str(Path(p).resolve())],
            'target_date': None,
            'work_order_context': None,
            'snapshot_date': pd.Timestamp(latest).to_pydatetime(),
        }
        latest_path = paths[latest]
        raw = frames[str(latest_path.resolve())]
        kept, audit = prepare_osat_dataframe(
            raw.copy(), str(latest_path), history_context=history,
            exclude_terminal_wip=True, return_audit=True,
        )
    return raw, kept, (audit if audit is not None else pd.DataFrame()), pd.Timestamp(latest)


def clean_each_snapshot(osat: pd.DataFrame) -> pd.DataFrame:
    """Apply the same-snapshot de-duplication rules to every snapshot (no history)."""
    snap = pd.to_datetime(osat['SNAPSHOT_DATE'], errors='coerce')
    parts = []
    for value in sorted(snap.dropna().unique()):
        frame = osat[snap == value].reset_index(drop=True)
        parts.append(prepare_osat_dataframe(frame, f'snapshot_{pd.Timestamp(value):%Y%m%d%H%M%S}.xlsx',
                                            history_context=None, exclude_terminal_wip=True))
    return pd.concat(parts, ignore_index=True) if parts else osat.iloc[0:0].copy()


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def fab_wip_summary(fab_wip, fab_to_master):
    """data_processor.get_fab1_wip_data + _finalize_fab1_wip_result:
    wafers = SUM(Current Qty) where Current Stage <> SHIPPED."""
    df = fab_wip.copy()
    df['MASTER_PRODUCT'] = df['Fab Product'].astype(str).str.strip().str.upper().map(fab_to_master).fillna('UNMAPPED')
    df['Current Qty'] = pd.to_numeric(df['Current Qty'], errors='coerce').fillna(0)
    stage = df['Current Stage'].astype(str).str.strip().str.upper()
    active = df[stage != 'SHIPPED']
    by_product = (active.groupby('MASTER_PRODUCT')
                  .agg(fab_wip_wafers=('Current Qty', 'sum'), fab_lots=('Fab Lot ID', 'nunique'))
                  .reset_index())
    by_stage = (active.groupby(['MASTER_PRODUCT', 'Current Stage'])['Current Qty'].sum()
                .reset_index().rename(columns={'Current Qty': 'wafers'}))
    return df, by_product, by_stage, int(len(df) - len(active))


def fab_commit_check(fab_wip_mapped, as_of):
    """Lots whose projected out date is later than the committed date (fab report columns)."""
    df = fab_wip_mapped.copy()
    if 'Committed Date' not in df.columns or 'Projected Out Date' not in df.columns:
        return pd.DataFrame()
    stage = df['Current Stage'].astype(str).str.strip().str.upper()
    df = df[stage != 'SHIPPED'].copy()
    df['commit'] = pd.to_datetime(df['Committed Date'], errors='coerce')
    df['projected'] = pd.to_datetime(df['Projected Out Date'], errors='coerce')
    df = df[df['commit'].notna() & df['projected'].notna()]
    df['slip_days'] = (df['projected'] - df['commit']).dt.days
    late = df[df['slip_days'] > 0]
    return late[['MASTER_PRODUCT', 'Fab Lot ID', 'Current Stage', 'Current Qty',
                 'commit', 'projected', 'slip_days']].sort_values('slip_days', ascending=False)


def fab_shipment_summary(fab_ship, fab_to_master):
    """data_processor.get_fab1_past_shipment_data: wafers = SUM(Ship Qty) where UM = 'WF'."""
    df = fab_ship.copy()
    df['MASTER_PRODUCT'] = df['Fab Product'].astype(str).str.strip().str.upper().map(fab_to_master).fillna('UNMAPPED')
    df['Ship Qty'] = pd.to_numeric(df['Ship Qty'], errors='coerce').fillna(0)
    wf = df[df['UM'].astype(str).str.strip().str.upper() == 'WF']
    by_product = (wf.groupby('MASTER_PRODUCT')
                  .agg(shipped_wafers=('Ship Qty', 'sum'), ship_lots=('Fab Lot ID', 'nunique'))
                  .reset_index())
    return df, by_product


def osat_wip_summary(df):
    """data_processor.get_operation_data: Sort/Bump sum WAFER_QTY, all later
    operations sum DIE_QTY."""
    rows = []
    for product, grp in df.groupby('MASTER_PRODUCT'):
        rec = {'MASTER_PRODUCT': product}
        for key, _label, unit in OSAT_OPERATIONS:
            sub = grp[grp['OPERATION'] == key]
            col = 'WAFER_QTY' if unit == 'wafers' else 'DIE_QTY'
            rec[key] = int(pd.to_numeric(sub[col], errors='coerce').fillna(0).sum())
        rows.append(rec)
    return pd.DataFrame(rows, columns=['MASTER_PRODUCT'] + [k for k, _, _ in OSAT_OPERATIONS])


def binning_breakdown(df):
    """data_processor.get_binning_breakdown: FT/Packing die qty grouped by LOCATION."""
    ft = df[df['OPERATION'].isin(['TESTING', 'PACKING'])].copy()
    if ft.empty:
        return pd.DataFrame(columns=['LOCATION', 'dies', 'share_pct'])
    ft['LOCATION'] = ft['LOCATION'].fillna('Unknown').astype(str).str.strip().replace({'': 'Unknown', 'nan': 'Unknown'})
    ft['DIE_QTY'] = pd.to_numeric(ft['DIE_QTY'], errors='coerce').fillna(0)
    out = ft.groupby('LOCATION')['DIE_QTY'].sum().reset_index().rename(columns={'DIE_QTY': 'dies'})
    total = out['dies'].sum()
    out['share_pct'] = (out['dies'] / total * 100).round(1) if total else 0.0
    return out.sort_values('dies', ascending=False).reset_index(drop=True)


def _parse_datecode(val):
    if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val):
        return None
    m = re.search(r'(\d{4})$', str(val).strip().split('.')[0])
    if not m:
        return None
    yy, ww = int(m.group(1)[:2]), int(m.group(1)[2:])
    try:
        return datetime.fromisocalendar(2000 + yy, ww, 1).date()
    except ValueError:
        return None


def excess_obsolete(df, settings: Settings):
    """data_processor.get_eo_data: a row is E&O when its YYWW date code is older
    than the threshold (months x 30 days) or its bin number is above the
    baseline bin."""
    threshold = settings.as_of - timedelta(days=30 * settings.eo_age_months)
    base_digits = re.sub(r'[^0-9]', '', settings.bin_baseline)
    base = int(base_digits) if base_digits else 1

    reasons = []
    for _, r in df.iterrows():
        why = []
        dc = _parse_datecode(r.get('DATECODE'))
        if dc and dc < threshold:
            why.append(f'Date code {r.get("DATECODE")} older than {settings.eo_age_months:g} months')
        loc = str(r.get('LOCATION') or '').upper()
        if loc.startswith('BIN'):
            digits = re.sub(r'[^0-9]', '', loc)
            if digits and int(digits) > base:
                why.append(f'{loc} above baseline {settings.bin_baseline}')
            elif not digits and loc != settings.bin_baseline:
                why.append(f'{loc} is not {settings.bin_baseline}')
        reasons.append('; '.join(why))
    work = df.copy()
    work['EO_REASON'] = reasons
    eo = work[work['EO_REASON'] != '']
    summary = []
    for key, label, unit in OSAT_OPERATIONS:
        sub = eo[eo['OPERATION'] == key]
        col = 'WAFER_QTY' if unit == 'wafers' else 'DIE_QTY'
        summary.append({'operation': label, 'unit': unit, 'rows': len(sub),
                        'qty': int(pd.to_numeric(sub[col], errors='coerce').fillna(0).sum())})
    return eo, pd.DataFrame(summary)


def capacity_check(osat_by_product, fab_ship_by_product, gdw, tolerance):
    """wip_regression.validate_gross_die_capacity, per product:
    active equivalent = (Sort+Bump wafers) x GDW + (Assembly+Testing dies)
    capacity          = shipped wafers x GDW x tolerance
    Flag when active equivalent > capacity (an impossible over-count)."""
    ship = dict(zip(fab_ship_by_product['MASTER_PRODUCT'], fab_ship_by_product['shipped_wafers']))
    rows = []
    for _, r in osat_by_product.iterrows():
        p = r['MASTER_PRODUCT']
        g = gdw.get(p)
        shipped = float(ship.get(p, 0))
        rec = {'MASTER_PRODUCT': p, 'gross_die_per_wafer': g, 'shipped_wafers': shipped,
               'active_die_equivalent': None, 'capacity_dies': None, 'status': ''}
        if not g:
            rec['status'] = 'No gross die/wafer in Product_Map'
        elif not shipped:
            rec['status'] = 'No fab shipments to compare'
        else:
            # Packing is FT in the dashboard's MAIN-based check, so it counts here too.
            active = (r['SORT'] + r['BUMP']) * g + r['ASSEMBLY'] + r['TESTING'] + r['PACKING']
            cap = shipped * g * tolerance
            rec.update(active_die_equivalent=round(active), capacity_dies=round(cap),
                       status='OVER CAPACITY - check for double counting' if active > cap else 'OK')
        rows.append(rec)
    return pd.DataFrame(rows)


def lot_lead_times(osat_all, fab_wip_mapped, fab_ship_mapped, as_of):
    """data_processor.get_lot_travel_history at snapshot-date level, per mother lot:
      stage start   = first snapshot the lot appears in the stage
      stage end     = last snapshot it appears in the stage
      process days  = end - start
      wait days     = start - previous stage end (fab ship date for the first OSAT stage)
      lead time     = sum(process) + sum(wait); scaled down when it exceeds the
                      elapsed time since the lot started (the dashboard's sanity check).
    The fab leg runs from Wafer Start Date to the fab ship date when both exist."""
    df = osat_all.copy()
    df['_mother'] = df['C_LOT_NUMBER'].apply(_mother)
    df['_snap'] = pd.to_datetime(df['SNAPSHOT_DATE'], errors='coerce').dt.normalize()
    df = df[df['_snap'].notna() & (df['_mother'] != '')]
    label_of = {k: label for k, label, _ in OSAT_OPERATIONS}
    df['_stage'] = df['OPERATION'].map(label_of)
    df = df[df['_stage'].notna()]

    fab_start = {}
    if 'Wafer Start Date' in fab_wip_mapped.columns:
        tmp = fab_wip_mapped.assign(_m=fab_wip_mapped['Fab Lot ID'].apply(_mother),
                                    _d=pd.to_datetime(fab_wip_mapped['Wafer Start Date'], errors='coerce'))
        fab_start = tmp.dropna(subset=['_d']).groupby('_m')['_d'].min().to_dict()
    ship = fab_ship_mapped.assign(_m=fab_ship_mapped['Fab Lot ID'].apply(_mother),
                                  _d=pd.to_datetime(fab_ship_mapped['Ship Date'], errors='coerce'))
    fab_ship_date = ship.dropna(subset=['_d']).groupby('_m')['_d'].max().to_dict()

    as_of_ts = pd.Timestamp(as_of)
    rows = []
    for mother, grp in df.groupby('_mother'):
        product = grp['MASTER_PRODUCT'].mode().iat[0]
        legs = []
        prev_end = fab_ship_date.get(mother)
        if mother in fab_start and mother in fab_ship_date:
            legs.append(('Fab', fab_start[mother], fab_ship_date[mother], 0))
        for stage in STAGE_SEQUENCE:
            s = grp[grp['_stage'] == stage]
            if s.empty:
                continue
            start, end = s['_snap'].min(), s['_snap'].max()
            wait = max(0, (start - prev_end).days) if prev_end is not None else 0
            legs.append((stage, start, end, wait))
            prev_end = end
        if not legs:
            continue
        process = {name: (end - start).days for name, start, end, _ in legs}
        waits = {name: w for name, _, _, w in legs}
        total = sum(process.values()) + sum(waits.values())
        starts = [start for _, start, _, _ in legs]
        if mother in fab_ship_date:
            starts.append(fab_ship_date[mother])  # wait into the first OSAT stage counts from here
        lot_start = min(starts)
        elapsed = (as_of_ts - lot_start).days
        scaled = False
        if total > elapsed > 0:
            factor = elapsed / total
            process = {k: int(v * factor) for k, v in process.items()}
            waits = {k: int(v * factor) for k, v in waits.items()}
            total = sum(process.values()) + sum(waits.values())
            scaled = True
        rec = {'MOTHER_LOT': mother, 'MASTER_PRODUCT': product,
               'current_stage': legs[-1][0], 'first_seen': lot_start.date(),
               'process_days': sum(process.values()), 'wait_days': sum(waits.values()),
               'lead_time_days': total, 'scaled_to_elapsed': 'yes' if scaled else ''}
        for name in ['Fab'] + STAGE_SEQUENCE:
            rec[f'{name} days'] = (process.get(name, 0) + waits.get(name, 0)) if name in process else None
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(['MASTER_PRODUCT', 'MOTHER_LOT']) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_plan(data: dict) -> dict:
    settings: Settings = data['settings']
    fab_to_master, osat_to_masters, gdw = build_maps(data['product_map'])

    fab_wip_mapped, fab_by_product, fab_by_stage, shipped_rows_excluded = fab_wip_summary(data['fab_wip'], fab_to_master)
    fab_ship_mapped, ship_by_product = fab_shipment_summary(data['fab_ship'], fab_to_master)
    late_lots = fab_commit_check(fab_wip_mapped, settings.as_of)

    # Lot ownership from fab files resolves ambiguous OSAT part names
    lot_owner: dict[str, set] = {}
    for frame in (fab_wip_mapped, fab_ship_mapped):
        for lot, master in zip(frame['Fab Lot ID'], frame['MASTER_PRODUCT']):
            if master != 'UNMAPPED':
                lot_owner.setdefault(_mother(lot), set()).add(master)

    # Lead times use each snapshot after the same-snapshot de-duplication rules,
    # so a stale TRANSFER row does not stretch a stage it has already left.
    osat_all = clean_each_snapshot(data['osat_wip'])
    osat_all['MASTER_PRODUCT'] = map_osat_products(osat_all, osat_to_masters, lot_owner)
    osat_all['OPERATION'] = classify_operation(osat_all)

    raw, kept, audit, latest = dedupe_latest_snapshot(data['osat_wip'])
    for frame in (raw, kept):
        frame['MASTER_PRODUCT'] = map_osat_products(frame, osat_to_masters, lot_owner)
        frame['OPERATION'] = classify_operation(frame)

    osat_raw_by_product = osat_wip_summary(raw)
    osat_by_product = osat_wip_summary(kept)
    bins = binning_breakdown(kept)
    eo_rows, eo_summary = excess_obsolete(kept, settings)
    capacity = capacity_check(osat_by_product, ship_by_product, gdw, settings.capacity_tolerance)
    lead = lot_lead_times(osat_all, fab_wip_mapped, fab_ship_mapped, settings.as_of)

    # One overview row per product
    overview = (fab_by_product.merge(ship_by_product, on='MASTER_PRODUCT', how='outer')
                .merge(osat_by_product, on='MASTER_PRODUCT', how='outer'))
    num_cols = [c for c in overview.columns if c != 'MASTER_PRODUCT']
    overview[num_cols] = overview[num_cols].fillna(0).astype(int)
    overview = overview.sort_values('MASTER_PRODUCT').reset_index(drop=True)

    raw_tot = osat_raw_by_product[[k for k, _, _ in OSAT_OPERATIONS]].sum()
    kept_tot = osat_by_product[[k for k, _, _ in OSAT_OPERATIONS]].sum()
    dedup_effect = pd.DataFrame([
        {'operation': label, 'unit': unit, 'before_dedup': int(raw_tot.get(key, 0)),
         'after_dedup': int(kept_tot.get(key, 0)),
         'removed': int(raw_tot.get(key, 0) - kept_tot.get(key, 0))}
        for key, label, unit in OSAT_OPERATIONS
    ])

    unmapped = sorted(set(kept.loc[kept['MASTER_PRODUCT'].isin(['UNMAPPED', 'UNRESOLVED']), 'PARTNAME'].astype(str)))

    return {
        'settings': settings,
        'latest_snapshot': latest,
        'snapshot_count': int(pd.to_datetime(data['osat_wip']['SNAPSHOT_DATE'], errors='coerce').nunique()),
        'overview': overview,
        'fab_by_stage': fab_by_stage,
        'fab_shipped_rows_excluded': shipped_rows_excluded,
        'late_lots': late_lots,
        'dedup_effect': dedup_effect,
        'dedup_audit': audit,
        'osat_rows_latest': len(raw),
        'osat_rows_kept': len(kept),
        'binning': bins,
        'eo_summary': eo_summary,
        'eo_rows': eo_rows,
        'capacity': capacity,
        'lead_times': lead,
        'unmapped_partnames': unmapped,
        'osat_kept': kept,
    }
