"""
Plan Yukta pilot web app.

Upload a filled Plan Yukta workbook (or run the bundled synthetic sample) and
get the planning view back, plus a results workbook. Uploads are processed in
memory and never written to disk or kept after the response.

Local:   python app.py                      -> http://127.0.0.1:5000
Render:  gunicorn app:app (see render.yaml)
"""
from __future__ import annotations

import base64
import hmac
import io
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path

import markdown
import pandas as pd
import json
import time

from flask import (Flask, abort, jsonify, redirect, render_template, request, send_from_directory,
                   session, url_for)

from plan_yukta.engine import OSAT_OPERATIONS, STAGE_SEQUENCE, TemplateError, read_workbook, run_plan
from plan_yukta import assistant, format_spec
from plan_yukta.planning import (STAGE_LABEL, PlanningInputError, b2b_workbook, run_planning,
                                 settings_from_values, product_params, worked_example)

HERE = Path(__file__).parent
STATIC = HERE / 'static'
SAMPLE = STATIC / 'PlanYukta_Sample.xlsx'
TEMPLATE = STATIC / 'PlanYukta_Template.xlsx'

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_UPLOAD_MB', '25')) * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('RENDER') == 'true'  # HTTPS on Render
FEEDBACK_URL = os.environ.get('FEEDBACK_URL', '')  # e.g. a Google Form for pilot testers
logging.basicConfig(level=logging.INFO)


def _testers() -> dict:
    """PILOT_ACCESS='name1:code1, name2:code2'. Empty means the site is open (local use)."""
    pairs = {}
    for item in os.environ.get('PILOT_ACCESS', '').split(','):
        if ':' in item:
            name, code = item.split(':', 1)
            if name.strip() and code.strip():
                pairs[name.strip()] = code.strip()
    return pairs


@app.before_request
def _require_access():
    if not _testers() or request.endpoint in ('login', 'static', 'healthz'):
        return None
    if session.get('tester') not in _testers():   # removed testers lose access on next request
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Your session has ended. Please sign in again.'}), 401
        return redirect(url_for('login', next=request.path))
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not _testers():
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        match = next((name for name, c in _testers().items() if hmac.compare_digest(c, code)), None)
        if match:
            session.clear()
            session['tester'] = match
            app.logger.info('PILOT login tester=%s at=%s', match, datetime.utcnow().isoformat())
            target = request.args.get('next', '/')
            return redirect(target if target.startswith('/') and not target.startswith('//') else '/')
        error = 'That access code is not valid. Check the code you were sent, or ask the pilot owner.'
        app.logger.info('PILOT failed login at=%s', datetime.utcnow().isoformat())
    return render_template('login.html', error=error)


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login') if _testers() else url_for('index'))


@app.context_processor
def _globals():
    return {'feedback_url': FEEDBACK_URL, 'tester': session.get('tester'), 'access_on': bool(_testers()),
            'chat_ai': assistant.ai_enabled()}


CHAT_LIMIT = int(os.environ.get('CHAT_LIMIT_PER_HOUR', '30'))


@app.post('/api/chat')
def chat():
    payload = request.get_json(silent=True) or {}
    now = time.time()
    recent = [t for t in session.get('chat_times', []) if now - t < 3600]
    if len(recent) >= CHAT_LIMIT:
        return jsonify({'answer': f'You have reached {CHAT_LIMIT} questions this hour. Please try again later.',
                        'mode': 'limit'})
    session['chat_times'] = recent + [now]
    result = assistant.ask(payload.get('question', ''), payload.get('context', ''), payload.get('history') or [])
    app.logger.info('PILOT chat tester=%s mode=%s', session.get('tester', '-'), result['mode'])
    return jsonify(result)


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
        pr = res.get('planning')
        if pr:
            pr['summary'].to_excel(xw, sheet_name='Plan_Summary', index=False)
            pr['alerts'].to_excel(xw, sheet_name='Plan_Alerts', index=False)
            pr['accuracy'].to_excel(xw, sheet_name='Forecast_Accuracy', index=False)
            fd = pr['final_demand'].copy(); fd['MONTH'] = fd['MONTH'].dt.strftime('%Y-%m')
            fd.to_excel(xw, sheet_name='Demand_Plan', index=False)
            pl = pr['plan'].copy(); pl['MONTH'] = pl['MONTH'].dt.strftime('%Y-%m')
            pl.to_excel(xw, sheet_name='Supply_Plan', index=False)
            st = pr['stages'].copy(); st['MONTH'] = st['MONTH'].dt.strftime('%Y-%m'); st['qty'] = st['qty'].round()
            st.to_excel(xw, sheet_name='Module_Loads', index=False)
            te = pr['testers'].copy(); te['MONTH'] = te['MONTH'].dt.strftime('%Y-%m')
            te.to_excel(xw, sheet_name='Tester_Capacity_Plan', index=False)
            pr['tester_detail'].to_excel(xw, sheet_name='Tester_Throughput', index=False)
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


