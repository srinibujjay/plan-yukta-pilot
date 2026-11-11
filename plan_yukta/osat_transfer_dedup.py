# Copied unchanged from dashboard/osat_transfer_dedup.py so the pilot deploys on its own.
# Keep the two in sync if the de-duplication rules change.
"""
OSAT WIP de-duplication when the same physical wafer appears in multiple MAIN stages.

Handles:
  1) Same-day forward transfer: CP/TRANSFER while wafer already in ASSY (drop stale TRANSFER).
  2) Backward flow after stage complete: BUMP/FINISH while wafer returned to CP/WS2 (drop FINISH
     at prior stage; use file history to pick the authoritative MAIN).

Applied per snapshot file with access to prior OSAT files (WIP dashboard, lot travel, genealogy).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Typical forward OSAT flow (used only for TRANSFER-at-earlier-stage rule)
MAIN_STAGE_ORDER = {
    'CP': 10,
    'BUMP': 20,
    'ASSY': 30,
    'FT': 40,
    'PACKING': 50,
}


def _mother_lot(c_lot_number):
    s = str(c_lot_number or '').strip().upper()
    if len(s) >= 6:
        return s[:6]
    return s


def _wafer_key(wafer_id):
    if wafer_id is None or (isinstance(wafer_id, float) and pd.isna(wafer_id)):
        return None
    s = str(wafer_id).strip()
    if not s or s.upper() in ('NAN', 'NONE'):
        return None
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def _is_transfer_state(state):
    return 'TRANSFER' in str(state or '').upper()


def _main_code(main_val):
    return str(main_val or '').strip().upper()


def _state_kind(state):
    s = str(state or '').upper()
    if any(tok in s for tok in ('FINISH', 'FINSH', 'DONE', 'COMPLETE', 'COMPLETED')):
        return 'terminal'
    if any(tok in s for tok in ('WAIT', 'PROCESS', 'HOLD', 'RUN', 'WIP')):
        return 'active'
    if 'TRANSFER' in s:
        return 'transfer'
    return 'other'


def _is_terminal_state(state):
    return _state_kind(state) == 'terminal'


def _is_completed_ft_bin_value(value):
    text = str(value or '').strip().upper().replace(' ', '')
    return text in {'BIN1', 'GOOD'}


def _event_sort_key(event):
    return (event['date'], event['mtime'], event.get('row_idx', 0))


def _normalize_date(d):
    if hasattr(d, 'date'):
        return d.date()
    return d


def _date_or_none(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        timestamp = pd.to_datetime(value, errors='coerce')
        if pd.isna(timestamp):
            return None
        return timestamp.date()
    except Exception:
        return None


def _work_order_operation_for_main(main):
    return {
        'CP': 'SORT',
        'BUMP': 'BUMPING',
        'ASSY': 'ASSEMBLY',
        'FT': 'TEST',
        'PACKING': 'TEST',
    }.get(_main_code(main))


def _format_work_order_evidence(work_order_context, mother, auth_main=None, snapshot_date=None):
    if not work_order_context or not mother:
        return ''

    records = (work_order_context.get('work_orders_by_mother') or {}).get(mother, [])
    if not records:
        return ''

    expected_operation = _work_order_operation_for_main(auth_main)
    snapshot_day = _date_or_none(snapshot_date)
    matches = []
    for record in records:
        operation = str(record.get('operation_type') or '').strip().upper()
        if expected_operation and operation != expected_operation:
            continue
        wo_date = _date_or_none(record.get('work_order_date'))
        if snapshot_day is not None and wo_date is not None and wo_date > snapshot_day:
            continue
        matches.append(record)

    if not matches:
        return ''

    matches.sort(key=lambda item: (_date_or_none(item.get('work_order_date')) or pd.Timestamp.min.date(), str(item.get('work_order_number') or '')))
    record = matches[-1]
    wo_number = record.get('work_order_number') or 'work order'
    operation = str(record.get('operation_type') or expected_operation or '').strip().upper()
    wo_date = _date_or_none(record.get('work_order_date'))
    date_text = wo_date.isoformat() if wo_date else 'date not available'
    if operation:
        return f" Supporting work-order release proof: {operation} {wo_number} for mother lot {mother} dated {date_text}."
    return f" Supporting work-order release proof: {wo_number} for mother lot {mother} dated {date_text}."


def is_osat_wip_dataframe(df):
    """True when df looks like a OSATA/OSAT WIP report."""
    if df is None or df.empty:
        return False
    required = {'MAIN', 'C_LOT_NUMBER', 'STATE', 'WAFER_ID'}
    return required.issubset(set(df.columns))


def _audit_removed_rows(df, indices, rule, reason, match_key_fn=None):
    if not indices:
        return pd.DataFrame()
    removed = df.loc[list(dict.fromkeys(indices))].copy()
    removed['DEDUP_RULE'] = rule
    removed['DEDUP_REASON'] = reason
    if match_key_fn:
        removed['DEDUP_MATCH_KEY'] = removed.apply(match_key_fn, axis=1)
    elif 'C_LOT_NUMBER' in removed.columns:
        removed['DEDUP_MATCH_KEY'] = removed['C_LOT_NUMBER'].apply(_mother_lot)
    else:
        removed['DEDUP_MATCH_KEY'] = ''
    helper_cols = [c for c in removed.columns if str(c).startswith('_dedup_')]
    if helper_cols:
        removed = removed.drop(columns=helper_cols)
    return removed.reset_index(drop=True)


def _merge_audit_frames(audit_frames):
    frames = [frame for frame in audit_frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _snapshot_date_label(file_path):
    stem = Path(str(file_path)).stem
    digits = ''.join(ch for ch in stem if ch.isdigit())
    if len(digits) >= 8:
        raw = digits[-14:] if len(digits) >= 14 else digits[-8:]
        try:
            fmt = '%Y%m%d%H%M%S' if len(raw) == 14 else '%Y%m%d'
            return pd.to_datetime(raw, format=fmt).strftime('%Y-%m-%d')
        except Exception:
            pass
    return 'the selected OSAT snapshot'


def _wafer_label(row):
    wafer = row.get('WAFER_ID')
    if wafer is None or (isinstance(wafer, float) and pd.isna(wafer)):
        return 'no wafer ID'
    text = str(wafer).strip()
    return text if text and text.upper() not in ('NAN', 'NONE') else 'no wafer ID'


def _add_audit_explanations(audit_df, file_path, history_context=None):
    if audit_df is None or audit_df.empty:
        return audit_df

    snapshot_date = _snapshot_date_label(file_path)
    work_order_context = (history_context or {}).get('work_order_context') or {}
    context_snapshot_date = (history_context or {}).get('snapshot_date')

    def explain(row):
        rule = row.get('DEDUP_RULE', '')
        mother = row.get('DEDUP_MATCH_KEY') or _mother_lot(row.get('C_LOT_NUMBER'))
        sublot = row.get('C_LOT_NUMBER') or mother
        main = _main_code(row.get('MAIN'))
        oper = str(row.get('OPER') or '').strip()
        state = str(row.get('STATE') or '').strip()
        wafer = _wafer_label(row)
        mother_lot = _mother_lot(row.get('C_LOT_NUMBER'))

        if rule == 'STALE_SORT_TRANSFER_DOWNSTREAM_DIE':
            return (
                f"On {snapshot_date}, {sublot} wafer {wafer} is still reported as "
                f"{main}/{oper} {state}, but mother lot {mother} is already present "
                "in downstream FT die-level WIP in the same OSAT snapshot. After wafer "
                "split, Testing/Packing no longer carries WAFER_ID, so this Sort transfer "
                "row is treated as moved downstream and excluded from active Sort WIP."
            )
        if rule == 'SAME_MAIN_TRANSFER_DUPLICATE':
            return (
                f"On {snapshot_date}, {sublot} wafer {wafer} is reported in the same "
                f"MAIN stage both as an active row and as {main}/{oper} {state}. The "
                "transfer row is treated as stale within that stage and excluded from "
                "active WIP to avoid counting the same wafer twice."
            )
        if rule == 'CROSS_MAIN_WAFER_LOCATION':
            return (
                f"On {snapshot_date}, {sublot} wafer {wafer} appears in more than one "
                "MAIN stage. The dashboard keeps the authoritative active stage and "
                f"removes this {main}/{oper} {state} row from active WIP to avoid duplication."
            )
        if rule == 'HISTORY_WAFER_LOCATION':
            auth_main = _main_code(row.get('DEDUP_AUTH_MAIN'))
            destination = f" latest MAIN stage {auth_main}" if auth_main else " a different latest MAIN stage"
            wo_evidence = _format_work_order_evidence(
                work_order_context,
                mother_lot,
                auth_main=auth_main,
                snapshot_date=context_snapshot_date,
            )
            return (
                f"File history up to {snapshot_date} shows {sublot} wafer {wafer} moved "
                f"to{destination}. This older {main}/{oper} {state} row "
                "is excluded from active WIP to avoid counting the same wafer twice."
                f"{wo_evidence}"
            )
        if rule == 'TERMINAL_WIP_ROW':
            reason = str(row.get('DEDUP_REASON') or '')
            if 'SORT work order' in reason:
                return (
                    f"On {snapshot_date}, {sublot} wafer {wafer} has terminal state {state}. "
                    "It is removed because the same mother lot has live Sort WIP and an active "
                    "SORT work order/release date validating the BUMP-to-Sort transition."
                )
            return (
                f"On {snapshot_date}, {sublot} wafer {wafer} has terminal state {state}. "
                "It is removed from active WIP only because the same wafer or mother lot "
                "also appears in another non-terminal row in this snapshot."
            )
        return row.get('DEDUP_REASON', '')

    audit_df = audit_df.copy()
    audit_df['DEDUP_SNAPSHOT_DATE'] = snapshot_date
    audit_df['DEDUP_EXPLANATION'] = audit_df.apply(explain, axis=1)
    return audit_df


def pick_authoritative_main(events):
    """
    Choose the single MAIN stage that should own this wafer for the current snapshot.

    Uses the latest snapshot day first; active/WAIT beats FINISH on the same day;
    otherwise the chronologically last event across history wins (supports CP after BUMP).
    """
    if not events:
        return None

    events = sorted(events, key=_event_sort_key)
    snapshot_date = _normalize_date(events[-1]['date'])
    same_day = [e for e in events if _normalize_date(e['date']) == snapshot_date]

    pool = same_day if same_day else events
    mains = {_main_code(e['main']) for e in pool}
    if len(mains) == 1:
        return next(iter(mains))

    active = [e for e in pool if _state_kind(e['state']) in ('active', 'transfer')]
    terminal = [e for e in pool if _state_kind(e['state']) == 'terminal']
    strong_active = [e for e in pool if _state_kind(e['state']) == 'active']
    transfer = [e for e in pool if _state_kind(e['state']) == 'transfer']

    if strong_active and transfer:
        strong_active_mains = {_main_code(e['main']) for e in strong_active}
        if len(strong_active_mains) == 1:
            return next(iter(strong_active_mains))
        return _main_code(sorted(strong_active, key=_event_sort_key)[-1]['main'])

    if active and terminal:
        active_mains = {_main_code(e['main']) for e in active}
        if len(active_mains) == 1:
            return next(iter(active_mains))
        return _main_code(sorted(active, key=_event_sort_key)[-1]['main'])

    # Multiple mains, same kind — last event wins (e.g. returned to CP/WS2 after BUMP FINISH)
    if active:
        active_mains = {_main_code(e['main']) for e in active}
        if len(active_mains) > 1:
            prior_mains = {
                _main_code(e['main'])
                for e in events
                if _normalize_date(e['date']) < snapshot_date
            }
            newly_seen_mains = active_mains - prior_mains
            if len(newly_seen_mains) == 1:
                return next(iter(newly_seen_mains))

    return _main_code(sorted(pool, key=_event_sort_key)[-1]['main'])


def _collect_events_from_df(df, mother, wafer, file_date, file_mtime):
    events = []
    if df is None or df.empty:
        return events
    for idx, row in df.iterrows():
        if _mother_lot(row.get('C_LOT_NUMBER')) != mother:
            continue
        if _wafer_key(row.get('WAFER_ID')) != wafer:
            continue
        events.append({
            'date': file_date,
            'mtime': file_mtime,
            'row_idx': idx,
            'main': row.get('MAIN'),
            'oper': row.get('OPER'),
            'state': row.get('STATE'),
        })
    return events


def _list_osat_files_up_to(folder, snapshot_path, get_date_fn, target_date=None):
    folder_path = Path(folder)
    snapshot_path = Path(snapshot_path).resolve()
    snap_dt = get_date_fn(str(snapshot_path))

    files = []
    for f in folder_path.glob('*.xls*'):
        try:
            fdt = get_date_fn(str(f))
        except Exception:
            continue
        if fdt > snap_dt:
            continue
        if target_date is not None:
            td = target_date.date() if hasattr(target_date, 'date') else target_date
            if fdt.date() > td:
                continue
        files.append(f)

    files = sorted(files, key=lambda p: (get_date_fn(str(p)), p.stat().st_mtime))
    if snapshot_path not in {p.resolve() for p in files}:
        files.append(snapshot_path)
        files = sorted(files, key=lambda p: (get_date_fn(str(p)), p.stat().st_mtime))
    return files


def dedupe_osat_cross_main_transfer_rows(df, return_audit=False):
    """
    Drop prior-stage TRANSFER rows when the same wafer is already reported under a later MAIN.
    """
    if not is_osat_wip_dataframe(df):
        return (df, pd.DataFrame()) if return_audit else df

    work = df.copy()
    work['_dedup_mother'] = work['C_LOT_NUMBER'].apply(_mother_lot)
    work['_dedup_wafer'] = work['WAFER_ID'].apply(_wafer_key)

    has_wafer = work['_dedup_wafer'].notna()
    if not has_wafer.any():
        return (df, pd.DataFrame()) if return_audit else df

    drop_indices = []

    for (_, _), group in work.loc[has_wafer].groupby(['_dedup_mother', '_dedup_wafer'], sort=False):
        mains = {_main_code(m) for m in group['MAIN'].dropna().unique()}
        if len(mains) <= 1:
            continue

        events = []
        for idx, row in group.iterrows():
            events.append({
                'date': pd.Timestamp('1970-01-01'),
                'mtime': 0,
                'row_idx': idx,
                'main': row.get('MAIN'),
                'oper': row.get('OPER'),
                'state': row.get('STATE'),
            })
        auth_main = pick_authoritative_main(events)
        if not auth_main:
            continue

        for idx, row in group.iterrows():
            main = _main_code(row.get('MAIN'))
            if main != auth_main:
                drop_indices.append(idx)

    if not drop_indices:
        return (df, pd.DataFrame()) if return_audit else df

    audit = _audit_removed_rows(
        work,
        drop_indices,
        'CROSS_MAIN_WAFER_LOCATION',
        'Removed because the same wafer is owned by another active MAIN stage in this snapshot.',
        lambda row: f"{row.get('_dedup_mother', '')}:{row.get('_dedup_wafer', '')}",
    )
    result = df.drop(index=drop_indices).reset_index(drop=True)
    return (result, audit) if return_audit else result


def dedupe_osat_wafer_location_with_history(df, file_path, history_context, include_history_only_conflicts=False, return_audit=False):
    """
    For wafers that appear under multiple MAIN values in the snapshot, scan prior OSAT
    files (up to this snapshot date) and keep only rows for the authoritative MAIN.
    """
    if not is_osat_wip_dataframe(df) or not history_context:
        return (df, pd.DataFrame()) if return_audit else df

    folder = history_context.get('folder')
    read_df = history_context.get('read_df')
    get_date = history_context.get('get_date')
    target_date = history_context.get('target_date')

    if not folder or not read_df or not get_date:
        return (df, pd.DataFrame()) if return_audit else df

    work = df.copy()
    work['_dedup_mother'] = work['C_LOT_NUMBER'].apply(_mother_lot)
    work['_dedup_wafer'] = work['WAFER_ID'].apply(_wafer_key)
    has_wafer = work['_dedup_wafer'].notna()
    if not has_wafer.any():
        return (df, pd.DataFrame()) if return_audit else df

    conflict_keys = set()
    for key, group in work.loc[has_wafer].groupby(['_dedup_mother', '_dedup_wafer'], sort=False):
        mains = {_main_code(m) for m in group['MAIN'].dropna().unique()}
        if len(mains) > 1:
            conflict_keys.add((key[0], key[1]))

    if include_history_only_conflicts:
        for key in work.loc[has_wafer].groupby(['_dedup_mother', '_dedup_wafer'], sort=False).groups:
            conflict_keys.add((key[0], key[1]))

    if not conflict_keys:
        return (df, pd.DataFrame()) if return_audit else df

    try:
        osat_files = _list_osat_files_up_to(folder, file_path, get_date, target_date)
    except Exception as e:
        print(f"OSAT history file list failed: {e}")
        return (df, pd.DataFrame()) if return_audit else df

    drop_indices = []
    auth_main_by_match_key = {}

    for mother, wafer in conflict_keys:
        events = []
        for f in osat_files:
            try:
                hist_df = read_df(str(f))
                if hist_df is None or hist_df.empty:
                    continue
                fdate = get_date(str(f))
                fmtime = Path(f).stat().st_mtime
                events.extend(_collect_events_from_df(hist_df, mother, wafer, fdate, fmtime))
            except Exception:
                continue

        auth_main = pick_authoritative_main(events)
        if not auth_main:
            continue
        auth_main_by_match_key[f"{mother}:{wafer}"] = auth_main

        group = work[(work['_dedup_mother'] == mother) & (work['_dedup_wafer'] == wafer)]
        for idx, row in group.iterrows():
            if _main_code(row.get('MAIN')) != auth_main:
                drop_indices.append(idx)

    if not drop_indices:
        return (df, pd.DataFrame()) if return_audit else df

    audit = _audit_removed_rows(
        work,
        drop_indices,
        'HISTORY_WAFER_LOCATION',
        'Removed because file history shows this wafer belongs to a different latest MAIN stage.',
        lambda row: f"{row.get('_dedup_mother', '')}:{row.get('_dedup_wafer', '')}",
    )
    if not audit.empty and auth_main_by_match_key:
        audit['DEDUP_AUTH_MAIN'] = audit['DEDUP_MATCH_KEY'].map(auth_main_by_match_key).fillna('')
    result = df.drop(index=drop_indices).reset_index(drop=True)
    return (result, audit) if return_audit else result


def drop_sort_transfer_rows_with_downstream_die_wip(df, return_audit=False):
    """
    Drop stale SORT transfer rows when the same mother lot is already in die-level WIP.

    Testing/Packing reports do not preserve WAFER_ID after wafer split, so this rule
    uses only the six-character mother lot for CP/TRANSFER rows.
    """
    if not is_osat_wip_dataframe(df):
        return (df, pd.DataFrame()) if return_audit else df

    work = df.copy()
    work['_dedup_mother'] = work['C_LOT_NUMBER'].apply(_mother_lot)
    main = work['MAIN'].apply(_main_code)
    state_kind = work['STATE'].apply(_state_kind)

    downstream_mothers = set(work.loc[
        main.eq('FT')
        & state_kind.isin(('active', 'transfer', 'other'))
        & work['_dedup_mother'].ne(''),
        '_dedup_mother',
    ])

    if not downstream_mothers:
        return (df, pd.DataFrame()) if return_audit else df

    drop_mask = (
        main.eq('CP')
        & work['STATE'].apply(_is_transfer_state)
        & work['_dedup_mother'].isin(downstream_mothers)
    )

    if not drop_mask.any():
        return (df, pd.DataFrame()) if return_audit else df

    drop_indices = list(work.index[drop_mask])
    audit = _audit_removed_rows(
        work,
        drop_indices,
        'STALE_SORT_TRANSFER_DOWNSTREAM_DIE',
        'Removed because the same mother lot is already present in downstream FT die-level WIP.',
        lambda row: row.get('_dedup_mother', ''),
    )
    result = df.drop(index=drop_indices).reset_index(drop=True)
    return (result, audit) if return_audit else result


def drop_same_main_transfer_duplicates(df, return_audit=False):
    """
    Drop transfer rows when the same wafer also has a live row in the same wafer-level MAIN stage.

    This handles intra-stage duplicates such as CP/WS2 WAIT and CP/TF TRANSFER for
    the same mother lot + wafer. A standalone transfer row is kept because it may be
    the only available WIP location evidence for that wafer.
    """
    if not is_osat_wip_dataframe(df):
        return (df, pd.DataFrame()) if return_audit else df

    work = df.copy()
    work['_dedup_mother'] = work['C_LOT_NUMBER'].apply(_mother_lot)
    work['_dedup_wafer'] = work['WAFER_ID'].apply(_wafer_key)
    work['_dedup_main'] = work['MAIN'].apply(_main_code)
    work['_dedup_state_kind'] = work['STATE'].apply(_state_kind)
    work['_dedup_is_transfer'] = work['STATE'].apply(_is_transfer_state)

    has_wafer = work['_dedup_wafer'].notna() & work['_dedup_main'].isin(('CP', 'BUMP'))
    if not has_wafer.any():
        return (df, pd.DataFrame()) if return_audit else df

    drop_indices = []
    for (_, _, _), group in work.loc[has_wafer].groupby(
        ['_dedup_mother', '_dedup_wafer', '_dedup_main'],
        sort=False,
    ):
        has_live_non_transfer = (
            (~group['_dedup_is_transfer'])
            & group['_dedup_state_kind'].isin(('active', 'other'))
        ).any()
        if not has_live_non_transfer:
            continue
        drop_indices.extend(group.index[group['_dedup_is_transfer']].tolist())

    if not drop_indices:
        return (df, pd.DataFrame()) if return_audit else df

    audit = _audit_removed_rows(
        work,
        drop_indices,
        'SAME_MAIN_TRANSFER_DUPLICATE',
        'Removed because the same wafer also has a live non-transfer row in the same MAIN stage.',
        lambda row: f"{row.get('_dedup_mother', '')}:{row.get('_dedup_wafer', '')}:{row.get('_dedup_main', '')}",
    )
    result = df.drop(index=drop_indices).reset_index(drop=True)
    return (result, audit) if return_audit else result


def _has_valid_sort_work_order(sort_work_orders_by_mother, mother, snapshot_date):
    records = (sort_work_orders_by_mother or {}).get(mother, [])
    if not records:
        return False
    snapshot_day = _date_or_none(snapshot_date)
    for record in records:
        wo_date = _date_or_none(record.get('work_order_date') if isinstance(record, dict) else record)
        if snapshot_day is None or wo_date is None or wo_date <= snapshot_day:
            return True
    return False


def drop_terminal_osat_wip_rows(df, return_audit=False, work_order_context=None, snapshot_date=None):
    """Remove completed/finished OSAT rows only when another live row owns the item."""
    if not is_osat_wip_dataframe(df):
        return (df, pd.DataFrame()) if return_audit else df

    work = df.copy()
    work['_dedup_mother'] = work['C_LOT_NUMBER'].apply(_mother_lot)
    work['_dedup_wafer'] = work['WAFER_ID'].apply(_wafer_key)
    work['_dedup_state_kind'] = work['STATE'].apply(_state_kind)

    completed_ft_bin_mask = (
        work['MAIN'].apply(_main_code).eq('FT')
        & work.get('LOCATION', pd.Series('', index=work.index)).apply(_is_completed_ft_bin_value)
    )
    terminal_mask = work['_dedup_state_kind'].eq('terminal') & ~completed_ft_bin_mask
    if not terminal_mask.any():
        return (df, pd.DataFrame()) if return_audit else df

    live_rows = work.loc[~terminal_mask]
    live_wafer_keys = {
        (row['_dedup_mother'], row['_dedup_wafer'])
        for _, row in live_rows[live_rows['_dedup_wafer'].notna()].iterrows()
        if row['_dedup_mother']
    }
    live_mothers_without_wafer = {
        row['_dedup_mother']
        for _, row in live_rows[live_rows['_dedup_wafer'].isna()].iterrows()
        if row['_dedup_mother']
    }
    live_downstream_orders_by_mother = {}
    live_main_orders_by_mother = {}
    for _, row in live_rows.iterrows():
        mother = row.get('_dedup_mother')
        main = _main_code(row.get('MAIN'))
        main_order = MAIN_STAGE_ORDER.get(main)
        if not mother:
            continue
        if main_order is not None:
            live_downstream_orders_by_mother.setdefault(mother, set()).add(main_order)
        live_main_orders_by_mother.setdefault(mother, set()).add(main)

    sort_work_orders_by_mother = (work_order_context or {}).get('sort_work_orders_by_mother', {})

    drop_indices = []
    drop_reasons = {}
    for idx, row in work.loc[terminal_mask].iterrows():
        mother = row.get('_dedup_mother')
        wafer = row.get('_dedup_wafer')
        main = _main_code(row.get('MAIN'))
        terminal_order = MAIN_STAGE_ORDER.get(_main_code(row.get('MAIN')))
        if not mother:
            continue
        if wafer is not None:
            if (mother, wafer) in live_wafer_keys:
                drop_indices.append(idx)
                drop_reasons[idx] = 'Removed because STATE is terminal and another non-terminal row owns the same wafer.'
            elif terminal_order is not None and any(
                live_order > terminal_order
                for live_order in live_downstream_orders_by_mother.get(mother, set())
            ):
                drop_indices.append(idx)
                drop_reasons[idx] = 'Removed because STATE is terminal and the same mother lot is live in a downstream stage.'
            elif (
                main == 'BUMP'
                and 'CP' in live_main_orders_by_mother.get(mother, set())
            ):
                drop_indices.append(idx)
                if _has_valid_sort_work_order(sort_work_orders_by_mother, mother, snapshot_date):
                    drop_reasons[idx] = 'Removed because STATE is terminal, the same mother lot has live Sort WIP, and a SORT work order supports the BUMP-to-Sort transition.'
                else:
                    drop_reasons[idx] = 'Removed because STATE is terminal and the same mother lot has live Sort WIP.'
        elif mother in live_mothers_without_wafer:
            drop_indices.append(idx)
            drop_reasons[idx] = 'Removed because STATE is terminal and another non-terminal row owns the same mother lot.'

    if not drop_indices:
        return (df, pd.DataFrame()) if return_audit else df

    audit = _audit_removed_rows(
        work,
        drop_indices,
        'TERMINAL_WIP_ROW',
        'Removed because STATE is terminal and another non-terminal row owns the same wafer or mother lot.',
        lambda row: f"{row.get('_dedup_mother', '')}:{row.get('_dedup_wafer', '') or ''}",
    )
    if not audit.empty and drop_reasons:
        for pos, idx in enumerate(list(dict.fromkeys(drop_indices))):
            if idx in drop_reasons:
                audit.loc[pos, 'DEDUP_REASON'] = drop_reasons[idx]
    result = df.drop(index=drop_indices).reset_index(drop=True)
    return (result, audit) if return_audit else result


def prepare_osat_dataframe(df, file_path, history_context=None, include_history_only_conflicts=False, exclude_terminal_wip=False, return_audit=False):
    """Apply OSAT WIP de-duplication.

    When file history is available, use it before the same-snapshot fallback so
    a wafer that moved from CP on an older snapshot to BUMP on the selected
    snapshot is owned by BUMP even if both rows still appear in the selected
    file. Without this ordering, row order inside one file can incorrectly make
    the older CP row win before history gets a chance to resolve ownership.
    """
    if df is None or df.empty:
        return (df, pd.DataFrame()) if return_audit else df

    audit_frames = []
    if history_context:
        if return_audit:
            df, audit = dedupe_osat_wafer_location_with_history(
                df,
                file_path,
                history_context,
                include_history_only_conflicts=include_history_only_conflicts,
                return_audit=True,
            )
            audit_frames.append(audit)
        else:
            df = dedupe_osat_wafer_location_with_history(
                df,
                file_path,
                history_context,
                include_history_only_conflicts=include_history_only_conflicts,
            )

    if return_audit:
        df, audit = dedupe_osat_cross_main_transfer_rows(df, return_audit=True)
        audit_frames.append(audit)
        df, audit = drop_same_main_transfer_duplicates(df, return_audit=True)
        audit_frames.append(audit)
        df, audit = drop_sort_transfer_rows_with_downstream_die_wip(df, return_audit=True)
        audit_frames.append(audit)
    else:
        df = dedupe_osat_cross_main_transfer_rows(df)
        df = drop_same_main_transfer_duplicates(df)
        df = drop_sort_transfer_rows_with_downstream_die_wip(df)

    if exclude_terminal_wip:
        if return_audit:
            df, audit = drop_terminal_osat_wip_rows(
                df,
                return_audit=True,
                work_order_context=(history_context or {}).get('work_order_context') if history_context else None,
                snapshot_date=(history_context or {}).get('snapshot_date') if history_context else None,
            )
            audit_frames.append(audit)
        else:
            df = drop_terminal_osat_wip_rows(
                df,
                work_order_context=(history_context or {}).get('work_order_context') if history_context else None,
                snapshot_date=(history_context or {}).get('snapshot_date') if history_context else None,
            )

    if return_audit:
        audit = _add_audit_explanations(_merge_audit_frames(audit_frames), file_path, history_context)
        return df, audit
    return df
