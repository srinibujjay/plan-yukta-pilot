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
     'Plan Yukta runs a fabless planning cycle in five modules: (1) Material now: WIP across fab and OSAT with '
     'double-counted rows removed, E&O, capacity check and lot lead times; (2) Demand forecast; (3) Module-level '
     'supply plan; (4) Tester (ATE) capacity; (5) Monthly B2B package for FAB and OSAT. Upload one workbook made '
     'from the template and all five run together.'),
    ('How the plan works backwards (reverse flow)',
     'The plan starts from customer demand and works backwards through the manufacturing modules. '
     '1) Finished goods: projected stock = last month + receipts from current WIP - demand. If it falls below the '
     'safety stock target (weeks of supply x weekly demand), the gap is a planned receipt. '
     '2) Final test and assembly: to receive N good units, N / (assembly yield x final test yield) good die must '
     'enter assembly, (assembly + final test weeks) earlier. '
     '3) Die bank: those die come from sorted good die in stock first. '
     '4) Wafer sort, bump and fab: any remaining die need new wafers = die / (GDW x fab line yield x sort yield), '
     'rounded up to whole lots, started (fab + bump + sort weeks) before assembly. A start that would fall before '
     'the first plan month is flagged "inside lead time". '
     '5) Testers: the final-test and sort loads from this plan, plus the WIP already in the line, are converted to '
     'tester hours using test time, sites and index time, and compared with testers x hours x OEE. '
     '6) B2B: the fab wafer starts and OSAT module loads become the rolling forecasts sent to suppliers, with '
     'frozen, slushy and liquid time fences.'),
    ("Holt's method",
     "Holt is not a typo. Holt's linear trend method (Charles C. Holt, 1957) is a standard exponential smoothing "
     'forecast that tracks a level and a trend. Alpha weights the latest level and beta the latest trend; higher '
     'values react faster to recent months. Plan Yukta reports WMAPE (forecast error as a share of actuals) and '
     'bias (positive = forecast runs high) over the last six months.'),
    ('Module-level planning',
     '"Module" means each manufacturing step a fabless product passes through: fab, bump, wafer sort, assembly and '
     'final test. Each module has its own yield, cycle time and usually its own supplier. The supply plan gives the '
     'monthly load on each module so you can agree capacity with each supplier.'),
    ('Tester capacity planning',
     'Final test seconds per unit = (test time + index time) / sites. Wafer sort seconds per wafer = '
     'ceil(GDW / sites) / stepping efficiency x (test time + index time) + wafer load time. Hours needed = quantity '
     'x seconds / 3600. Hours available = testers x hours per week x 4.33 x OEE. Above 85% is tight, above 100% '
     'overloaded; the plan also shows how many testers would be needed. Fixes: add testers, raise OEE, cut test '
     'time (more sites, shorter program), or move load to another month.'),
    ('Monthly B2B workflow',
     'Working day 1-3 refresh demand; day 4 S&OP sign-off; day 5 run supply and tester plans; day 6 send the fab '
     'rolling wafer-start forecast (frozen month is a firm order); day 7 send the OSAT loading forecast and work '
     'orders; day 10 suppliers return commits; day 12 compare commits with requests and escalate gaps. Daily: '
     'receive WIP and shipment notices. The B2B package download has REQUEST, COMMIT and GAP rows.'),
    ('Inside lead time and shortage alerts',
     'Inside lead time means the plan would have needed a start before the first plan month, so only stock or WIP '
     'can cover that month: expedite, allocate or pull from the die bank. Shortage means projected finished goods '
     'go negative.'),
    ('Privacy and access',
     'Uploads are processed in memory and not stored. Each tester signs in with their own access code; the pilot '
     'owner adds or removes codes in the hosting settings.'),
]


def _sections():
    out = [(t, b) for t, b in FAQ]
    calc = (HERE / 'CALCULATIONS.md').read_text(encoding='utf-8')
    for block in re.split(r'\n(?=## )', calc):
        title = block.strip().splitlines()[0].lstrip('#').strip() if block.strip() else ''
        if title:
            out.append((title, block.strip()))
    out.append(('Upload format', format_spec.as_text()))
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
    ctx = f'\n\nCURRENT RESULTS ON THE TESTER\'S SCREEN (summary):\n{context}' if context else ''
    return ('You are "Ask Plan Yukta", the help assistant inside the Plan Yukta pilot, a planning tool for fabless '
            'semiconductor supply chains. Answer questions about how to use the tool, what to upload, how each '
            'number is calculated, and what the tester\'s current results mean. Use only the reference below and '
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
        return {'answer': "I couldn't find that in the help. Try the pages \"What it does\", \"Upload format\" or "
                          '"How it calculates", or ask about uploads, the forecast, the supply plan, testers or the B2B package.',
                'mode': 'help'}
    parts = []
    for title, body in hits:
        text = re.sub(r'[#*`|]', '', body)
        text = re.sub(r'\n{2,}', '\n', text).strip()
        parts.append(f'**{title}**\n{text[:1800]}{"…" if len(text) > 1800 else ""}')
    return {'answer': '\n\n'.join(parts), 'mode': 'help'}