def svg_forecast(hist: pd.DataFrame, plan: pd.DataFrame, product: str) -> str:
    """Small inline SVG: last 12 months of actuals, statistical and final forecast."""
    h = hist[(hist['PRODUCT'] == product) & (hist['TYPE'] == 'ACTUAL')].groupby('MONTH')['QTY'].sum().sort_index().tail(12)
    f = plan[plan['PRODUCT'] == product].sort_values('MONTH')
    pts_h = list(h.items())
    months_all = [m for m, _ in pts_h] + list(f['MONTH'])
    if not months_all:
        return ''
    vals = [v for _, v in pts_h] + list(f['final_demand']) + list(f['stat_fcst']) + \
           [v for v in f['customer_fcst'] if v is not None and not pd.isna(v)]
    vmax = max(vals + [1]) * 1.1
    W, H, L, B = 560, 170, 46, 22
    n = len(months_all)
    x = lambda i: L + (W - L - 10) * i / max(1, n - 1)
    y = lambda v: 8 + (H - B - 8) * (1 - v / vmax)
    def line(points, cls, dash=''):
        if len(points) < 2:
            return ''
        d = ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in points)
        return f'<polyline class="{cls}" fill="none" points="{d}"{dash}/>'
    k = len(pts_h)
    hist_pts = [(i, v) for i, (_, v) in enumerate(pts_h)]
    final_pts = ([(k - 1, pts_h[-1][1])] if pts_h else []) + [(k + i, v) for i, v in enumerate(f['final_demand'])]
    stat_pts = ([(k - 1, pts_h[-1][1])] if pts_h else []) + [(k + i, v) for i, v in enumerate(f['stat_fcst'])]
    cust = [(k + i, v) for i, v in enumerate(f['customer_fcst']) if v is not None and not pd.isna(v)]
    grid = ''.join(f'<line class="g" x1="{L}" x2="{W-10}" y1="{y(vmax*t):.1f}" y2="{y(vmax*t):.1f}"/>'
                   f'<text class="t" x="{L-6}" y="{y(vmax*t)+4:.1f}" text-anchor="end">{vmax*t/1000:,.0f}k</text>'
                   for t in (0, 0.5, 1.0) if vmax)
    labels = ''.join(f'<text class="t" x="{x(i):.1f}" y="{H-6}" text-anchor="middle">{m:%b %y}</text>'
                     for i, m in enumerate(months_all) if i % 3 == 0)
    divider = f'<line class="now" x1="{x(k-0.5):.1f}" x2="{x(k-0.5):.1f}" y1="6" y2="{H-B}"/>' if k else ''
    dots = ''.join(f'<circle class="cust" cx="{x(i):.1f}" cy="{y(v):.1f}" r="3"/>' for i, v in cust)
    return (f'<svg viewBox="0 0 {W} {H}" class="fc" role="img" aria-label="Demand history and forecast for {product}">'
            f'{grid}{divider}{line(hist_pts, "hist")}{line(stat_pts, "stat", " stroke-dasharray=\'4 3\'")}'
            f'{line(final_pts, "final")}{dots}{labels}</svg>')


