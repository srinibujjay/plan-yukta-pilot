"""
"Ask Plan Yukta" assistant.

With ANTHROPIC_API_KEY set, questions go to Claude with the Plan Yukta guide,
formulas, upload format and (on a results page) a summary of the tester's
current results. Without a key it falls back to searching the same help text,
so the pilot works with no AI cost at all.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import format_spec

HERE = Path(__file__).resolve().parent.parent
API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'

FAQ = [
    ('What Plan Yukta does',
     'Plan Yukta is a planning cockpit for fabless semiconductor supply chains. It plans backwards from customer demand '
     'through finished goods, pack, final test (with tester capacity), assembly, bump, wafer sort and fab wafer starts at '
     'every OSAT, then turns the plan into ATP promises, FAB and OSAT purchase orders, the monthly B2B package, cost and P&L. '
     'Every module reads the same data tables, and the visitor can edit any table on its Data page.'),
    ('Using your own data',
     'Open Data Tables in the sidebar to edit any table in the browser, or upload a CSV / Excel for one table. '
     'Import / Export downloads the whole workspace as one workbook; replace the demo rows with your own data and upload it. '
     'If any row has a problem nothing is changed and the error says which row and column. Reset to demo data undoes everything.'),
    ('How the plan works backwards',
     '1) Demand: the build strategy per product gives plan demand. 2) Finished goods needed = demand + safety stock build - '
     'finished goods on hand. 3) Pack, Test2 and Test1 starts = good units needed / yield, netted against WIP at each step. '
     '4) Test starts are capacity-checked against the tester fleet at each OSAT, with pull-in and catch-up. 5) Assembly die = '
     'test starts the testers can do / assembly yield. 6) Wafers = die / (GDPW x sort yield x bump yield). 7) Fab outs net fab '
     'WIP; the rest become wafer starts, a fab cycle time earlier, rounded up to lots. Each step is offset by its cycle time.'),
    ('Why an OSAT is short of testers',
     'Testing Starts and Tester Capacity show load % (what the plan asks) against testers available (consignee + non-consignee, '
     'after fleet changes). Above 100% the testers cannot make the plan in that month. Plan Yukta then builds ahead with idle '
     'testers in earlier months (pull-in), within the pull-in horizon and the product service level, and makes the rest late '
     '(catch-up). Fixes: add a fleet change, raise OEE, cut test time (more sites), allow non-consignee testers, or move volume '
     'to another OSAT by changing vendor shares.'),
    ('Tester and hardware overrides (future capacity)',
     'Future changes go on the Tester & Capacity Overrides page (sidebar, Capacity & engineering): tester arrivals or removals '
     '(consignee / non-consignee, from a month), hardware arrivals (sockets, load boards, probe and instrument cards), test time / '
     'sites / index / OEE changes from a month, and yield changes. Each applies from its month onwards. The page shows capacity, '
     'load %, pull-in, units made late and customer shortfall with and without the overrides, per OSAT and step. "Overrides off" '
     'shows the baseline plan in every module. In the demo, two testers arrive at OSAT-A Test1 in July 2027 and a faster ORION '
     'test program starts in May; without them customers would be about 2.8M units short.'),
    ('Pull-in and service level',
     'Pull-in uses idle tester time in earlier months to build ahead for a later shortfall. The share of the shortfall that may '
     'be built early is min(service level %, max pull-in %) per product. It never goes further back than the pull-in horizon, or '
     'earlier than material can be built (the fab start lead time). The pull-in weight per product scales it: -0.10 aggressive '
     '(100% of the cap), -0.05 moderate (63%, may use non-consignee testers), -0.02 conservative (40%), 0 neutral (25%, own testers '
     'only), positive = avoid. Pull-in Setup has sliders with a live preview of total gap, pull-in production, forecast '
     'achievement and build-ahead stock. The Module 1 Dashboard shows root cause and a monthly recovery plan.'),
    ('Vendor QBR scorecard and issues log',
     'Vendor QBR & Issues ranks each OSAT 0-100 on quality (test yield vs plan and reported quality), delivery (delivered vs '
     'frozen plan), cost (price index against the lowest quote), capacity (forward test load made on time) and responsiveness '
     '(days to close issues, minus points for overdue and open critical issues). Weights and targets are in QBR scorecard weights. '
     'Grades A >= 90, B >= 80, C >= 70. The page writes a QBR agenda, keeps an 8D-style issues log you can add to and close, and '
     'downloads a QBR pack per vendor.'),
    ('Customer rating',
     'Customer Rating scores how reliably each customer takes agreed orders: 100 - (pushed out % x 0.6 + cancelled % x 1.0 + '
     'reduced % x 0.8), by agreed quantity, from Agreed-order history. Excellent >= 95, Good >= 85, Fair >= 70, else Risk, each '
     'with a commit policy. Open orders are risk-adjusted by the same history.'),
    ('Post-silicon analysis and the test-data API',
     'Post-Silicon Analysis reads lot and wafer test results and bins: control chart (median +/- SPC sigma x robust sigma), lots '
     'below the limit with their failure signature, tester outliers, sustained yield shifts, fail-bin Pareto and bin split vs plan. '
     '"Use in the plan" adds a Yield override at the last-5-lot mean; "Update bin splits" copies the actual pass-bin mix. Results '
     'can be pushed by POST /api/v1/test-results with the bearer token shown on the page, for example from an export job of a '
     'commercial yield-analytics tool; it is a generic JSON endpoint, not a vendor connector.'),
    ('Inventory health',
     'Inventory Health values every WIP lot and finished goods at standard cost for the steps completed, converts WIP to the '
     'finished units it should yield, shows days of supply against plan demand, excess above the threshold weeks plus cycle time, '
     'and aging from the YYWW date code with obsolete risk. In the demo, end-of-life ATLAS has excess and obsolete-risk stock.'),
    ("Holt's method",
     "Holt is not a typo. Holt's linear trend method (Charles C. Holt, 1957) is a standard exponential smoothing forecast that "
     'tracks a level and a trend. Alpha weights the latest level and beta the latest trend. WMAPE and bias are measured on '
     'one-step forecasts over the last six months of shipment history.'),
    ('Tester capacity formula',
     'Final test seconds per unit = (test time + index time) / sites. Sort seconds per wafer = ceil(GDPW / sites) / stepping '
     'efficiency x (test time + index) + wafer load time. Units per tester-month = hours per day x 3600 x OEE x working days / '
     'seconds per unit. Testers needed = load / units per tester-month.'),
    ('Monthly B2B workflow',
     'Day 1-3 refresh demand; day 4 S&OP sign-off; day 5 run the plan and save a snapshot; day 6 send the fab its rolling '
     'wafer-start forecast (frozen month = firm PO); day 7 send OSAT loading forecasts and work orders; day 10 suppliers return '
     'commits; day 12 compare COMMIT with REQUEST and escalate gaps. The B2B package download has REQUEST, COMMIT and GAP rows.'),
    ('Available to promise',
     'ATP = cumulative (finished goods on hand by bin + planned pack output x bin split) - cumulative reservations, taking the '
     'minimum from the month onwards. The order check applies the shippable matrix (customer accepted bins and MOQ), splits across '
     'OSATs and proposes later ship dates when needed. Reserve adds lines to the Reservations table.'),
    ('Inside lead time',
     'A requirement that should already have started before the plan start month (or a fab start before month 0) cannot be met '
     'by new starts. Plan Yukta makes it in the first month and flags it; customers are short only if stock and safety stock '
     'cannot cover the delay. FAB PO lists such wafers under Expedite.'),
    ('Privacy and access',
     'Each tester signs in with their own access code. Each browser session gets its own workspace, kept on the server for 24 '
     'hours and never shown to anyone else. The demo data is synthetic.'),
]


def _sections():
    from . import modules
    out = [(t, b) for t, b in FAQ]
    for key, info in modules.INFO.items():
        body = ' '.join(x for x in [info.get('summary', ''), info.get('what', '')] if x)
        if info.get('how'):
            body += ' Calculation: ' + ' '.join(info['how'])
        if info.get('tryit'):
            body += ' Try: ' + ' '.join(info['tryit'])
        if body.strip():
            out.append((info.get('title', key), body))
    calc = (HERE / 'CALCULATIONS.md').read_text(encoding='utf-8')
    for block in re.split(r'\n(?=## )', calc):
        title = block.strip().splitlines()[0].lstrip('#').strip() if block.strip() else ''
        if title:
            out.append((title, block.strip()))
    from .workspace import TABLES
    for k, m in TABLES.items():
        out.append((f'Data table: {m["title"]}', m['about'] + ' Columns: ' + ', '.join(
            f'{c["name"]}{" (" + c["help"] + ")" if c["help"] else ""}' for c in m['columns'])))
    out.append(('Lot-level audit upload format', format_spec.as_text()))
    return out


SECTIONS = _sections()
STOP = set('a an the is are was were be to of and or in on for with what how why does do i my me it this that '
           'can should which when where who will from by as at if not your you we our'.split())


def _words(text):
    return [w for w in re.findall(r'[a-z0-9&]+', text.lower()) if w not in STOP and len(w) > 1]


def search(question: str, k: int = 2):
    q = set(_words(question))
    scored = []
    for title, body in SECTIONS:
        tw = _words(title)
        bw = _words(body)
        score = sum(3 for w in q if w in tw) + sum(1 for w in q if w in bw)
        scored.append((score, title, body))
    scored.sort(key=lambda x: -x[0])
    top = scored[0][0] if scored else 0
    # keep the best match, plus runners-up only when they score almost as well
    return [(t, b) for s, t, b in scored[:k] if s > 0 and s >= 0.75 * top]


def ai_enabled() -> bool:
    return bool(os.environ.get('ANTHROPIC_API_KEY'))


def _system_prompt(context: str) -> str:
    kb = '\n\n'.join(f'### {t}\n{b}' for t, b in SECTIONS)
    ctx = f'\n\nCURRENT PLAN AND PAGE (summary):\n{context}' if context else ''
    return ('You are "Ask Plan Yukta", the help assistant inside the Plan Yukta pilot, a planning cockpit for fabless '
            'semiconductor supply chains with modules in a sidebar and editable data tables. Answer questions about how to use '
            'the tool, how each number is calculated, what the current plan shows and which data table to change. Use only the reference below and '
            'the results summary; if something is not covered, say so plainly and suggest where to look in the app. '
            'Never invent figures. Keep answers short: a few sentences or a short list, plain language, and name '
            'the page or section to look at. Decline unrelated requests politely.\n\nREFERENCE\n' + kb + ctx)


def ask(question: str, context: str = '', history: list | None = None) -> dict:
    question = (question or '').strip()[:800]
    if not question:
        return {'answer': 'Ask me anything about Plan Yukta: what to upload, how the plan works, or what your results mean.',
                'mode': 'help'}
    if ai_enabled():
        msgs = []
        for turn in (history or [])[-6:]:
            if turn.get('role') in ('user', 'assistant') and turn.get('text'):
                msgs.append({'role': turn['role'], 'content': str(turn['text'])[:1500]})
        msgs.append({'role': 'user', 'content': question})
        while msgs and msgs[0]['role'] != 'user':
            msgs.pop(0)
        body = json.dumps({'model': os.environ.get('CHAT_MODEL', 'claude-haiku-5-5'), 'max_tokens': 700,
                           'system': _system_prompt((context or '')[:6000]), 'messages': msgs}).encode()
        req = urllib.request.Request(API_URL, data=body, method='POST', headers={
            'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': API_VERSION,
            'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read())
            text = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text').strip()
            if text:
                return {'answer': text, 'mode': 'ai'}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            pass   # fall back to help search below
    hits = search(question)
    if not hits:
        return {'answer': "I couldn't find that in the help. Try the Demo Tour or How It Calculates, or ask about a module: "
                          'testing starts, pull-in, tester capacity, ATP, POs, the B2B package, cost or P&L.',
                'mode': 'help'}
    parts = []
    for title, body in hits:
        text = re.sub(r'[#*`|]', '', body)
        text = re.sub(r'\n{2,}', '\n', text).strip()
        parts.append(f'**{title}**\n{text[:1800]}{"…" if len(text) > 1800 else ""}')
    return {'answer': '\n\n'.join(parts), 'mode': 'help'}
