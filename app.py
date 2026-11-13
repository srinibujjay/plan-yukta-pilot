"""
Plan Yukta pilot: fabless supply-chain planning cockpit.

Every visitor works on their own copy of the synthetic demo data (a workspace). They
can edit any data table in the browser, upload their own tables, and every module
recalculates from it. A separate lot-level WIP audit (upload a workbook) is kept too.

Local:   python app.py                      -> http://127.0.0.1:5000
Render:  gunicorn app:app (see render.yaml)
"""
from __future__ import annotations

import hmac
import re
import io
import json
import logging
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

import markdown
from flask import (Flask, Response, abort, jsonify, redirect, render_template, request, send_file,
                   send_from_directory, session, url_for)

from plan_yukta import assistant, cockpit, exports, modules, views, pf_views, integrations as IG
from plan_yukta import workspace as W

HERE = Path(__file__).parent
STATIC = HERE / 'static'
SAMPLE = STATIC / 'PlanYukta_Sample.xlsx'
TEMPLATE = STATIC / 'PlanYukta_Template.xlsx'

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_UPLOAD_MB', '25')) * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('RENDER') == 'true'
FEEDBACK_URL = os.environ.get('FEEDBACK_URL', '')
CHAT_LIMIT = int(os.environ.get('CHAT_LIMIT_PER_HOUR', '30'))
logging.basicConfig(level=logging.INFO)


# ------------------------------------------------------------------ access
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
    if not _testers() or request.endpoint in ('login', 'static', 'healthz', 'api_test_results'):
        return None
    if session.get('tester') not in _testers():
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Your session has ended. Please sign in again.'}), 401
        return redirect(url_for('login', next=request.path))
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not _testers():
        return redirect(url_for('home'))
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
    return redirect(url_for('login') if _testers() else url_for('home'))


# ------------------------------------------------------------------ workspace
def ws_get():
    wsid = session.get('ws')
    ws = W.load(wsid) if wsid else None
    if ws is None:
        wsid = W.new_id()
        ws = W.save(wsid, W.demo_workspace())
        session['ws'] = wsid
        session.permanent = True
    return wsid, ws


_cache = {}


def results(wsid, ws):
    key = (wsid, ws.get('version'), ws.get('saved_at'))
    hit = _cache.get(wsid)
    if hit and hit[0] == key:
        return hit[1]
    R = cockpit.compute(ws)
    if len(_cache) > 64:
        _cache.clear()
    _cache[wsid] = (key, R)
    return R


_base_cache = {}


def baseline_results(wsid, ws):
    """The same plan with every override switched off, for the with/without comparison."""
    key = (wsid, ws.get('version'), ws.get('saved_at'))
    hit = _base_cache.get(wsid)
    if hit and hit[0] == key:
        return hit[1]
    Rb = cockpit.compute(ws, apply_overrides=False)
    if len(_base_cache) > 64:
        _base_cache.clear()
    _base_cache[wsid] = (key, Rb)
    return Rb


def edited_tables(ws):
    return sorted(ws.get('edited', []))


@app.context_processor
def _globals():
    return {'feedback_url': FEEDBACK_URL, 'tester': session.get('tester'), 'access_on': bool(_testers()),
            'chat_ai': assistant.ai_enabled(), 'nav_groups': modules.nav_groups(), 'icons': modules.ICONS, 'nav_sub': modules.SUB,
            'tables_meta': W.TABLES, 'mlabel': views.mlabel, 'nav_label': modules.label}


def _fmt(v, fmt):
    if v is None or v == '':
        return '–' if fmt not in ('text', 'badge', 'link') else ''
    try:
        if fmt == 'int':
            return f'{float(v):,.0f}'
        if fmt == 'num0':
            return f'{float(v):,.0f}'
        if fmt == 'num1':
            return f'{float(v):,.1f}'
        if fmt == 'num2':
            return f'{float(v):,.2f}'
        if fmt == 'pct':
            return f'{float(v):.0f}%'
        if fmt == 'money':
            return views.money(float(v))
        if fmt == 'money2':
            return f'${float(v):,.2f}'
        if fmt == 'money4':
            return f'${float(v):,.4f}'
        if fmt == 'month':
            return views.mlabel(str(v)) if len(str(v)) >= 7 else str(v)
        if fmt == 'date':
            return v.strftime('%d %b %Y') if hasattr(v, 'strftime') else str(v)
    except (TypeError, ValueError):
        return str(v)
    return str(v)


def safe_json(obj) -> str:
    """JSON that can sit inside a <script> tag."""
    return json.dumps(obj, default=str).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


app.jinja_env.filters['fmt'] = _fmt
app.jinja_env.filters['short'] = views.short
app.jinja_env.filters['money'] = views.money


def nav_badges(R):
    c = R['checks']['items']
    return {'checks': sum(1 for x in c if x['severity'] in ('error', 'warning')),
            'home': len([a for a in R['home']['alerts'] if a['severity'] == 'high'])}


def render_page(key, d, R, ws, **kw):
    tpl = d.pop('template', 'module.html') if isinstance(d, dict) else 'module.html'
    ctx = page_context(key, R, ws)
    return render_template(tpl, page=d, key=key, R=R, ws=ws, badges=nav_badges(R), chat_context=ctx,
                           args=request.args, next_key=modules.next_key(key), **kw)


def page_context(key, R, ws):
    """Short summary of what is on screen, for the chat assistant."""
    h = R['home']
    out = {'page': modules.label(key), 'plan_start': R['plan'].start, 'horizon_months': R['plan'].H,
           'as_of': str(R['plan'].as_of), 'edited_tables': edited_tables(ws),
           'alerts': [f"{a['module']} {a['month']}: {a['text']}" for a in h['alerts'][:10]],
           'peak_tester_load': f'{h["load_peak"][0]:.0f}% at OSAT-{h["load_peak"][1]} {h["load_peak"][2]} in {h["load_peak"][3]}',
           'customer_shortfall_units': round(h['short']), 'plan_revenue_usd': round(h['revenue']), 'gross_margin_pct': round(h['gm'], 1),
           'data_checks': [c['message'] for c in R['checks']['items'][:8]]}
    return safe_json(out)[:6000]


