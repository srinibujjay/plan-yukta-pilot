"""Jira Cloud and Confluence Cloud connectors for the portfolio pages.

Credentials come from environment variables (site owner) or from the visitor's workspace (form).
Only https://<name>.atlassian.net sites are allowed, so the server cannot be pointed at other hosts.
Jira is read-only: epics and their child-issue counts. Confluence: create or update one page.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import escape

DEFAULT_JQL = 'issuetype = Epic AND statusCategory != Done ORDER BY duedate ASC'
SITE_RE = re.compile(r'^https://[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net$')
TIMEOUT = 15
MAX_CHILDREN = 2000


class IntegrationError(Exception):
    pass


def config(ws):
    c = dict(ws.get('integrations') or {})
    env = {'site': os.environ.get('ATLASSIAN_SITE'), 'email': os.environ.get('ATLASSIAN_EMAIL'),
           'token': os.environ.get('ATLASSIAN_TOKEN'), 'space': os.environ.get('CONFLUENCE_SPACE'), 'jql': os.environ.get('JIRA_EPIC_JQL')}
    if env['site'] and env['token']:
        c.update({k: v for k, v in env.items() if v})
        c['source'] = 'Environment'
    else:
        c['source'] = 'This workspace' if c.get('token') else 'None (demo)'
    return c


def clean_site(s):
    s = (s or '').strip().rstrip('/').lower()
    if s and not s.startswith('https://'):
        s = 'https://' + s.removeprefix('http://')
    if s and not SITE_RE.match(s):
        raise IntegrationError('Use your Atlassian Cloud address, like https://your-company.atlassian.net')
    return s


def status(cfg):
    ok = bool(cfg.get('site') and cfg.get('email') and cfg.get('token'))
    return {'jira_ready': ok, 'conf_ready': ok and bool(cfg.get('space')),
            'jira_note': cfg.get('site') if ok else 'add site, email and API token',
            'conf_note': (f'space {cfg.get("space")}' if cfg.get('space') else 'add a space key') if ok else 'needs the Atlassian connection',
            'source': cfg.get('source', 'None (demo)')}


def _req(cfg, method, path, params=None, body=None):
    site = clean_site(cfg.get('site'))
    if not site or not cfg.get('email') or not cfg.get('token'):
        raise IntegrationError('Connect your Atlassian site first (site, email and API token).')
    url = site + path + ('?' + urllib.parse.urlencode(params, doseq=True) if params else '')
    auth = base64.b64encode(f'{cfg["email"]}:{cfg["token"]}'.encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Basic {auth}', 'Accept': 'application/json', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(rq, timeout=TIMEOUT) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = {401: 'the email or API token was not accepted', 403: 'this account cannot see that project or space',
               404: 'not found (check the site, space key or JQL)', 400: 'Atlassian rejected the request (check the JQL)',
               429: 'Atlassian rate limit: try again in a minute'}.get(e.code, f'HTTP {e.code}')
        try:
            detail = json.loads(e.read() or b'{}')
            extra = '; '.join(detail.get('errorMessages', [])[:2]) or (detail.get('message') or '')
        except (ValueError, AttributeError):
            extra = ''
        raise IntegrationError(f'{method} {path}: {msg}' + (f' ({extra[:160]})' if extra else '')) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise IntegrationError(f'Could not reach {site}: {getattr(e, "reason", e)}') from None


def _search(cfg, jql, fields, limit):
    out, token = [], None
    while len(out) < limit:
        params = {'jql': jql, 'fields': ','.join(fields), 'maxResults': min(100, limit - len(out))}
        if token:
            params['nextPageToken'] = token
        r = _req(cfg, 'GET', '/rest/api/3/search/jql', params)
        out += r.get('issues', [])
        token = r.get('nextPageToken')
        if not token:
            break
    return out


def test(cfg):
    me = _req(cfg, 'GET', '/rest/api/3/myself')
    msg = f'Jira OK: signed in as {me.get("displayName") or me.get("emailAddress") or "user"}.'
    if cfg.get('space'):
        sp = _req(cfg, 'GET', '/wiki/api/v2/spaces', {'keys': cfg['space']})
        msg += f' Confluence OK: space {cfg["space"]} found.' if sp.get('results') else f' Confluence: space {cfg["space"]} not found.'
    return msg


def jira_sync(cfg, keys=None):
    """Return pf_jira rows for the epics matched by the JQL (plus any linked keys)."""
    jql = (cfg.get('jql') or DEFAULT_JQL).strip()
    if keys:
        jql = f'({jql.split(" ORDER BY")[0]}) OR key in ({",".join(sorted(keys))})'
    epics = _search(cfg, jql, ['summary', 'status', 'duedate'], 200)
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    rows = []
    for e in epics:
        f = e.get('fields', {})
        kids = _search(cfg, f'parent = {e["key"]}', ['status'], MAX_CHILDREN)
        cats = [((k.get('fields', {}).get('status') or {}).get('statusCategory') or {}).get('key') for k in kids]
        rows.append({'JiraKey': e['key'], 'Summary': (f.get('summary') or '')[:200], 'Status': (f.get('status') or {}).get('name'),
                     'DueDate': f.get('duedate'), 'Done': cats.count('done'), 'InProgress': cats.count('indeterminate'),
                     'Total': len(cats), 'Synced': now})
    return rows


def confluence_publish(cfg, title, storage_html):
    space = (cfg.get('space') or '').strip()
    if not space:
        raise IntegrationError('Add a Confluence space key first.')
    sp = _req(cfg, 'GET', '/wiki/api/v2/spaces', {'keys': space}).get('results') or []
    if not sp:
        raise IntegrationError(f'Confluence space {space} not found or not visible to this account.')
    sid = sp[0]['id']
    found = _req(cfg, 'GET', '/wiki/api/v2/pages', {'space-id': sid, 'title': title}).get('results') or []
    body = {'representation': 'storage', 'value': storage_html}
    if found:
        pid = found[0]['id']
        cur = _req(cfg, 'GET', f'/wiki/api/v2/pages/{pid}')
        n = int((cur.get('version') or {}).get('number') or 1)
        r = _req(cfg, 'PUT', f'/wiki/api/v2/pages/{pid}', body={'id': pid, 'status': 'current', 'title': title, 'body': body,
                                                                 'version': {'number': n + 1, 'message': 'Updated from Plan Yukta'}})
        action = f'updated (version {n + 1})'
    else:
        r = _req(cfg, 'POST', '/wiki/api/v2/pages', body={'spaceId': sid, 'status': 'current', 'title': title, 'body': body})
        action = 'created'
    link = ((r.get('_links') or {}).get('base') or clean_site(cfg['site']) + '/wiki') + ((r.get('_links') or {}).get('webui') or '')
    return action, link


# ------------------------------------------------------------------ board pack
def board_pack(ws, R=None):
    """Board pack content shared by the Excel export and the Confluence page."""
    from . import portfolio as PF
    from .pf_views import _insights, recommend
    pf = PF.Portfolio(ws)
    k = pf.kpis()
    live = [p for p in pf.projects.values() if p['Funding'] != 'Stopped']
    summary = [re.sub('<[^>]+>', '', x) for x in _insights(pf, R)]
    portfolio = [{'Project': p['Name'], 'BU': p['BU'], 'Category': p['Category'], 'Stage': p['Stage'], 'Funding': p.get('funding_result'),
                  'Release': p['launch_fc'], 'Slip (months)': p['launch_slip'], 'Score': round(p['score'], 1), 'Value $M': float(p['ValueUSDm']),
                  'Cost $M': round(p['cost_usdm'], 1), 'Health': p['health']}
                 for p in sorted(live, key=lambda p: (p['Funding'] != 'Committed', -p['score']))]
    gates = []
    for g in pf.upcoming_gates(120):
        rec, _, why = recommend(pf, g)
        gates.append({'Date': f'{g["eff"]:%Y-%m-%d}', 'Project': g['name'], 'Gate': g['Gate'], 'Readiness %': g.get('Readiness'),
                      'Recommendation': rec, 'Why': why})
    asks = []
    for q, idx in pf.quarters():
        for x in pf.supply:
            need = max(pf.load_committed[x][i] - pf.supply[x][i] * pf.target[x] for i in idx)
            if need > 0.5:
                asks.append({'Quarter': q, 'Pool': x, 'Extra FTE': round(need, 1)})
    names = {pid: p['Name'] for pid, p in pf.projects.items()}
    decisions = [{'Date': str(d['Date']), 'Project': names.get(d['ProjectID'], d['ProjectID']), 'Gate': d.get('Gate'), 'Decision': d['Decision'],
                  'Summary': d['Summary']} for d in sorted(ws['tables'].get('pf_decisions', []), key=lambda d: str(d['Date']), reverse=True)[:12]]
    risks = [{'ID': r['RiskID'], 'Project': names.get(r['ProjectID'], r['ProjectID']), 'Item': r['Title'],
              'PxI': int(r['Probability']) * int(r['Impact']), 'Owner': r.get('Owner'), 'Mitigation': r.get('Mitigation')}
             for r in sorted(ws['tables'].get('pf_risks', []), key=lambda r: -int(r['Probability']) * int(r['Impact'])) if r['Status'] != 'Closed'][:8]
    return {'title': f'Portfolio Board pack — {pf.as_of:%d %b %Y}', 'kpis': k, 'summary': summary, 'portfolio': portfolio,
            'gates': gates, 'asks': asks, 'decisions': decisions, 'risks': risks}


def storage_html(pack):
    def tbl(rows):
        if not rows:
            return '<p><em>None.</em></p>'
        cols = list(rows[0])
        h = ''.join(f'<th>{escape(str(c))}</th>' for c in cols)
        b = ''.join('<tr>' + ''.join(f'<td>{escape("" if r[c] is None else str(r[c]))}</td>' for c in cols) + '</tr>' for r in rows)
        return f'<table><tbody><tr>{h}</tr>{b}</tbody></table>'
    k = pack['kpis']
    return (f'<p><em>Generated by Plan Yukta from the portfolio data. Synthetic demo data unless your own tables are loaded.</em></p>'
            f'<h2>Headlines</h2><ul>' + ''.join(f'<li>{escape(s)}</li>' for s in pack['summary']) + '</ul>'
            f'<p>{k["projects"]} active projects ({k["committed"]} committed, {k["proposed"]} proposed) · committed value ${k["value_committed"]:,.0f}M · '
            f'capacity used next 12 months {k["util12"]:.0f}% · {k["red"]} red, {k["amber"]} amber.</p>'
            f'<h2>Gate decisions requested</h2>{tbl(pack["gates"])}'
            f'<h2>Capacity asks</h2>{tbl(pack["asks"])}'
            f'<h2>Portfolio and funding line</h2>{tbl(pack["portfolio"])}'
            f'<h2>Top risks</h2>{tbl(pack["risks"])}'
            f'<h2>Recent decisions</h2>{tbl(pack["decisions"])}')