def planning_view(pr: dict):
    if not pr:
        return None
    s = pr['settings']
    labels = pr['b2b']['labels']
    # module loads: one row per module, summed over products
    st = pr['stages'].copy()
    st['m'] = st['MONTH'].dt.strftime('%Y-%m')
    modules = []
    for stage in ['FAB', 'BUMP', 'SORT', 'ASSY', 'FT']:
        sub = st[st['STAGE'] == stage].groupby('m')['qty'].sum()
        vals = [float(sub.get(l, 0)) for l in labels]
        top = max(vals + [1])
        modules.append({'name': STAGE_LABEL[stage], 'unit': 'wafers' if stage in ('FAB', 'BUMP', 'SORT') else 'units',
                        'cells': [(f'{v:,.0f}' if v else '–', round(v / top * 100)) for v in vals]})
    te = pr['testers'].copy()
    te['m'] = te['MONTH'].dt.strftime('%Y-%m')
    testers = []
    for t, g in te.groupby('TESTER_TYPE', sort=False):
        g = g.set_index('m')
        testers.append({'name': t, 'osat': g['OSAT'].iloc[0], 'count': g['testers'].iloc[0],
                        'cells': [{'pct': g.loc[l, 'utilisation_pct'], 'hrs': g.loc[l, 'hours_required'],
                                   'need': g.loc[l, 'testers_needed'], 'status': g.loc[l, 'status']}
                                  for l in labels if l in g.index]})
    plans = []
    for prod in pr['summary']['PRODUCT']:
        pl = pr['plan'][pr['plan']['PRODUCT'] == prod]
        rows = {
            'Demand (units)': pl['demand'], 'Receipts from current WIP': pl['wip_receipts'],
            'Planned receipts (new)': pl['planned_receipts'], 'Projected finished goods': pl['projected_fg'],
            'Safety stock target': pl['safety_stock'], 'Weeks of supply': pl['weeks_of_supply'],
            'Die bank (good die)': pl['die_bank'],
        }
        stp = st[st['PRODUCT'] == prod]
        for stage in ['FAB', 'BUMP', 'SORT', 'ASSY', 'FT']:
            sub = stp[stp['STAGE'] == stage].groupby('m')['qty'].sum()
            if sub.sum() > 0:
                rows[f'{STAGE_LABEL[stage]} load'] = pd.Series([sub.get(l, 0) for l in labels])
        table = []
        for k, series in rows.items():
            vals = list(series)
            cells = []
            for v in vals:
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    cells.append('')
                elif k == 'Weeks of supply':
                    cells.append(f'{v:.1f}')
                else:
                    cells.append(f'{v:,.0f}' if v else '–')
            neg = k == 'Projected finished goods'
            table.append({'label': k, 'cells': cells, 'warn': [neg and isinstance(v, (int, float)) and v < 0 for v in vals]})
        acc = pr['accuracy'][pr['accuracy']['PRODUCT'] == prod]
        a = acc.iloc[0].to_dict() if not acc.empty else {}
        params = pr['params'][prod]
        plans.append({'product': prod, 'table': table, 'svg': svg_forecast(pr['demand_history'], pr['final_demand'], prod),
                      'acc': a, 'upw': params['units_per_wafer'], 'lt': params['lt_total_wk'],
                      'sources': ', '.join(sorted(set(pr['final_demand'][pr['final_demand']['PRODUCT'] == prod]['source'])))})
    fab = pr['b2b']['fab']
    osat = pr['b2b']['osat']
    return {
        'settings': s, 'labels': labels, 'zones': pr['b2b']['zones'], 'modules': modules, 'testers': testers,
        'plans': plans,
        'summary': _table(pr['summary'], {'PRODUCT': 'Product', 'demand_total': 'Demand in horizon (units)',
                                          'units_per_wafer': 'Good units per wafer', 'total_lead_time_wk': 'Total lead time (wk)',
                                          'wafer_starts_total': 'New wafer starts', 'min_weeks_of_supply': 'Lowest weeks of supply',
                                          'alerts': 'Alerts'}),
        'alerts': _table(pr['alerts'], {'PRODUCT': 'Product / tester', 'month': 'Month', 'issue': 'Issue', 'detail': 'What it means'}),
        'tester_detail': _table(pr['tester_detail']),
        'fab': fab, 'osat': osat, 'calendar': pr['b2b']['calendar'],
        'b2b_b64': base64.b64encode(b2b_workbook(pr['b2b'], {'plan_start': f"{s.plan_start:%Y-%m}",
                                                              'horizon': s.horizon_months})).decode(),
    }


def chat_context(res: dict) -> str:
    """Compact summary of the current results for the chat assistant."""
    out = {'as_of': str(res['settings'].as_of),
           'material_now_by_product': res['overview'].to_dict('records'),
           'duplicate_rows_removed': int(res['osat_rows_latest'] - res['osat_rows_kept']),
           'capacity_check': res['capacity'][['MASTER_PRODUCT', 'status']].to_dict('records'),
           'late_fab_lots': len(res['late_lots']), 'unmapped_osat_names': res['unmapped_partnames']}
    pr = res.get('planning')
    if pr:
        te = pr['testers'].copy(); te['MONTH'] = te['MONTH'].dt.strftime('%Y-%m')
        out.update({
            'plan_settings': {'start': str(pr['settings'].plan_start), 'horizon_months': pr['settings'].horizon_months,
                              'method': pr['settings'].forecast_method, 'uplift_pct': pr['settings'].demand_uplift_pct,
                              'overrides': pr['settings'].overrides},
            'plan_summary': pr['summary'].to_dict('records'),
            'forecast_accuracy': pr['accuracy'].to_dict('records'),
            'alerts': pr['alerts'].head(15).to_dict('records'),
            'tester_utilisation_pct': te.pivot_table(index='TESTER_TYPE', columns='MONTH',
                                                     values='utilisation_pct').round(0).to_dict('index'),
        })
    return json.dumps(out, default=str)[:6000]