# ------------------------------------------------------------------ pages
BUILDERS = {
    'demand': views.demand, 'testing': views.testing, 'pullin': views.pullin, 'assembly': views.assembly,
    'frontend': views.frontend, 'flow': views.flow, 'testers': views.testers, 'hardware': views.hardware,
    'ate': views.ate, 'npi': views.npi, 'fab-po': views.fab_po, 'osat-po': views.osat_po, 'substrate': views.substrate,
    'cross-flow': views.cross_flow, 'b2b': views.b2b, 'pva': views.pva, 'cost': views.cost, 'pnl': views.pnl,
    'm1-dashboard': views.m1_dashboard, 'flow-dashboard': views.flow_dashboard,
    'vendor-qbr': views.vendor_qbr, 'customers': views.customers, 'inventory': views.inventory,
}
PF_BUILDERS = {
    'pf-overview': pf_views.overview, 'pf-roadmap': pf_views.roadmap, 'pf-capacity': pf_views.capacity, 'pf-priority': pf_views.priority,
    'pf-scenarios': pf_views.scenario, 'pf-board': pf_views.board, 'pf-raid': pf_views.raid, 'pf-integrations': pf_views.integrations,
}


@app.get('/')
def home():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    return render_page('home', views.home(R, request.args), R, ws, tour=modules.TOUR[:4])


@app.get('/m/<key>')
def module_page(key):
    wsid, ws = ws_get()
    R = results(wsid, ws)
    if key in BUILDERS:
        return render_page(key, BUILDERS[key](R, request.args), R, ws)
    if key in PF_BUILDERS:
        return render_page(key, PF_BUILDERS[key](R, request.args, ws), R, ws)
    if key == 'postsilicon':
        return render_page(key, views.postsilicon(R, request.args, token=api_token(wsid), base_url=request.host_url), R, ws)
    if key == 'overrides':
        Rb = baseline_results(wsid, ws)
        return render_page(key, views.overrides(R, Rb, request.args, ws), R, ws)
    if key == 'snapshots':
        return render_page(key, views.snapshots(R, request.args, ws), R, ws)
    if key == 'atp':
        return render_page(key, views.page('atp', [], extra={'template': 'atp.html'}), R, ws, **atp_context(R, ws))
    if key == 'osat-wip':
        return render_page(key, views.page('osat-wip', [], extra={'template': 'osat_wip.html'}), R, ws, W=R['osat_wip'])
    if key == 'checks':
        return render_page(key, views.page('checks', [], extra={'template': 'checks.html'}), R, ws)
    if key == 'sku-setup':
        return render_page(key, views.page('sku-setup', [], extra={'template': 'sku_setup.html'}), R, ws, products=ws['tables']['products'],
                           vendors=ws['tables']['vendors'], months=R['plan'].months)
    if key == 'io':
        return render_page(key, views.page('io', [], extra={'template': 'io.html'}), R, ws, edited=edited_tables(ws))
    if key == 'tour':
        return render_page(key, views.page('tour', [], extra={'template': 'tour.html'}), R, ws, tour=modules.TOUR)
    if key == 'method':
        body = markdown.markdown((HERE / 'CALCULATIONS.md').read_text(encoding='utf-8'), extensions=['tables'])
        return render_page(key, views.page('method', [], extra={'template': 'method.html'}), R, ws, body=body)
    if key == 'data':
        return redirect(url_for('data_index'))
    if key == 'audit':
        return redirect(url_for('audit_index'))
    abort(404)


# ------------------------------------------------------------------ data tables
@app.get('/data')
def data_index():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    groups = [(g, [(k, m, len(ws['tables'].get(k, []))) for k, m in W.TABLES.items() if m['group'] == g]) for g in W.GROUPS]
    return render_page('data', views.page('data', [], extra={'template': 'data_index.html'}), R, ws, groups=groups, edited=edited_tables(ws))


@app.get('/data/<table>')
def data_table(table):
    if table not in W.TABLES:
        abort(404)
    wsid, ws = ws_get()
    R = results(wsid, ws)
    meta = W.TABLES[table]
    cols = [dict(c) for c in meta['columns']]
    setting_cols = {name: W.setting_col(name) for name in W.SETTINGS} if table == 'settings' else {}
    payload = {'table': table, 'columns': cols, 'rows': ws['tables'].get(table, []), 'keyed': bool(meta.get('keyed')),
               'settingCols': setting_cols, 'save': url_for('api_save_table', table=table),
               'links': 'See the effect on the <a href="/">Cockpit</a> or in any module.'}
    issues = [c for c in R['checks']['items'] if c['table'] == table]
    d = views.page('data', [], extra={'template': 'data_table.html', 'title': meta['title'], 'summary': meta['about']})
    return render_page('data', d, R, ws, table=table, meta=meta, payload=safe_json(payload),
                       issues=issues, edited=edited_tables(ws))


def _mark_edited(ws, table, edited=True):
    e = set(ws.get('edited', []))
    (e.add if edited else e.discard)(table)
    ws['edited'] = sorted(e)


@app.post('/api/data/<table>')
def api_save_table(table):
    if table not in W.TABLES:
        abort(404)
    wsid, ws = ws_get()
    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows')
    if not isinstance(rows, list):
        return jsonify({'ok': False, 'errors': [[0, '', 'No rows received.']]}), 400
    clean, errors = W.validate_rows(table, rows)
    if errors:
        return jsonify({'ok': False, 'errors': errors[:200], 'count': len(errors)})
    ws['tables'][table] = clean
    _mark_edited(ws, table)
    W.save(wsid, ws)
    app.logger.info('PILOT edit tester=%s table=%s rows=%d', session.get('tester', '-'), table, len(clean))
    return jsonify({'ok': True, 'rows': len(clean)})


@app.post('/data/<table>/reset')
def data_reset(table):
    if table not in W.TABLES:
        abort(404)
    wsid, ws = ws_get()
    ws['tables'][table] = W.demo_workspace()['tables'][table]
    _mark_edited(ws, table, False)
    W.save(wsid, ws)
    return redirect(url_for('data_table', table=table, msg='Table reset to the demo data.'))


