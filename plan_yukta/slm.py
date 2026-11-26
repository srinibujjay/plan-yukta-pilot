"""Yukta Lite: a small, local question-answering engine for the landing page.

No API key, no model download and no GPU: it runs in a few milliseconds inside the app.
It is not a generative language model. It answers three kinds of question:

1. Questions about the visitor's own plan data (demand, shortfall, tester load, wafer POs, holds,
   revenue and margin, inventory, vendor scorecards, customer ratings, NPI, portfolio capacity),
   by spotting the intent and the product / OSAT / step / month named in the question.
2. "What is ..." questions, from a built-in semiconductor glossary plus the Plan Yukta ERM glossary.
3. Anything else, by ranking the Plan Yukta help, formulas and data-table notes (BM25) and quoting
   the most relevant sentences with a link to the page.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .cockpit import TEST_OPS

# ------------------------------------------------------------------ semiconductor glossary
SEMI_GLOSSARY = {
    'OSAT': 'Outsourced Semiconductor Assembly and Test: the partner that bumps, assembles, tests and packs die after the fab. A fabless company plans capacity, yield and cycle time at each OSAT.',
    'fabless': 'A chip company that designs and sells chips but owns no fab; it buys wafers from a foundry and assembly and test from OSATs, so planning and supplier management are its core operations job.',
    'foundry': 'The wafer fab that manufactures wafers for fabless customers to their design, on a chosen process node.',
    'wafer start': 'A wafer released into the fab. Wafer starts happen one fab cycle time (often 10–16 weeks) before the wafers come out, so they are committed long before demand is certain.',
    'fab cycle time': 'Time from wafer start to fab out, typically 8–16 weeks depending on node and layer count; hot lots can be faster at a premium.',
    'GDPW': 'Gross die per wafer: how many complete die fit on one wafer, from die size and wafer diameter. Good die = GDPW x sort yield.',
    'CP': 'Chip probe (also wafer sort): electrical test of every die on the wafer before it is diced. CP yield is the share of die that pass.',
    'wafer sort': 'Testing each die on the wafer with a probe card before dicing, to find good die (also called CP or probe). Sort yield feeds the die bank.',
    'FT': 'Final test: testing packaged units on ATE with handlers. FT yield is the share of packaged units that pass; many products have FT1 (e.g. hot) and FT2 (e.g. cold or room).',
    'final test': 'Electrical test of packaged units on ATE (FT). Test time per unit, number of sites and OEE decide how many testers you need.',
    'ATE': 'Automatic test equipment: the tester that runs the test program at wafer sort or final test. Capacity per tester = available seconds x OEE / seconds per unit.',
    'OEE': 'Overall equipment effectiveness = availability x performance x quality. A tester at 80% OEE gives 80% of its theoretical output.',
    'probe card': 'The custom fixture of fine needles that contacts the die pads during wafer sort; a long-lead hardware item that can limit sort capacity.',
    'load board': 'The product-specific board that connects the packaged unit (through a socket) to the tester at final test; also long-lead hardware.',
    'multi-site': 'Testing several units or die at once on one tester. Seconds per unit = (test time + index time) / sites.',
    'index time': 'The handler or prober time to swap units between test insertions; it adds to test time in the capacity formula.',
    'bump': 'Adding solder or copper-pillar bumps to the wafer pads so the die can be flip-chip mounted.',
    'flip chip': 'Mounting the die face down on the substrate through bumps, giving short connections and many I/Os.',
    'wire bond': 'Connecting die pads to the lead frame or substrate with fine gold or copper wires; cheaper and common for lower pin counts.',
    'substrate': 'The small printed-circuit-like base a die is mounted on in a BGA or flip-chip package; advanced substrates can have long lead times and tight supply.',
    'lead frame': 'A stamped or etched metal frame that carries the die in packages such as QFN and SOIC.',
    'QFN': 'Quad flat no-lead package: small, cheap, good thermal pad; common for power and analog chips.',
    'WLCSP': 'Wafer-level chip-scale package: the package is built on the wafer itself, so the package is the size of the die.',
    'BGA': 'Ball grid array package: solder balls on the underside for many connections; usually on an organic substrate.',
    'chiplet': 'A smaller die that is combined with others in one package to make a larger product, so each part can use the best node and yield is higher than one big die.',
    '2.5D': 'Packaging where die sit side by side on a silicon interposer or bridge with very dense wiring between them, often with HBM next to a large logic die.',
    '3D packaging': 'Stacking die on top of each other with through-silicon vias or hybrid bonding, for the shortest connections.',
    'HBM': 'High-bandwidth memory: stacked DRAM placed next to a processor in a 2.5D package. Supply is concentrated in a few makers, so HBM allocation is a key planning risk.',
    'interposer': 'A silicon (or organic) layer with fine wiring that connects die placed side by side in 2.5D packaging.',
    'KGD': 'Known good die: die fully tested before packaging, essential for multi-die packages because one bad die scraps the whole assembly.',
    'die bank': 'Stock of sorted, good die held before assembly. It decouples the long fab lead time from shorter assembly and test, and is a common place for safety stock.',
    'WIP': 'Work in progress: wafers or units started but not finished. Plan Yukta nets WIP at each step before asking for new starts.',
    'yield': 'The share of good output at a step (sort, assembly, test). Cumulative yield multiplies the step yields; starts needed = good units needed / yield.',
    'defect density': 'D0: defects per unit area on a wafer. Die yield falls as die area x D0 grows, which is why big die and new nodes yield lower.',
    'binning': 'Sorting tested units into bins by performance (speed, power) or failure type. Customers accept certain bins, so the bin split drives what can ship.',
    'burn-in': 'Running units at high voltage and temperature to screen out early failures (infant mortality), mainly for automotive and high-reliability parts.',
    'HTOL': 'High-temperature operating life: a reliability qualification test running parts at high temperature and voltage, often for 1,000 hours.',
    'AEC-Q100': 'The automotive qualification standard for integrated circuits, defining stress tests such as HTOL, temperature cycling and ESD.',
    'JEDEC': 'The standards body for semiconductor packaging, reliability tests (for example MSL and HTOL methods) and memory.',
    'MSL': 'Moisture sensitivity level: how long a package can be exposed to air before it must be baked before soldering (MSL1 unlimited to MSL6 very short).',
    'qualification': 'The set of reliability and characterisation tests a product must pass before volume shipment; it often sets the NPI critical path.',
    'NPI': 'New product introduction: the path from tape-out through first silicon, characterisation, qualification and ramp to high-volume manufacturing.',
    'tape-out': 'Sending the final chip design to the foundry to make masks; the start of the silicon part of NPI.',
    'mask set': 'The set of photomasks for a design; costly on advanced nodes, which is why changes after tape-out are expensive.',
    'MPW': 'Multi-project wafer (shuttle): several designs share one mask set and wafer run to cut prototype cost.',
    'HVM': 'High-volume manufacturing: the product is qualified and ramped into steady production.',
    'EOL': 'End of life: a product being discontinued. Plan last-time buys and avoid building stock that becomes obsolete.',
    'last time buy': 'A final order customers place before a product is discontinued; it sets the last builds and the risk of obsolete stock.',
    'S&OP': 'Sales and operations planning: the monthly process that agrees one demand plan and one supply plan across sales, operations and finance.',
    'MPS': 'Master production schedule: the agreed plan of what to build, when, after S&OP.',
    'MRP': 'Material requirements planning: exploding the build plan into material and component needs by date.',
    'safety stock': 'Extra stock held to cover demand and supply variation. In Plan Yukta it is set in weeks of demand per product.',
    'ATP': 'Available to promise: stock plus planned output not yet reserved for customers, used to promise new orders reliably.',
    'CTP': 'Capable to promise: like ATP but also checks whether capacity and material could make more by the requested date.',
    'lead time': 'Time from order or start to availability. In fabless supply chains the fab lead time dominates, so early decisions carry the most risk.',
    'frozen zone': 'The near-term window in which the plan or POs cannot change without penalty, because material is already committed.',
    'pull-in': 'Building ahead in earlier months with spare capacity to cover a later capacity shortfall.',
    'bullwhip effect': 'Small changes in end demand growing into large swings upstream, because each tier over-orders; long fab lead times make it worse.',
    'LTA': 'Long-term agreement: a supply contract reserving capacity or volume over years, sometimes with prepayment or take-or-pay terms.',
    'take-or-pay': 'A contract term where the buyer pays for reserved capacity even if it does not use it.',
    'allocation': 'Rationing scarce supply across customers or products by priority when demand exceeds supply.',
    'SPC': 'Statistical process control: tracking a process with control limits so shifts are caught early (for example yield below mean minus 3 sigma).',
    'Cpk': 'Process capability index: how well a process fits inside its specification limits; 1.33 or higher is a common target.',
    '8D': 'Eight disciplines problem solving: team, describe, contain, root cause, corrective action, validate, prevent, close. Used for supplier quality issues.',
    'PPAP': 'Production part approval process: the automotive package proving a supplier process can make parts consistently.',
    'QBR': 'Quarterly business review with a supplier: scorecard (quality, delivery, cost, capacity, responsiveness), issues and actions.',
    'process node': 'The manufacturing generation of a fab process (for example 28 nm or 5 nm class). Newer nodes give more transistors per area but cost more and have longer cycle times.',
    'EDA': 'Electronic design automation: the software used to design and verify chips.',
    'tape and reel': 'Packing finished units in carrier tape on reels for automated board assembly; the usual final pack step.',
    'RMA': 'Return material authorisation: the process for customer returns and failure analysis.',
    'COGS': 'Cost of goods sold: wafer, assembly, test and other unit costs. Gross margin = (revenue - COGS) / revenue.',
    'FTE': 'Full-time equivalent: one person working full time for the period. A new joiner often delivers about 0.5 FTE at first, ramping to 1.0.',
}
ALIASES = {'cp yield': 'CP', 'chip probe': 'CP', 'probe test': 'wafer sort', 'ft yield': 'FT', 'ft1': 'FT', 'ft2': 'FT',
           'osat': 'OSAT', 'osats': 'OSAT', 'gross die per wafer': 'GDPW', 'automatic test equipment': 'ATE', 'tester': 'ATE',
           'hbm': 'HBM', 'chiplets': 'chiplet', '2.5d packaging': '2.5D', '3d': '3D packaging', 'known good die': 'KGD',
           'work in progress': 'WIP', 'd0': 'defect density', 'bin split': 'binning', 'bins': 'binning', 'sop': 'S&OP',
           's op': 'S&OP', 'sales and operations planning': 'S&OP', 'available to promise': 'ATP', 'capable to promise': 'CTP',
           'long term agreement': 'LTA', 'statistical process control': 'SPC', 'new product introduction': 'NPI',
           'high volume manufacturing': 'HVM', 'end of life': 'EOL', 'last time buy': 'last time buy', 'ltb': 'last time buy',
           'moisture sensitivity level': 'MSL', 'aec q100': 'AEC-Q100', 'aecq100': 'AEC-Q100', 'node': 'process node',
           'cycle time': 'fab cycle time', 'wafer starts': 'wafer start', 'die-bank': 'die bank', 'pullin': 'pull-in',
           'pull in': 'pull-in', 'bullwhip': 'bullwhip effect', 'tape out': 'tape-out', 'shuttle': 'MPW',
           'overall equipment effectiveness': 'OEE', 'cost of goods sold': 'COGS', 'full time equivalent': 'FTE'}

STOP = set('a an the is are was were be to of and or in on for with what whats how why does do did i my me it this that '
           'can could should which when where who will from by as at if not your you we our us please tell show give '
           'explain about there their any some much many get let know need want would like'.split())
MONTHS = {m: i + 1 for i, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split())}


def _stem(w):
    for suf in ('ings', 'ing', 'ies', 'es', 's', 'ed'):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)] + ('y' if suf == 'ies' else '')
    return w


def _toks(text):
    return [_stem(w) for w in re.findall(r'[a-z0-9&]+', text.lower()) if w not in STOP and len(w) > 1]


# ------------------------------------------------------------------ BM25 over the help text
class _Index:
    def __init__(self, docs):
        self.docs = docs                          # (title, body, page)
        self.tf = [Counter(_toks(t) * 3 + _toks(b)) for t, b, _ in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.titles = [set(_toks(t)) for t, _, _ in docs]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter(w for c in self.tf for w in c)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def search(self, q, k=3):
        qt = set(_toks(q))
        out = []
        for i, c in enumerate(self.tf):
            s = 0.0
            for w in qt:
                f = c.get(w)
                if f:
                    s += self.idf[w] * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * self.len[i] / self.avg))
            if s > 0:
                tt = self.titles[i]
                s += sum(1.5 * self.idf.get(w, 1) for w in qt if w in tt and w not in GENERIC)
                s /= 1 + max(0.0, self.len[i] / self.avg - 3) * 0.15   # long reference pages should not drown short, focused ones
                out.append((s, i))
        out.sort(reverse=True)
        return [(s, self.docs[i]) for s, i in out[:k]]


GENERIC = set(_toks('how plan yukta calculate calculated work works page module data table use using'))
_INDEX = None


def _index():
    global _INDEX
    if _INDEX is None:
        from . import assistant, learn, modules
        docs = []
        title_to_key = {v.get('title', k): k for k, v in modules.INFO.items()}
        for t, b in assistant.SECTIONS:
            if t.lower() in ('how plan yukta calculates', 'how it calculates'):   # intro pages: too general to quote
                continue
            docs.append((t, b, title_to_key.get(t)))
        for term, d in SEMI_GLOSSARY.items():
            docs.append((term, d, None))
        for g in learn.GLOSSARY:
            docs.append((g[0], f'{g[1]} {g[2]}', g[3] if len(g) > 3 else None))
        _INDEX = _Index(docs)
    return _INDEX


def _best_sentences(body, q, n=3):
    text = re.sub(r'[#*`|]', ' ', body)
    text = re.sub(r'\s+', ' ', text).strip()
    sents = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9(])', text)
    qt = set(_toks(q))
    scored = [(len(qt & set(_toks(s))), -i, s) for i, s in enumerate(sents) if 20 < len(s) < 600]
    scored.sort(reverse=True)
    keep = sorted(scored[:n], key=lambda x: -x[1])
    return ' '.join(s for _, _, s in keep) if keep and keep[0][0] > 0 else ' '.join(sents[:2])


# ------------------------------------------------------------------ helpers
def short(n):
    n = float(n or 0)
    for d, s in ((1e9, 'B'), (1e6, 'M'), (1e3, 'k')):
        if abs(n) >= d:
            return f'{n / d:.1f}{s}'
    return f'{n:.0f}'


def money(n):
    return '$' + short(n)


def mlabel(m):
    from datetime import date
    try:
        y, mm = m.split('-')
        return date(int(y), int(mm), 1).strftime('%b %Y')
    except (ValueError, AttributeError):
        return str(m)


def link(label, path):
    return f'[{label}]({path})'


class Ctx:
    def __init__(self, R, ws, q):
        self.R, self.ws, self.q = R, ws, q
        self.p = R['plan']
        self.low = ' ' + re.sub(r'[^a-z0-9&\- ]', ' ', q.lower()) + ' '
        self.toks = set(_toks(q))
        self.skus = [s for s in self.p.products if re.search(rf'\b{s.lower()}\b', self.low)]
        vend = [v['Vendor'] for v in ws['tables']['vendors']]
        self.vendors = [v for v in vend if re.search(rf'\bosat[\s-]?{v.lower()}\b|\bvendor[\s-]{v.lower()}\b', self.low)]
        step = None
        for pat, st in ((r'\b(test ?1|ft ?1|final test 1)\b', 'Test1'), (r'\b(test ?2|ft ?2|final test 2)\b', 'Test2'),
                        (r'\b(sort|probe|cp)\b', 'Sort'), (r'\bassembl', 'Assembly'), (r'\bbump', 'Bump'), (r'\bpack\b', 'Pack')):
            if re.search(pat, self.low):
                step = st
                break
        self.step = step
        self.month = self._month()
        custs = sorted({o['Customer'] for o in ws['tables'].get('orders', [])})
        self.customers = [c for c in custs if c.lower() in self.low or c.split()[-1].lower() in self.toks]

    def _month(self):
        months = self.p.months
        m = re.search(r'\b(20\d\d)-(\d\d)\b', self.low)
        if m and m.group(0) in months:
            return m.group(0)
        if 'next month' in self.low and len(months) > 1:
            return months[1]
        if 'this month' in self.low:
            return months[0]
        m = re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:uary|ruary|ch|il|e|y|ust|t|tember|ober|ember)?\b(?:\s*(20\d\d))?', self.low)
        if m:
            mm = MONTHS[m.group(1)]
            cands = [x for x in months if int(x[5:]) == mm and (not m.group(2) or x[:4] == m.group(2))]
            if cands:
                return cands[0]
        return None

    def has(self, *words):
        return any((' ' + w + ' ') in self.low or _stem(w) in self.toks for w in words)


# ------------------------------------------------------------------ data answers
def a_overview(c):
    h = c.R['home']
    pk = h['load_peak']
    lines = [f'**Plan at a glance** ({mlabel(c.p.months[0])} to {mlabel(c.p.months[-1])}):',
             f'- Demand next 6 months: **{short(h["demand6"])} units**',
             f'- Customer shortfall: **{short(h["short"]) + " units" if h["short"] > 0.5 else "none"}**',
             f'- Peak tester load: **{pk[0]:.0f}%** at OSAT-{pk[1]} {pk[2]} in {mlabel(pk[3])}',
             f'- Wafer POs to act on: **{len(h["po_due"])}** · lots on hold: **{len(h["holds"])}**',
             f'- Plan revenue: **{money(h["revenue"])}** at **{h["gm"]:.1f}%** gross margin']
    if h['alerts']:
        lines.append('\n**Top alerts**')
        for a in h['alerts'][:4]:
            lines.append(f'- {a["module"]} · {mlabel(a.get("month"))}: {a["text"]}')
    lines.append('\nFull detail: ' + link('Planning cockpit', '/cockpit'))
    return '\n'.join(lines)


def a_demand(c):
    months = c.p.months
    skus = c.skus or list(c.p.products)
    i = months.index(c.month) if c.month else None
    lines = []
    for s in skus:
        d = (c.p.dem.get(s) or [])[:len(months)]
        if not d:
            continue
        if i is not None:
            lines.append(f'- **{s}**: {short(d[i])} units in {mlabel(months[i])}')
        else:
            lines.append(f'- **{s}**: {short(sum(d[:6]))} units over the next 6 months (peak {short(max(d))} in {mlabel(months[d.index(max(d))])})')
    head = f'**Plan demand{" for " + mlabel(c.month) if c.month else ", next 6 months"}**'
    return head + '\n' + '\n'.join(lines) + '\n\nBuild strategy and forecast vs orders: ' + link('Demand & Forecast', '/m/demand')


def a_short(c):
    t = c.R['flow']['totals']
    months = c.p.months
    tot = sum(t['short'])
    if tot < 0.5:
        return ('**No customer shortfall** in the plan horizon: pull-in, catch-up and stock cover every month.\n\n'
                'See how the tester crunch is absorbed: ' + link('M1 · Testing Starts', '/m/testing'))
    worst = [(months[i], v) for i, v in enumerate(t['short']) if v > 0.5]
    lines = [f'**Customers are short {short(tot)} units** across the horizon:'] + \
            [f'- {mlabel(m)}: {short(v)} units' for m, v in worst[:6]]
    return '\n'.join(lines) + '\n\nRoot cause and recovery plan: ' + link('M1 Dashboard', '/m/m1-dashboard')


def a_load(c):
    p, months = c.p, c.p.months
    cells = []
    for (v, st), a in p.alloc.items():
        if c.vendors and v not in c.vendors:
            continue
        if c.step and st != c.step:
            continue
        for i, x in enumerate(a['summary'][:p.H]):
            if c.month and months[i] != c.month:
                continue
            cells.append((x['load_util'], v, st, months[i], x))
    if not cells:
        return 'That OSAT does not run that test step in this plan. Try "tester load at OSAT-A Test1".'
    cells.sort(key=lambda z: -z[0])
    if c.vendors and c.step and c.month:
        u, v, st, m, x = cells[0]
        return (f'**OSAT-{v} {st} in {mlabel(m)}: {u:.0f}% load** ({x["needed"]:.1f} testers needed vs {x["total"]} available).'
                + (f' Pull-in {short(x["pullin"])} units, catch-up {short(x["catchup"])}.' if x['pullin'] or x['catchup'] else '')
                + '\n\nDetail: ' + link('Tester Capacity', f'/m/testers?vendor={v}'))
    over = [z for z in cells if z[0] > 100]
    head = f'**Highest tester load{" at OSAT-" + c.vendors[0] if c.vendors else ""}{" " + c.step if c.step else ""}:**'
    lines = [f'- OSAT-{v} {st}, {mlabel(m)}: **{u:.0f}%** ({x["needed"]:.1f} needed / {x["total"]} available)' for u, v, st, m, x in cells[:5]]
    tail = (f'\n\n{len(over)} month-cells are above 100%: the plan builds ahead (pull-in) or late (catch-up) there.' if over
            else '\n\nNothing is above 100%.')
    return head + '\n' + '\n'.join(lines) + tail + '\n\nFixes and overrides: ' + link('Tester Capacity', '/m/testers') + ' · ' + \
        link('Tester & Capacity Overrides', '/m/overrides')


def a_po(c):
    rows = c.R['home']['po_due']
    if c.skus:
        rows = [r for r in rows if r['sku'] in c.skus]
    if not rows:
        return 'No wafer POs are due or past cutoff' + (f' for {", ".join(c.skus)}' if c.skus else '') + '.\n\n' + link('FAB PO Schedule', '/m/fab-po')
    lines = [f'**{len(rows)} wafer PO line{"s" if len(rows) != 1 else ""} to act on:**'] + [
        f'- {r["sku"]}: {r["wafers"]} wafers ({r["lots"]} lots) starting {mlabel(r["start_month"])} for {mlabel(r["out_month"])} fab out, '
        f'{money(r["value"])}, **{r["status"].lower()}**' for r in rows[:6]]
    return '\n'.join(lines) + '\n\nRolling forecast and POs: ' + link('FAB PO Schedule', '/m/fab-po')


def a_holds(c):
    rows = c.R['home']['holds']
    if c.skus:
        rows = [r for r in rows if any(s[:2] in str(r.get('VendorProduct', '')) for s in c.skus)]
    if not rows:
        return 'No lots are on hold.\n\n' + link('OSAT WIP', '/m/osat-wip')
    lines = [f'**{len(rows)} lot{"s" if len(rows) != 1 else ""} on hold** (not counted as supply):'] + [
        f'- {r["LotID"]} at OSAT-{r["Vendor"]}, {r.get("VendorOperation", "")}, {r.get("VendorProduct", "")}' for r in rows[:8]]
    return '\n'.join(lines) + '\n\nLot list and states: ' + link('OSAT WIP', '/m/osat-wip')


def a_revenue(c):
    rows = c.R['pnl']['rows']
    h = c.R['home']
    if c.skus or c.customers:
        sel = [r for r in rows if (not c.skus or r['sku'] in c.skus) and (not c.customers or r['customer'] in c.customers)
               and (not c.month or r['month'] == c.month)]
        rev = sum(r['revenue'] for r in sel)
        cogs = sum(r['cogs'] for r in sel)
        who = ', '.join(c.skus + c.customers)
        gm = (rev - cogs) / rev * 100 if rev else 0
        return (f'**{who}{" in " + mlabel(c.month) if c.month else ""}: revenue {money(rev)}, COGS {money(cogs)}, '
                f'gross margin {gm:.1f}%.**\n\n' + link('P&L', '/m/pnl') + ' · ' + link('Cost', '/m/cost'))
    by = Counter()
    for r in rows:
        by[r['sku']] += r['revenue']
    lines = [f'**Plan revenue {money(h["revenue"])} at {h["gm"]:.1f}% gross margin** over {len(c.p.months)} months:'] + \
            [f'- {s}: {money(v)}' for s, v in by.most_common()]
    return '\n'.join(lines) + '\n\n' + link('P&L', '/m/pnl') + ' · ' + link('Cost', '/m/cost')


def a_inventory(c):
    from . import insights as I
    V = I.inventory_view(c.p, c.R)
    rows = [r for r in V['products'] if not c.skus or r['sku'] in c.skus]
    lines = ['**Inventory health** (WIP + finished goods at standard cost):']
    for r in rows:
        extra = []
        if r['excess'] > 0.5:
            extra.append(f'excess {short(r["excess"])} units ({money(r["excess_value"])})')
        if r['obsolete_qty'] > 0.5:
            extra.append(f'obsolete risk {money(r["obsolete_value"])}')
        dos = f'{r["dos"]:.0f} days of supply' if r['dos'] is not None and r['dos'] < 9999 else 'no near-term demand'
        lines.append(f'- **{r["sku"]}** ({r["status"]}): {money(r["value"])}, {dos}' + (f'; {", ".join(extra)}' if extra else ''))
    return '\n'.join(lines) + '\n\nAging and lot detail: ' + link('Inventory Health', '/m/inventory')


def a_vendor(c):
    from . import insights as I
    Q = I.qbr_view(c.p, c.R, 'L3')
    rows = [s for s in Q['scores'] if not c.vendors or s['vendor'] in c.vendors]
    lines = [f'**Vendor scorecard, {Q["months"][0]} to {Q["months"][-1]}** (0–100):']
    for s in sorted(rows, key=lambda s: -s['total']):
        weak = min(s['scores'], key=s['scores'].get)
        lines.append(f'- **{s["name"]}**: {s["total"]:.0f} (grade {s["grade"]}), weakest {weak.lower()} {s["scores"][weak]:.0f}, '
                     f'{s["open"]} open issue{"s" if s["open"] != 1 else ""}')
    acts = [a for a in Q['actions'] if not c.vendors or a['vendor'] in c.vendors][:2]
    if acts:
        lines.append('\n**Suggested actions**')
        lines += [f'- OSAT-{a["vendor"]} {a["category"].lower()}: {a["action"]}' for a in acts]
    return '\n'.join(lines) + '\n\nQBR agenda and issues log: ' + link('Vendor QBR & Issues', '/m/vendor-qbr')


def a_customer(c):
    from . import insights as I
    C = I.customer_view(c.p, c.R)
    rows = [x for x in C['customers'] if not c.customers or x['customer'] in c.customers]
    lines = ['**Customer rating** (how reliably each customer takes agreed orders):'] + [
        f'- **{x["customer"]}**: {x["score"]:.0f} ({x["rating"]}), pushed out {x["push_pct"]:.0f}%, cancelled {x["cancel_pct"]:.0f}%. '
        f'{x["policy"]}' for x in rows]
    return '\n'.join(lines) + '\n\n' + link('Customer Rating', '/m/customers')


def a_npi(c):
    rows = [x for x in c.R['npi']['products'] if not c.skus or x['sku'] in c.skus]
    if not rows:
        return 'No NPI product matches that.\n\n' + link('NPI Management', '/m/npi')
    lines = []
    for x in rows:
        risk = f'**at risk**: qualification ends {x["qual_done"]:%d %b %Y}, after first demand in {mlabel(x["first_demand"])}' if x['risk'] \
            else f'on track: qualification ends {x["qual_done"]:%d %b %Y}'
        lines.append(f'- **{x["sku"]}**: fab start {x["start"]:%d %b %Y}, samples {x["samples"]:%d %b %Y}, {risk}. '
                     f'Cumulative yield {x["yield_cum"]:.0f}%.')
    return '**NPI status**\n' + '\n'.join(lines) + '\n\nTimeline and qualification plan: ' + link('NPI Management', '/m/npi')


def a_product(c):
    prods = {r['SKU']: r for r in c.ws['tables']['products']}
    out = []
    for s in c.skus:
        r = prods.get(s)
        if r:
            d = c.p.dem.get(s) or [0]
            out.append(f'**{s}**: {r.get("Description")}, {r.get("Package")} package, status {r.get("Status")}, '
                       f'GDPW {r.get("GDPW"):,}, build strategy {r.get("BuildStrategy")}, safety stock {r.get("SafetyStockWeeks")} weeks, '
                       f'service level {r.get("ServiceLevelPct")}%. Demand next 6 months {short(sum(d[:6]))} units.')
    return '\n\n'.join(out) + '\n\nEdit product settings: ' + link('SKU Setup', '/m/sku-setup')


def a_list(c):
    if c.has('customer'):
        custs = sorted({o['Customer'] for o in c.ws['tables'].get('orders', [])})
        return '**Customers:** ' + ', '.join(custs) + '\n\n' + link('Customer Rating', '/m/customers')
    if c.has('osat', 'vendor', 'supplier'):
        vs = c.ws['tables']['vendors']
        return '**OSATs:** ' + '; '.join(f'{v["Name"]} ({v["Region"]}, {v["SharePct"]:.0f}% share)' for v in vs) + \
            '\n\n' + link('Vendor QBR & Issues', '/m/vendor-qbr')
    prods = c.ws['tables']['products']
    return '**Products:**\n' + '\n'.join(f'- **{r["SKU"]}**: {r["Description"]}, {r["Package"]}, {r["Status"]}' for r in prods) + \
        '\n\n' + link('SKU Setup', '/m/sku-setup')


def a_checks(c):
    items = c.R['checks']['items']
    if not items:
        return 'All data checks pass.\n\n' + link('Data Checks', '/m/checks')
    return f'**{len(items)} data check{"s" if len(items) != 1 else ""}:**\n' + '\n'.join(
        f'- {i["severity"]}: {i["message"]}' for i in items[:6]) + '\n\n' + link('Data Checks', '/m/checks')


def a_portfolio(c):
    from . import portfolio as PF
    pf = PF.Portfolio(c.ws)
    k = pf.kpis()
    over = []
    for x in pf.supply:
        worst = max(range(len(pf.supply[x])), key=lambda i: pf.load_committed[x][i] - pf.supply[x][i] * pf.target[x])
        gap = pf.load_committed[x][worst] - pf.supply[x][worst] * pf.target[x]
        if gap > 0.5:
            over.append((gap, x))
    over.sort(reverse=True)
    lines = [f'**Engineering portfolio:** {k["projects"]} projects ({k["committed"]} committed, {k["proposed"]} proposed), '
             f'capacity used next 12 months **{k["util12"]:.0f}%**, {k["red"]} red and {k["amber"]} amber, '
             f'{k["dep_conflicts"]} dependency conflict{"s" if k["dep_conflicts"] != 1 else ""}.']
    if over:
        lines.append('\n**Skill pools over target at their worst month:**')
        lines += [f'- {x}: {g:.1f} FTE short' for g, x in over[:4]]
    reds = [p['Name'] for p in pf.projects.values() if p.get('health') == 'R']
    if reds:
        lines.append('\nRed projects: ' + ', '.join(reds))
    return '\n'.join(lines) + '\n\n' + link('Portfolio Overview', '/m/pf-overview') + ' · ' + link('Capacity vs Demand', '/m/pf-capacity')


# ------------------------------------------------------------------ routing
GREET = re.compile(r'^\s*(hi|hello|hey|hai|namaste|good (morning|afternoon|evening))\b', re.I)
DEFINE = re.compile(r'^\s*(what\s+is|what\s+are|what\'s|whats|define|meaning\s+of|explain|full\s+form\s+of|expand)\s+(an?\s+|the\s+)?(.+?)\??\s*$', re.I)

HELP = ('I\'m **Yukta Lite**, a small assistant that runs inside Plan Yukta (no AI service, no cost). Try:\n'
        '- **Your plan:** "How is the plan?", "Demand for ORION in March", "Tester load at OSAT-A Test1", '
        '"Which wafer POs are due?", "Lots on hold", "Revenue by product", "Inventory health"\n'
        '- **Suppliers and customers:** "Vendor scorecard", "Customer rating", "NPI status"\n'
        '- **Portfolio:** "Which skill pools are overloaded?"\n'
        '- **Concepts:** "What is GDPW?", "What is a die bank?", "Explain HBM"\n'
        '- **How the tool works:** "How is tester capacity calculated?", "How does pull-in work?"')

INTENTS = [
    # name, required-any word list, handler, extra-score words
    ('portfolio', ('portfolio', 'roadmap', 'fte', 'skill', 'pool', 'headcount', 'engineer', 'project', 'funding'), a_portfolio, ()),
    ('npi', ('npi', 'qualification', 'qual', 'new product', 'nova', 'at risk'), a_npi, ('status', 'risk')),
    ('vendor', ('scorecard', 'score', 'qbr', 'vendor score', 'best osat', 'worst osat', 'supplier performance', 'grade', 'rank'), a_vendor, ('osat',)),
    ('customer', ('customer rating', 'customer score', 'reliable customer', 'rating', 'push out', 'cancel'), a_customer, ('customer',)),
    ('po', ('po', 'pos', 'purchase order', 'wafer order', 'order wafer', 'cutoff', 'expedite', 'wafer start'), a_po, ('wafer', 'fab')),
    ('holds', ('hold', 'held', 'on hold'), a_holds, ('lot',)),
    ('short', ('short', 'shortfall', 'shortage', 'late', 'miss', 'backlog', 'gap'), a_short, ('customer',)),
    ('load', ('load', 'utilisation', 'utilization', 'tester', 'testers', 'capacity', 'overload', 'crunch', 'bottleneck'), a_load,
     ('osat', 'test1', 'test2', 'sort')),
    ('inventory', ('inventory', 'stock', 'excess', 'obsolete', 'days of supply', 'aging', 'ageing', 'dos'), a_inventory, ()),
    ('revenue', ('revenue', 'margin', 'p&l', 'pnl', 'profit', 'sales', 'cogs', 'asp'), a_revenue, ()),
    ('demand', ('demand', 'forecast', 'volume', 'requirement'), a_demand, ('unit',)),
    ('checks', ('data check', 'data checks', 'error', 'warning', 'validation'), a_checks, ()),
    ('list', ('list', 'which products', 'what products', 'all products', 'our products', 'which osat', 'all osat',
              'which customer', 'all customer'), a_list, ()),
    ('overview', ('overview', 'summary', 'alert', 'alerts', 'how is the plan', 'how is my plan', 'plan status', 'top risks', 'key risks',
                  'top issues', 'key issues', 'any issues', 'any risks', 'whats wrong', 'what is wrong', 'attention', 'today',
                  'status of the plan', 'how are we doing'), a_overview, ()),
]
HOWTO = re.compile(r'(\bhow (do|does|to|can|should) |\bformula|calculat|\bcomputed?\b|\bwhy does\b|\bwhere do\b|\bupload|\bimport\b|\bexport\b|\bwork\b)', re.I)


def _glossary_lookup(term):
    t = term.lower().strip(' ?.').removesuffix(' mean').strip()
    t = re.sub(r'^(a|an|the)\s+', '', t)
    key = ALIASES.get(t) or next((k for k in SEMI_GLOSSARY if k.lower() == t), None)
    if not key and t.endswith('s'):
        key = ALIASES.get(t[:-1]) or next((k for k in SEMI_GLOSSARY if k.lower() == t[:-1]), None)
    if key:
        return key, SEMI_GLOSSARY[key], None
    from . import learn
    for g in learn.GLOSSARY:
        name = g[0].lower()
        abbr = re.findall(r'\(([^)]+)\)', name)
        if t == name or t == re.sub(r'\s*\([^)]*\)', '', name) or (abbr and t == abbr[0].lower()):
            return g[0], f'{g[1]} {g[2]}', (g[3] if len(g) > 3 else None)
    return None


def _page_link(key):
    from . import modules
    if not key:
        return ''
    return '\n\nSee: ' + link(modules.label(key), '/m/' + key)


def _intent_score(c, words, extra):
    s, seen = 0, set()
    for w in words:
        if ' ' in w or '&' in w:
            s += 3 if (' ' + w + ' ') in c.low else 0
        elif _stem(w) not in seen and ((' ' + w + ' ') in c.low or _stem(w) in c.toks):
            seen.add(_stem(w))
            s += 2
    s += sum(1 for w in extra if (' ' + w + ' ') in c.low)
    return s


def _search_answer(q, res):
    s, (title, body, key) = res[0]
    txt = _best_sentences(body, q, 3)
    more = [t for sc, (t, _, _) in res[1:] if sc > 0.6 * s and t != title]
    out = f'**{title}**\n{txt}' + _page_link(key)
    if more:
        out += '\n\nRelated: ' + '; '.join(more[:2])
    return {'answer': out, 'mode': 'lite', 'kind': 'search'}


def answer(question: str, R, ws) -> dict:
    q = (question or '').strip()[:800]
    if not q:
        return {'answer': HELP, 'mode': 'lite', 'kind': 'help'}
    if GREET.match(q) and len(q.split()) <= 4:
        return {'answer': 'Hello! ' + HELP, 'mode': 'lite', 'kind': 'greet'}
    if re.search(r'\b(help|what can you do|who are you|commands)\b', q, re.I) and len(q.split()) <= 6:
        return {'answer': HELP, 'mode': 'lite', 'kind': 'help'}
    c = Ctx(R, ws, q)

    # "what is GDPW" style definitions, unless the question is clearly about the plan data
    m = DEFINE.match(q)
    if m and not HOWTO.search(q):
        hit = _glossary_lookup(m.group(3))
        if hit:
            term, body, key = hit
            return {'answer': f'**{term}**: {body}' + _page_link(key), 'mode': 'lite', 'kind': 'define'}

    # how-to questions go to the help text first (formulas, workflows)
    if HOWTO.search(q):
        res = _index().search(q, 3)
        if res and res[0][0] > 3.0:
            return _search_answer(q, res)

    # data intents
    if not HOWTO.search(q):
        scored = sorted(((_intent_score(c, w, x), n, h) for n, w, h, x in INTENTS), key=lambda z: -z[0])
        best = scored[0]
        if best[0] >= 2:
            try:
                return {'answer': best[2](c), 'mode': 'lite', 'kind': best[1]}
            except Exception:  # noqa: BLE001 - a data gap must never break the chat
                pass
        if c.skus and len(c.toks) <= 4:
            return {'answer': a_product(c), 'mode': 'lite', 'kind': 'product'}

    # glossary term mentioned anywhere (short questions)
    if len(c.toks) <= 3:
        for n in (3, 2, 1):
            words = re.findall(r'[a-z0-9&.\-]+', q.lower())
            for i in range(len(words) - n + 1):
                hit = _glossary_lookup(' '.join(words[i:i + n]))
                if hit:
                    term, body, key = hit
                    return {'answer': f'**{term}**: {body}' + _page_link(key), 'mode': 'lite', 'kind': 'define'}

    # help-text search
    res = _index().search(q, 3)
    if res and res[0][0] > 2.0:
        return _search_answer(q, res)
    return {'answer': "I don't have an answer for that yet. I know Plan Yukta's data, how each module calculates, and common "
                      'semiconductor and supply chain terms.\n\n' + HELP, 'mode': 'lite', 'kind': 'none'}


def context_for_llm(question: str, R, ws) -> str:
    """Facts for the optional on-device model: the Lite answer plus the best help passages."""
    base = answer(question, R, ws)['answer']
    res = _index().search(question, 2)
    extra = '\n\n'.join(f'{t}: {_best_sentences(b, question, 4)}' for _, (t, b, _) in res)
    return (base + '\n\n' + extra)[:3500]