def render_results(res: dict, source_name: str, is_sample: bool):
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
    return render_template(
        'results.html', res=res, source_name=source_name, is_sample=is_sample, kpis=kpis,
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
        xlsx_b64=xlsx, plan=planning_view(res.get('planning')), planning_error=res.get('planning_error'),
        chat_context=chat_context(res),
    )


def _apply_playground(settings, form):
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


def _plan_overrides(ps, form):
    """Planning levers from the playground form (applied to every product)."""
    def f(name, lo, hi):
        try:
            v = form.get(name, '')
            return None if v == '' else max(lo, min(hi, float(v)))
        except ValueError:
            return None
    if form.get('forecast_method') in ('BLEND', 'CUSTOMER', 'STAT'):
        ps.forecast_method = form['forecast_method']
    v = f('demand_uplift_pct', -90, 300)
    if v is not None: ps.demand_uplift_pct = v
    v = f('horizon_months', 3, 18)
    if v is not None: ps.horizon_months = int(v)
    o = {}
    v = f('safety_stock_wk', 0, 26);  o['SAFETY_STOCK_WK'] = v
    v = f('sort_yield_pct', 10, 100); o['SORT_YIELD'] = None if v is None else v / 100
    v = f('ct_fab_wk', 4, 30);        o['CT_FAB_WK'] = v
    v = f('extra_testers', -5, 20);   o['extra_testers'] = v
    v = f('oee_pct', 20, 100);        o['oee'] = None if v is None else v / 100
    v = f('test_time_pct', -50, 200); o['test_time_pct'] = v
    ps.overrides = {k: v for k, v in o.items() if v is not None}


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/format')
def upload_format():
    return render_template('format.html', sheets=format_spec.SHEETS, rules=format_spec.RULES)


_EXAMPLE = {}


def guide_example():
    """Worked backward-planning example built from the sample workbook's own parameters."""
    if not _EXAMPLE:
        d = read_workbook(SAMPLE)['planning']
        params = product_params(d['plan_params'], {})
        _EXAMPLE['ex'] = worked_example(params, d['tester_params'], 'ORION B0', 400_000, '2027-06-01')
    return _EXAMPLE['ex']


@app.get('/guide')
def guide():
    return render_template('guide.html', ex=guide_example())


@app.get('/method')
def method():
    html = markdown.markdown((HERE / 'CALCULATIONS.md').read_text(encoding='utf-8'), extensions=['tables'])
    return render_template('method.html', body=html)


@app.get('/download/<name>')
def download(name):
    allowed = {'template': TEMPLATE.name, 'sample': SAMPLE.name}
    if name not in allowed:
        abort(404)
    return send_from_directory(STATIC, allowed[name], as_attachment=True)


@app.post('/run')
def run():
    use_sample = request.form.get('sample') == '1'
    try:
        if use_sample:
            data, name = read_workbook(SAMPLE), 'Synthetic sample workbook'
            _apply_playground(data['settings'], request.form)
        else:
            f = request.files.get('workbook')
            if not f or not f.filename:
                return render_template('index.html', error='Choose a workbook to upload first.'), 400
            if not f.filename.lower().endswith(('.xlsx', '.xlsm')):
                return render_template('index.html', error='Upload an .xlsx file made from the Plan Yukta template.'), 400
            data, name = read_workbook(io.BytesIO(f.read())), f.filename
        res = run_plan(data)
        res['planning'] = None
        if data.get('planning'):
            try:
                ps = settings_from_values(data['settings'].plan_values, data['settings'].as_of)
                if use_sample:
                    _plan_overrides(ps, request.form)
                res['planning'] = run_planning(data['planning'], res, ps)
            except (PlanningInputError, KeyError, ValueError) as exc:
                res['planning_error'] = f'Planning could not run: {exc}'
        app.logger.info('PILOT run tester=%s source=%s', session.get('tester', '-'), 'sample' if use_sample else 'upload')
    except TemplateError as exc:
        return render_template('index.html', error=str(exc)), 400
    except Exception as exc:  # noqa: BLE001 - show pilot testers something useful
        app.logger.exception('Plan run failed')
        return render_template('index.html', error=f'The plan could not be run: {exc}'), 500
    return render_results(res, name, use_sample)


@app.errorhandler(413)
def too_large(_):
    mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return render_template('index.html', error=f'That file is over the {mb} MB pilot limit.'), 413


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', port=int(os.environ.get('PORT', 5000)))