@app.get('/data/<table>.csv')
def data_csv(table):
    if table not in W.TABLES:
        abort(404)
    _, ws = ws_get()
    return Response(W.table_csv(ws, table), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=planyukta_{table}.csv'})


@app.post('/data/<table>/upload')
def data_upload(table):
    if table not in W.TABLES:
        abort(404)
    wsid, ws = ws_get()
    f = request.files.get('file')
    if not f or not f.filename:
        return redirect(url_for('data_table', table=table, err='Choose a CSV or Excel file first.'))
    try:
        book = W.read_upload(f.filename, f.read())
    except Exception as exc:  # noqa: BLE001
        return redirect(url_for('data_table', table=table, err=f'Could not read that file: {exc}'))
    rows = book.get(None) or book.get(table) or next(iter(book.values()), [])
    rows, missing = W.match_columns(table, rows)
    if missing:
        return redirect(url_for('data_table', table=table, err=f'Missing columns: {", ".join(missing)}. Download the CSV to see the headings.'))
    clean, errors = W.validate_rows(table, rows)
    if errors:
        e = '; '.join(f'row {i + 2} {c}: {m}' for i, c, m in errors[:6])
        return redirect(url_for('data_table', table=table, err=f'{len(errors)} problem(s), nothing was changed. {e}'))
    ws['tables'][table] = clean
    _mark_edited(ws, table)
    W.save(wsid, ws)
    return redirect(url_for('data_table', table=table, msg=f'Loaded {len(clean):,} rows from {f.filename}.'))


# ------------------------------------------------------------------ workspace import / export
@app.get('/workspace.xlsx')
def workspace_export():
    _, ws = ws_get()
    return send_file(io.BytesIO(W.export_workbook(ws)), as_attachment=True, download_name='PlanYukta_Workspace.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.post('/workspace/import')
def workspace_import():
    wsid, ws = ws_get()
    f = request.files.get('file')
    if not f or not f.filename.lower().endswith(('.xlsx', '.xlsm')):
        return redirect(url_for('module_page', key='io', err='Upload the workspace .xlsx (download it from this page first).'))
    try:
        book = W.read_upload(f.filename, f.read())
    except Exception as exc:  # noqa: BLE001
        return redirect(url_for('module_page', key='io', err=f'Could not read that workbook: {exc}'))
    loaded, problems = [], []
    new_tables = dict(ws['tables'])
    for name in W.TABLES:
        sheet = book.get(name) or book.get(name[:31])
        if sheet is None:
            continue
        rows, missing = W.match_columns(name, sheet)
        if missing:
            problems.append(f'{name}: missing columns {", ".join(missing)}')
            continue
        clean, errors = W.validate_rows(name, rows)
        if errors:
            i, c, m = errors[0]
            problems.append(f'{name}: {len(errors)} problem(s), first at row {i + 2} {c}: {m}')
            continue
        new_tables[name] = clean
        loaded.append(name)
    if problems:
        return redirect(url_for('module_page', key='io', err='Nothing was changed. ' + ' | '.join(problems[:6])))
    ws['tables'] = new_tables
    ws['edited'] = sorted(set(ws.get('edited', [])) | set(loaded))
    ws['source'] = f.filename
    W.save(wsid, ws)
    app.logger.info('PILOT import tester=%s sheets=%d', session.get('tester', '-'), len(loaded))
    return redirect(url_for('module_page', key='io', msg=f'Loaded {len(loaded)} tables from {f.filename}.'))


@app.post('/workspace/reset')
def workspace_reset():
    wsid, ws = ws_get()
    fresh = W.demo_workspace()
    fresh['version'] = ws.get('version', 0)
    W.save(wsid, fresh)
    nxt = request.form.get('next') or '/'
    if not nxt.startswith('/') or nxt.startswith('//'):
        nxt = '/'
    return redirect(nxt.split('?')[0] + '?msg=Every+table+is+back+to+the+demo+data.')


# ------------------------------------------------------------------ actions
@app.post('/osat-wip/hold')
def osat_hold():
    wsid, ws = ws_get()
    vendor, lot, action = request.form.get('vendor'), request.form.get('lot'), request.form.get('action')
    for r in ws['tables']['osat_wip']:
        if r['Vendor'] == vendor and r['LotID'] == lot:
            if action == 'release' and r['State'] == 'HOLD':
                r['State'] = 'WAIT'
                r['HoldReason'] = None
            elif action == 'hold':
                r['State'] = 'HOLD'
                r['HoldReason'] = (request.form.get('reason') or 'Held from the OSAT WIP page')[:120]
            break
    _mark_edited(ws, 'osat_wip')
    W.save(wsid, ws)
    return redirect(url_for('module_page', key='osat-wip', msg=f'Lot {lot} {"released" if action == "release" else "put on hold"}.') + '#holds')


def atp_context(R, ws):
    p = R['plan']
    T = R['atp']['table']
    skus = sorted({k[0] for k in T})
    summary = []
    for (sku, v, b), d in sorted(T.items()):
        summary.append({'sku': sku, 'vendor': v, 'bin': b, 'onhand': d['onhand'], 'atp': d['atp'][:p.H],
                        'reserved': sum(d['reserved'][:p.H])})
    lines = session.pop('atp_lines', None)
    result = None
    if lines:
        result = cockpit.atp_check(p, R['atp'], lines)
    res = [r for r in ws['tables']['reservations']]
    return {'skus': skus, 'bins': sorted({k[2] for k in T}), 'customers': sorted({r['Customer'] for r in ws['tables']['customer_bins']}),
            'atp_summary': summary, 'atp_result': result, 'reservations': res, 'months': p.months,
            'default_crd': f'{p.months[0]}-20'}


def _atp_lines(form):
    lines = []
    for i in range(1, 6):
        sku = form.get(f'sku{i}')
        qty = form.get(f'qty{i}', '').replace(',', '').strip()
        if not sku or not qty:
            continue
        try:
            q = float(qty)
            crd = W.norm_date(form.get(f'crd{i}'))
        except ValueError:
            continue
        if q <= 0 or not crd:
            continue
        lines.append({'sku': sku, 'customer': (form.get(f'customer{i}') or 'Customer Alpha')[:60], 'bin': form.get(f'bin{i}') or 'BIN_1',
                      'qty': q, 'crd': crd, 'po': (form.get(f'po{i}') or '')[:40]})
    return lines


@app.post('/atp/check')
def atp_check():
    lines = _atp_lines(request.form)
    if not lines:
        return redirect(url_for('module_page', key='atp', err='Enter at least one order line with a product, quantity and requested date.'))
    if request.form.get('do') == 'reserve':
        wsid, ws = ws_get()
        R = results(wsid, ws)
        out = cockpit.atp_check(R['plan'], R['atp'], lines)
        res = ws['tables']['reservations']
        n = 1 + max([int(r['SalesOrder'].split('-')[-1]) for r in res if r['SalesOrder'].split('-')[-1].isdigit()] + [1000])
        made = 0
        for o in out:
            for a in o['allocations']:
                res.append({'SalesOrder': f'RS-{n}', 'Customer': o['line']['customer'], 'CustomerPO': o['line'].get('po') or None,
                            'SKU': o['line']['sku'], 'Vendor': a['vendor'], 'Bin': o['line']['bin'], 'Qty': int(a['qty']),
                            'CRD': o['line']['crd'], 'SSD': a['ssd'], 'Status': 'Reserved'})
                n += 1
                made += 1
        _mark_edited(ws, 'reservations')
        W.save(wsid, ws)
        app.logger.info('PILOT reserve tester=%s lines=%d', session.get('tester', '-'), made)
        return redirect(url_for('module_page', key='atp', msg=f'{made} reservation line(s) created.') + '#reservations')
    session['atp_lines'] = lines
    return redirect(url_for('module_page', key='atp') + '#result')


@app.post('/atp/cancel')
def atp_cancel():
    wsid, ws = ws_get()
    so = request.form.get('so')
    for r in ws['tables']['reservations']:
        if r['SalesOrder'] == so and r['Status'] == 'Reserved':
            r['Status'] = 'Cancelled'
    _mark_edited(ws, 'reservations')
    W.save(wsid, ws)
    return redirect(url_for('module_page', key='atp', msg=f'{so} cancelled.') + '#reservations')


@app.post('/snapshots/save')
def snapshot_save():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    name = (request.form.get('name') or '').strip()[:60] or f'Snapshot {len(ws.get("snapshots", [])) + 1}'
    snaps = ws.setdefault('snapshots', [])
    sid = secrets.token_hex(4)
    snaps.append({'id': sid, 'name': name, 'created': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
                  'edited': edited_tables(ws), 'data': cockpit.plan_snapshot_data(R)})
    ws['snapshots'] = snaps[-8:]
    W.save(wsid, ws)
    return redirect(url_for('module_page', key='snapshots', snap=sid, msg=f'Saved "{name}". Change some data, then come back to compare.'))


@app.post('/snapshots/delete')
def snapshot_delete():
    wsid, ws = ws_get()
    ws['snapshots'] = [s for s in ws.get('snapshots', []) if s['id'] != request.form.get('id')]
    W.save(wsid, ws)
    return redirect(url_for('module_page', key='snapshots'))


@app.post('/pullin/save')
def pullin_save():
    wsid, ws = ws_get()
    rows = ws['tables']['products']
    for r in rows:
        s = r['SKU']
        if f'pull_{s}' in request.form or f'sl_{s}' in request.form:
            r['PullIn'] = 'Y' if request.form.get(f'pull_{s}') == 'Y' else 'N'
            for fld, key in (('ServiceLevelPct', 'sl'), ('MaxPullInPct', 'max'), ('Priority', 'prio'), ('SafetyStockWeeks', 'ss'),
                             ('PullInWeight', 'w')):
                v = request.form.get(f'{key}_{s}')
                if v not in (None, ''):
                    r[fld] = v
    clean, errors = W.validate_rows('products', rows)
    if errors:
        i, c, m = errors[0]
        return redirect(url_for('module_page', key='pullin', err=f'{rows[i]["SKU"]} {c}: {m}. Nothing was saved.'))
    ws['tables']['products'] = clean
    h = request.form.get('horizon')
    if h not in (None, ''):
        st, err = W.validate_rows('settings', [dict(r, Value=(h if r['Setting'] == 'Pull-in horizon months' else r['Value']))
                                               for r in ws['tables']['settings']])
        if err:
            return redirect(url_for('module_page', key='pullin', err='Pull-in horizon must be a whole number from 0 to 12.'))
        ws['tables']['settings'] = st
        _mark_edited(ws, 'settings')
    _mark_edited(ws, 'products')
    W.save(wsid, ws)
    return redirect(url_for('module_page', key='pullin', msg='Pull-in settings saved; the plan has been recalculated.'))


def _pullin_variant(ws, f):
    """Copy of the workspace with one product's pull-in settings (and the non-consignee switch) changed."""
    import copy
    sku = f.get('sku')
    new = {'tables': dict(ws['tables'])}
    prods = copy.deepcopy(ws['tables']['products'])
    hit = False
    for r in prods:
        if r['SKU'] == sku:
            hit = True
            for fld, key in (('PullInWeight', 'weight'), ('ServiceLevelPct', 'sl'), ('MaxPullInPct', 'max'),
                             ('PullIn', 'pull'), ('BuildStrategy', 'build')):
                if f.get(key) not in (None, ''):
                    r[fld] = f.get(key)
    clean, errors = W.validate_rows('products', prods)
    if not hit or errors:
        return None, (errors[0][2] if errors else 'Unknown product')
    new['tables']['products'] = clean
    if f.get('nc') in ('Y', 'N'):
        st = [dict(r, Value=(f['nc'] if r['Setting'] == 'Allow non-consignee testers' else r['Value'])) for r in ws['tables']['settings']]
        new['tables']['settings'], _ = W.validate_rows('settings', st)
    return new, None


@app.post('/api/pullin/preview')
def pullin_preview():
    wsid, ws = ws_get()
    f = request.get_json(silent=True) or {}
    variant, err = _pullin_variant(ws, f)
    if err:
        return jsonify({'error': err}), 400
    R = results(wsid, ws)
    Rn = cockpit.compute(variant)
    return jsonify({'html': views.pullin_preview_html(R, Rn, f.get('sku'))})


@app.post('/pullin/save-one')
def pullin_save_one():
    wsid, ws = ws_get()
    variant, err = _pullin_variant(ws, request.form)
    if err:
        return redirect(url_for('module_page', key='pullin', err=err))
    ws['tables']['products'] = variant['tables']['products']
    ws['tables']['settings'] = variant['tables']['settings']
    _mark_edited(ws, 'products')
    _mark_edited(ws, 'settings')
    W.save(wsid, ws)
    sku = request.form.get('sku')
    return redirect(url_for('module_page', key='pullin', sku_sel=sku, msg=f'Pull-in strategy for {sku} saved; every module has been re-planned.'))


@app.post('/sku-setup/create')
def sku_create():
    wsid, ws = ws_get()
    t = ws['tables']
    f = request.form
    new = (f.get('sku') or '').strip().upper()
    src = f.get('clone')
    err = None
    if not new or not new.replace('_', '').replace('-', '').isalnum() or len(new) > 20:
        err = 'Give the new product a short name: letters, numbers, - or _ (up to 20).'
    elif any(r['SKU'].upper() == new for r in t['products']):
        err = f'{new} already exists.'
    elif not any(r['SKU'] == src for r in t['products']):
        err = 'Choose a product to clone.'
    if err:
        return redirect(url_for('module_page', key='sku-setup', err=err))
    base = next(r for r in t['products'] if r['SKU'] == src)
    prod = dict(base, SKU=new, Description=(f.get('desc') or f'Cloned from {src}')[:80], Status=f.get('status') or 'NPI')
    for fld in ('GDPW', 'WaferPriceUSD', 'Package'):
        if f.get(fld):
            prod[fld] = f.get(fld)
    if prod['Status'] == 'NPI':
        prod['NPIStartDate'] = f.get('npi_start') or base.get('NPIStartDate') or str(cockpit.Plan(ws).as_of)
    vendors = f.getlist('vendors') or sorted({r['Vendor'] for r in t['tester_capacity'] if r['SKU'] == src})
    yield_adj = 0.0
    try:
        yield_adj = float(f.get('yield_adj') or 0) / 100
    except ValueError:
        pass
    added = {'products': 1}
    t['products'].append(prod)
    for name, key in (('process_flow', 'SKU'), ('bin_splits', 'SKU'), ('pricing', 'SKU'), ('npi_milestones', 'SKU')):
        rows = [dict(r, **{key: new}) for r in t[name] if r[key] == src]
        if name == 'process_flow' and yield_adj:
            for r in rows:
                r['Yield'] = max(0.05, min(1.0, float(r['Yield']) + yield_adj))
        t[name].extend(rows)
        added[name] = len(rows)
    caps = [dict(r, SKU=new) for r in t['tester_capacity'] if r['SKU'] == src and r['Vendor'] in vendors]
    if not caps and vendors:   # vendor not qualified on the source: copy the source's first vendor times to each chosen vendor
        first = [r for r in t['tester_capacity'] if r['SKU'] == src]
        v0 = first[0]['Vendor'] if first else None
        caps = [dict(r, SKU=new, Vendor=v) for v in vendors for r in first if r['Vendor'] == v0]
    t['tester_capacity'].extend(caps)
    added['tester_capacity'] = len(caps)
    costs = [dict(r, SKU=new) for r in t['osat_costs'] if r['SKU'] == src]
    t['osat_costs'].extend(costs)
    added['osat_costs'] = len(costs)
    fc = 0
    try:
        start_m = W.norm_month(f.get('fc_start'))
        qty = [float(x.replace(',', '')) for x in (f.get('fc_qty') or '').replace(';', ' ').split() if x.strip()]
    except ValueError:
        start_m, qty = None, []
    if start_m and qty:
        for i, q in enumerate(qty[:18]):
            t['forecast'].append({'Month': cockpit.month_add(start_m, i), 'SKU': new, 'Units': int(q)})
            fc += 1
    added['forecast'] = fc
    for name in added:
        clean, errors = W.validate_rows(name, t[name])
        if errors:
            i, c, m = errors[0]
            return redirect(url_for('module_page', key='sku-setup', err=f'{name} row {i + 1} {c}: {m}. Nothing was saved.'))
        t[name] = clean
        _mark_edited(ws, name)
    W.save(wsid, ws)
    summary = ', '.join(f'{W.TABLES[k]["title"]} +{v}' for k, v in added.items() if v)
    return redirect(url_for('module_page', key='sku-setup', msg=f'{new} created. {summary}.', new=new))


# ------------------------------------------------------------------ overrides
@app.post('/overrides/add/<table>')
def override_add(table):
    if table not in views.OVERRIDE_TABLES:
        abort(404)
    wsid, ws = ws_get()
    cols = [c['name'] for c in W.TABLES[table]['columns']]
    row = {c: (request.form.get(c) or '').strip() or None for c in cols}
    if table == 'capacity_overrides' and not any(row.get(k) for k in ('TestTimeSec', 'Sites', 'IndexTimeSec', 'OEE')):
        return redirect(url_for('module_page', key='overrides', err='Fill at least one of test time, sites, index time or OEE.') + '#add-testtime')
    def _num(v):
        try:
            return float(v or 0)
        except ValueError:
            return 1.0      # let validation report the bad value
    if table == 'fleet_changes' and not (_num(row.get('ConsigneeChange')) or _num(row.get('NonConsigneeChange'))):
        return redirect(url_for('module_page', key='overrides', err='Enter a number of testers to add or remove.') + '#add-tester')
    if table == 'fleet_changes':
        row['ConsigneeChange'] = row.get('ConsigneeChange') or 0
        row['NonConsigneeChange'] = row.get('NonConsigneeChange') or 0
    keycols = W.TABLES[table]['key']
    rows = [r for r in ws['tables'].get(table, []) if [str(r.get(k)).upper() for k in keycols] != [str(row.get(k)).upper() for k in keycols]]
    replaced = len(rows) != len(ws['tables'].get(table, []))
    clean, errors = W.validate_rows(table, rows + [row])
    anchor = {'fleet_changes': '#add-tester', 'hardware_arrivals': '#add-hardware', 'capacity_overrides': '#add-testtime',
              'yield_overrides': '#add-yield'}[table]
    if errors:
        i, c, m = errors[0]
        return redirect(url_for('module_page', key='overrides', err=f'{c}: {m}. Nothing was added.') + anchor)
    ws['tables'][table] = clean
    _mark_edited(ws, table)
    W.save(wsid, ws)
    app.logger.info('PILOT override tester=%s table=%s', session.get('tester', '-'), table)
    msg = ('Override updated (same month and resource as an existing one).' if replaced else 'Override added.') + ' The plan has been recalculated.'
    return redirect(url_for('module_page', key='overrides', msg=msg, res=f'{row.get("Vendor")}|{row.get("Step") or row.get("Operation")}') + '#timeline')


@app.post('/overrides/delete')
def override_delete():
    table = request.form.get('table')
    if table not in views.OVERRIDE_TABLES:
        abort(404)
    wsid, ws = ws_get()
    rows = ws['tables'].get(table, [])
    try:
        i = int(request.form.get('i', -1))
        sig = json.loads(request.form.get('sig') or '{}')
    except ValueError:
        i, sig = -1, {}
    if 0 <= i < len(rows) and all(str(rows[i].get(k)) == str(v) for k, v in sig.items()):
        rows.pop(i)
        _mark_edited(ws, table)
        W.save(wsid, ws)
        return redirect(url_for('module_page', key='overrides', msg='Override deleted. The plan has been recalculated.'))
    return redirect(url_for('module_page', key='overrides', err='That override has already changed; reload and try again.'))


@app.post('/overrides/switch')
def override_switch():
    wsid, ws = ws_get()
    change = {}
    if request.form.get('apply') in ('Y', 'N'):
        change['Apply overrides'] = request.form['apply']
    if request.form.get('hw') in ('Y', 'N'):
        change['Limit testers to hardware-ready'] = request.form['hw']
    rows = [dict(r, Value=change.get(r['Setting'], r['Value'])) for r in ws['tables']['settings']]
    clean, errors = W.validate_rows('settings', rows)
    if not errors:
        ws['tables']['settings'] = clean
        _mark_edited(ws, 'settings')
        W.save(wsid, ws)
    return redirect(url_for('module_page', key='overrides', msg='Setting changed; every module has been re-planned.'))


# ------------------------------------------------------------------ vendor QBR, post-silicon
def _redirect_back(key, anchor='', **kw):
    return redirect(url_for('module_page', key=key, **kw) + anchor)


@app.post('/qbr/issue/add')
def qbr_issue_add():
    wsid, ws = ws_get()
    rows = list(ws['tables'].get('vendor_issues', []))
    nums = [int(r['IssueID'][3:]) for r in rows if str(r.get('IssueID', '')).startswith('VI-') and r['IssueID'][3:].isdigit()]
    f = request.form
    row = {'IssueID': f'VI-{(max(nums) + 1) if nums else 1:04d}', 'Vendor': (f.get('Vendor') or '').strip(), 'Opened': f.get('Opened') or None,
           'Category': f.get('Category'), 'Severity': f.get('Severity'), 'Title': (f.get('Title') or '').strip()[:160],
           'SKU': (f.get('SKU') or '').strip() or None, 'Owner': (f.get('Owner') or '').strip()[:60] or None, 'Due': f.get('Due') or None,
           'Status': 'Open', 'Closed': None, 'RootCause': None, 'Action': (f.get('Action') or '').strip()[:200] or None}
    clean, errors = W.validate_rows('vendor_issues', rows + [row])
    if errors:
        i, c, m = errors[0]
        return _redirect_back('vendor-qbr', '#issues', err=f'{c}: {m}. The issue was not added.')
    ws['tables']['vendor_issues'] = clean
    _mark_edited(ws, 'vendor_issues')
    W.save(wsid, ws)
    return _redirect_back('vendor-qbr', '#issues', msg=f'Issue {row["IssueID"]} logged; the scorecard has been updated.')


@app.post('/qbr/issue/close')
def qbr_issue_close():
    wsid, ws = ws_get()
    rows = ws['tables'].get('vendor_issues', [])
    iid = request.form.get('id')
    hit = next((r for r in rows if r['IssueID'] == iid), None)
    if not hit:
        return _redirect_back('vendor-qbr', '#issues', err='That issue is no longer in the log.')
    as_of = W.settings_dict(ws).get('As-of date')
    hit.update(Status='Closed', Closed=str(as_of)[:10] if as_of else datetime.utcnow().strftime('%Y-%m-%d'))
    if (request.form.get('root') or '').strip():
        hit['RootCause'] = request.form['root'].strip()[:160]
    clean, errors = W.validate_rows('vendor_issues', rows)
    if errors:
        return _redirect_back('vendor-qbr', '#issues', err=f'{errors[0][1]}: {errors[0][2]}.')
    ws['tables']['vendor_issues'] = clean
    _mark_edited(ws, 'vendor_issues')
    W.save(wsid, ws)
    return _redirect_back('vendor-qbr', '#issues', msg=f'{iid} closed on the as-of date.')


@app.post('/postsilicon/use-yield')
def postsilicon_use_yield():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    f = request.form
    sku, vendor, step = f.get('sku'), f.get('vendor'), f.get('step')
    try:
        y = round(float(f.get('yield')), 4)
    except (TypeError, ValueError):
        abort(400)
    start = R['plan'].start
    rows = [r for r in ws['tables'].get('yield_overrides', [])
            if not (r['SKU'] == sku and r['Vendor'] == vendor and r['Operation'] == step and r['EffectiveMonth'] == start)]
    row = {'SKU': sku, 'Vendor': vendor, 'Operation': step, 'EffectiveMonth': start, 'Yield': y, 'ReworkRate': None,
           'Reason': 'Post-Silicon: last-5-lot mean'}
    cols = [c['name'] for c in W.TABLES['yield_overrides']['columns']]
    row = {k: row.get(k) for k in cols}
    clean, errors = W.validate_rows('yield_overrides', rows + [row])
    if errors:
        return _redirect_back('postsilicon', err=f'{errors[0][1]}: {errors[0][2]}.', sku=sku, step=step)
    ws['tables']['yield_overrides'] = clean
    _mark_edited(ws, 'yield_overrides')
    W.save(wsid, ws)
    return _redirect_back('postsilicon', sku=sku, step=step,
                          msg=f'{sku} {step} at OSAT-{vendor} now plans at {y * 100:.1f}% from {views.mlabel(start)} (Yield override added). '
                              f'Starts, tester load and wafer starts have been re-planned.')


@app.post('/postsilicon/use-bins')
def postsilicon_use_bins():
    from plan_yukta import insights
    wsid, ws = ws_get()
    R = results(wsid, ws)
    sku, step = request.form.get('sku'), request.form.get('step') or 'Test1'
    P = insights.postsilicon_view(R['plan'], sku, step)
    act = [(b['bin'], b['actual']) for b in P['bin_split'] if b['actual']]
    tot = sum(a for _, a in act)
    if P['sku'] != sku or not tot:
        return _redirect_back('postsilicon', err='No pass-bin data for that product.', sku=sku, step=step)
    fr = [(b, round(a / tot, 4)) for b, a in act]
    fr[-1] = (fr[-1][0], round(1 - sum(x for _, x in fr[:-1]), 4))
    rows = [r for r in ws['tables']['bin_splits'] if r['SKU'] != sku] + [{'SKU': sku, 'Bin': b, 'Fraction': x} for b, x in fr]
    clean, errors = W.validate_rows('bin_splits', rows)
    if errors:
        return _redirect_back('postsilicon', err=f'{errors[0][1]}: {errors[0][2]}.', sku=sku, step=step)
    ws['tables']['bin_splits'] = clean
    _mark_edited(ws, 'bin_splits')
    W.save(wsid, ws)
    return _redirect_back('postsilicon', sku=sku, step=step, msg=f'{sku} bin splits updated from actual test bins: ' +
                          ', '.join(f'{b} {x * 100:.1f}%' for b, x in fr) + '.')


def api_token(wsid):
    return f'{wsid}.' + hmac.new(app.config['SECRET_KEY'].encode(), f'test-data:{wsid}'.encode(), 'sha256').hexdigest()[:32]


def _token_ws():
    auth = request.headers.get('Authorization', '')
    tok = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    wsid, _, sig = tok.partition('.')
    if not wsid or not sig or not hmac.compare_digest(api_token(wsid), tok):
        return None, None
    ws = W.load(wsid)
    return (wsid, ws) if ws else (None, None)


API_MAX_ROWS = 5000


@app.route('/api/v1/test-results', methods=['GET', 'POST'])
def api_test_results():
    wsid, ws = _token_ws()
    if not ws:
        return jsonify({'error': 'Missing or invalid token. Copy it from Post-Silicon Analysis.'}), 401
    if request.method == 'GET':
        return jsonify({'test_results': len(ws['tables'].get('test_results', [])), 'test_bins': len(ws['tables'].get('test_bins', []))})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Send a JSON object: {"results": [...], "bins": [...]}'}), 400
    out = {'results_added': 0, 'bins_added': 0, 'errors': []}
    for name, table in (('results', 'test_results'), ('bins', 'test_bins')):
        new = body.get(name) or []
        if not isinstance(new, list) or len(new) > API_MAX_ROWS or not all(isinstance(r, dict) for r in new):
            return jsonify({'error': f'"{name}" must be a list of up to {API_MAX_ROWS} objects.'}), 400
        if not new:
            continue
        cols = [c['name'] for c in W.TABLES[table]['columns']]
        new = [{c: r.get(c) for c in cols} for r in new]
        key = W.TABLES[table]['key']
        sig = lambda r: tuple(str(r.get(k)).upper() for k in key)
        incoming = {sig(r) for r in new}
        rows = [r for r in ws['tables'].get(table, []) if sig(r) not in incoming] + new
        clean, errors = W.validate_rows(table, rows)
        if errors:
            off = len(rows) - len(new)
            out['errors'] += [{'list': name, 'row': i - off + 1, 'column': c, 'error': m} for i, c, m in errors[:20]]
            continue
        ws['tables'][table] = clean
        _mark_edited(ws, table)
        out[f'{name}_added'] = len(new)
    if out['results_added'] or out['bins_added']:
        W.save(wsid, ws)
    app.logger.info('PILOT test-data API results=%s bins=%s errors=%s', out['results_added'], out['bins_added'], len(out['errors']))
    return jsonify(out), (200 if not out['errors'] else 422)


# ------------------------------------------------------------------ portfolio & roadmaps
def _pf_back(key, **kw):
    return redirect(url_for('module_page', key=key, **kw))


@app.post('/pf/scenario/save')
def pf_scenario_save():
    from plan_yukta import portfolio as PFm
    wsid, ws = ws_get()
    name = (request.form.get('name') or '').strip()[:60]
    if not name:
        return _pf_back('pf-scenarios', err='Give the scenario a name.')
    _, changes = pf_views._scenario_arg(ws, request.form)
    if not changes:
        return _pf_back('pf-scenarios', err='Nothing to save: build a what-if first.')
    rows = [r for r in ws['tables'].get('pf_scenarios', []) if r['Scenario'] != name]
    cols = [c['name'] for c in W.TABLES['pf_scenarios']['columns']]
    for i, c in enumerate(sorted(changes, key=lambda c: c.get('Seq') or 0), start=1):
        rows.append({k: ({'Scenario': name, 'Seq': i}.get(k, c.get(k))) for k in cols})
    clean, errors = W.validate_rows('pf_scenarios', rows)
    if errors:
        return _pf_back('pf-scenarios', err=f'{errors[0][1]}: {errors[0][2]}.')
    ws['tables']['pf_scenarios'] = clean
    _mark_edited(ws, 'pf_scenarios')
    W.save(wsid, ws)
    return _pf_back('pf-scenarios', scenario=name, msg=f'Scenario "{name}" saved with {len(changes)} change(s).')


@app.post('/pf/gate/decide')
def pf_gate_decide():
    wsid, ws = ws_get()
    f = request.form
    pid, gate, dec = f.get('pid'), f.get('gate'), f.get('decision')
    g = next((r for r in ws['tables'].get('pf_gates', []) if r['ProjectID'] == pid and r['Gate'] == gate), None)
    if not g or dec not in ('Approve', 'Approve with conditions', 'Defer', 'Re-scope', 'Stop'):
        return _pf_back('pf-board', err='That gate is no longer in the table.')
    as_of = str(W.settings_dict(ws).get('As-of date'))[:10]
    g['Status'] = {'Approve': 'Passed', 'Approve with conditions': 'Conditional', 'Defer': 'Deferred', 'Re-scope': 'Deferred', 'Stop': 'Failed'}[dec]
    g['Decided'] = as_of
    decs = ws['tables'].get('pf_decisions', [])
    nums = [int(d['DecisionID'][2:]) for d in decs if str(d.get('DecisionID', '')).startswith('D-') and d['DecisionID'][2:].isdigit()]
    summary = (f.get('summary') or '').strip()[:200] or f'{gate}: {dec.lower()}.'
    decs.append({'DecisionID': f'D-{(max(nums) + 1) if nums else 101}', 'Date': as_of, 'Forum': 'Portfolio Board', 'ProjectID': pid, 'Gate': gate,
                 'Decision': dec, 'Summary': summary, 'Owner': None, 'ActionDue': None})
    if dec == 'Stop':
        for p in ws['tables'].get('pf_projects', []):
            if p['ProjectID'] == pid:
                p['Funding'], p['Stage'] = 'Stopped', 'Stopped'
    elif dec in ('Approve', 'Approve with conditions') and gate in ('G1 Plan approval', 'G2 Development commit'):
        for p in ws['tables'].get('pf_projects', []):
            if p['ProjectID'] == pid:
                p['Funding'] = 'Committed'
                p['Stage'] = {'G1 Plan approval': 'Plan', 'G2 Development commit': 'Develop'}[gate] if p['Stage'] in ('Idea', 'Concept', 'Plan') else p['Stage']
    for t in ('pf_gates', 'pf_decisions', 'pf_projects'):
        clean, errors = W.validate_rows(t, ws['tables'][t])
        if errors:
            return _pf_back('pf-board', err=f'{errors[0][1]}: {errors[0][2]}.')
        ws['tables'][t] = clean
        _mark_edited(ws, t)
    W.save(wsid, ws)
    return _pf_back('pf-board', msg=f'Recorded: {dec} for {pid} {gate}. Gate status, decision log and funding updated.')


@app.post('/pf/integrations/save')
def pf_integrations_save():
    wsid, ws = ws_get()
    f = request.form
    cur = dict(ws.get('integrations') or {})
    try:
        cur['site'] = IG.clean_site(f.get('site'))
    except IG.IntegrationError as e:
        return _pf_back('pf-integrations', err=str(e))
    cur['email'] = (f.get('email') or '').strip()[:120]
    if (f.get('token') or '').strip():
        cur['token'] = f['token'].strip()[:300]
    cur['jql'] = (f.get('jql') or '').strip()[:300] or IG.DEFAULT_JQL
    cur['space'] = re.sub(r'[^A-Za-z0-9_~-]', '', f.get('space') or '')[:40]
    ws['integrations'] = cur
    W.save(wsid, ws)
    return _pf_back('pf-integrations', msg='Saved. Press Test connection.')


@app.post('/pf/integrations/clear')
def pf_integrations_clear():
    wsid, ws = ws_get()
    ws.pop('integrations', None)
    W.save(wsid, ws)
    return _pf_back('pf-integrations', msg='Credentials removed from this workspace.')


@app.post('/pf/integrations/test')
def pf_integrations_test():
    wsid, ws = ws_get()
    try:
        return _pf_back('pf-integrations', msg=IG.test(IG.config(ws)))
    except IG.IntegrationError as e:
        return _pf_back('pf-integrations', err=str(e))


@app.post('/pf/jira/sync')
def pf_jira_sync():
    wsid, ws = ws_get()
    keys = {p['JiraKey'] for p in ws['tables'].get('pf_projects', []) if p.get('JiraKey')}
    try:
        rows = IG.jira_sync(IG.config(ws), keys)
    except IG.IntegrationError as e:
        return _pf_back('pf-integrations', err=str(e))
    clean, errors = W.validate_rows('pf_jira', rows)
    if errors:
        return _pf_back('pf-integrations', err=f'Jira data did not validate: {errors[0][1]}: {errors[0][2]}.')
    ws['tables']['pf_jira'] = clean
    _mark_edited(ws, 'pf_jira')
    W.save(wsid, ws)
    app.logger.info('PILOT jira sync epics=%s', len(clean))
    return _pf_back('pf-integrations', msg=f'Synced {len(clean)} epics from Jira.')


@app.post('/pf/confluence/publish')
def pf_confluence_publish():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    cfg = IG.config(ws)
    if not IG.status(cfg)['conf_ready']:
        return _pf_back('pf-integrations', err='Connect your Atlassian site and add a Confluence space key to publish. '
                                               'Meanwhile, download the board pack from Portfolio Board & Gates.')
    pk = IG.board_pack(ws, R)
    try:
        action, link = IG.confluence_publish(cfg, 'Portfolio Board pack (Plan Yukta)', IG.storage_html(pk))
    except IG.IntegrationError as e:
        return _pf_back('pf-integrations', err=str(e))
    return _pf_back('pf-integrations', msg=f'Confluence page {action}: {link}')


# ------------------------------------------------------------------ exports
def _download(data, name, mime):
    return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)


XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@app.get('/export/<name>')
def export(name):
    wsid, ws = ws_get()
    R = results(wsid, ws)
    if name == 'board-pack.xlsx':
        return _download(exports.board_pack_workbook(ws, R), 'PlanYukta_Portfolio_Board_Pack.xlsx', XLSX)
    if name.startswith('qbr-') and name.endswith('.xlsx'):
        v = name[4:-5]
        if v not in R['plan'].vendors:
            abort(404)
        return _download(exports.qbr_workbook(R, v, request.args.get('period') or 'L3'), f'PlanYukta_QBR_OSAT-{v}.xlsx', XLSX)
    if name == 'b2b.xlsx':
        return _download(exports.b2b_workbook(R), f'PlanYukta_B2B_{R["plan"].start}.xlsx', XLSX)
    if name == 'plan.xlsx':
        return _download(exports.plan_workbook(R), f'PlanYukta_Plan_{R["plan"].start}.xlsx', XLSX)
    if name == 'fab-forecast.xml':
        return _download(exports.fab_forecast_xml(R), 'PlanYukta_FAB_Forecast.xml', 'application/xml')
    if name == 'fab-po.xml':
        return _download(exports.fab_po_xml(R), 'PlanYukta_FAB_PO.xml', 'application/xml')
    if name == 'osat-forecast.xml':
        return _download(exports.osat_forecast_xml(R), 'PlanYukta_OSAT_Forecast.xml', 'application/xml')
    abort(404)


# ------------------------------------------------------------------ chat
@app.post('/api/chat')
def chat():
    payload = request.get_json(silent=True) or {}
    now = time.time()
    recent = [t for t in session.get('chat_times', []) if now - t < 3600]
    if len(recent) >= CHAT_LIMIT:
        return jsonify({'answer': f'You have reached {CHAT_LIMIT} questions this hour. Please try again later.', 'mode': 'limit'})
    session['chat_times'] = recent + [now]
    result = assistant.ask(payload.get('question', ''), payload.get('context', ''), payload.get('history') or [])
    app.logger.info('PILOT chat tester=%s mode=%s', session.get('tester', '-'), result['mode'])
    return jsonify(result)


# ------------------------------------------------------------------ lot-level WIP audit (upload)
from plan_yukta.engine import OSAT_OPERATIONS, STAGE_SEQUENCE, TemplateError, read_workbook, run_plan  # noqa: E402
from plan_yukta import format_spec  # noqa: E402
import audit_view  # noqa: E402


@app.get('/audit')
def audit_index():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    return render_template('audit_index.html', page=views.page('audit', []), key='audit', R=R, ws=ws, badges=nav_badges(R),
                           chat_context=None, args=request.args, next_key=None, error=request.args.get('err'))


@app.get('/audit/format')
def upload_format():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    return render_template('format.html', page=views.page('audit', []), key='audit', R=R, ws=ws, badges=nav_badges(R),
                           chat_context=None, args=request.args, next_key=None, sheets=[dict(sh, columns=[c for c in sh['columns'] if c[1] == 'Yes' or sh['sheet'] != 'Settings']) for sh in format_spec.SHEETS[:6]],
                           rules=[r for r in format_spec.RULES if 'Planning' not in r])


@app.get('/download/<name>')
def download(name):
    allowed = {'template': TEMPLATE.name, 'sample': SAMPLE.name}
    if name not in allowed:
        abort(404)
    return send_from_directory(STATIC, allowed[name], as_attachment=True)


@app.post('/audit/run')
def audit_run():
    wsid, ws = ws_get()
    R = results(wsid, ws)
    use_sample = request.form.get('sample') == '1'
    try:
        if use_sample:
            data, name = read_workbook(SAMPLE), 'Synthetic sample workbook'
            audit_view.apply_playground(data['settings'], request.form)
        else:
            f = request.files.get('workbook')
            if not f or not f.filename:
                return redirect(url_for('audit_index', err='Choose a workbook to upload first.'))
            if not f.filename.lower().endswith(('.xlsx', '.xlsm')):
                return redirect(url_for('audit_index', err='Upload an .xlsx file made from the audit template.'))
            data, name = read_workbook(io.BytesIO(f.read())), f.filename
        res = run_plan(data)
        app.logger.info('PILOT audit tester=%s source=%s', session.get('tester', '-'), 'sample' if use_sample else 'upload')
    except TemplateError as exc:
        return redirect(url_for('audit_index', err=str(exc)))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception('Audit run failed')
        return redirect(url_for('audit_index', err=f'The audit could not be run: {exc}'))
    ctx = audit_view.results_context(res, name, use_sample)
    return render_template('results.html', page=views.page('audit', []), key='audit', R=R, ws=ws, badges=nav_badges(R),
                           chat_context=None, args=request.args, next_key=None, **ctx)


# ------------------------------------------------------------------ misc
@app.errorhandler(413)
def too_large(_):
    mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return f'That file is over the {mb} MB pilot limit. Go back and choose a smaller file.', 413


@app.errorhandler(404)
def not_found(_):
    return redirect(url_for('home')) if request.method == 'GET' and not request.path.startswith(('/api/', '/static/')) else ('Not found', 404)


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


# old links from the first pilot
@app.get('/guide')
def old_guide():
    return redirect(url_for('module_page', key='tour'))


@app.get('/format')
def old_format():
    return redirect(url_for('upload_format'))


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', port=int(os.environ.get('PORT', 5000)))
