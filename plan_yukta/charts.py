"""
Small server-rendered SVG charts. No JavaScript libraries: they render instantly,
work offline and pick up the page's light/dark colours through CSS classes.
"""
from __future__ import annotations

from html import escape

PALETTE = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8']


def _fmt(v):
    a = abs(v)
    if a >= 1e9:
        return f'{v / 1e9:.1f}B'
    if a >= 1e6:
        return f'{v / 1e6:.1f}M'
    if a >= 1e3:
        return f'{v / 1e3:.0f}k' if a >= 1e4 or abs(v / 1e3 - round(v / 1e3)) < 0.05 else f'{v / 1e3:.1f}k'
    if a >= 10 or v == 0:
        return f'{v:.0f}'
    return f'{v:.1f}'


def _nice_max(v):
    if v <= 0:
        return 1
    import math
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def _mlabel(m):
    names = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    try:
        return f'{names[int(m[5:7]) - 1]} {m[2:4]}'
    except (ValueError, IndexError):
        return str(m)


def bars(labels, series, stacked=True, height=220, unit='', lines=None, ref=None, title=''):
    """series: [(name, values)]; lines: [(name, values)] drawn over the bars; ref: horizontal line (value, label)."""
    W, H, L, R, T, B = 760, height, 52, 12, 14, 30
    n = len(labels) or 1
    if stacked:
        tops = [sum(max(0, s[1][i] or 0) for s in series) for i in range(n)]
    else:
        tops = [max([s[1][i] or 0 for s in series] + [0]) for i in range(n)]
    extra = [v or 0 for _, vals in (lines or []) for v in vals] + ([ref[0]] if ref else [])
    vmax = _nice_max(max(tops + extra + [0]) * 1.05)
    pw = (W - L - R) / n
    y = lambda v: T + (H - T - B) * (1 - (v or 0) / vmax)
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    for t in (0, .25, .5, .75, 1):
        yy = y(vmax * t)
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
                   f'<text class="ax" x="{L - 6}" y="{yy + 4:.1f}" text-anchor="end">{_fmt(vmax * t)}</text>')
    step = 1 if n <= 14 else 2
    for i, lab in enumerate(labels):
        if i % step == 0:
            out.append(f'<text class="ax" x="{L + pw * (i + .5):.1f}" y="{H - 10}" text-anchor="middle">{escape(_mlabel(lab))}</text>')
    k = len(series)
    for i in range(n):
        base = 0.0
        for si, (name, vals) in enumerate(series):
            v = max(0.0, vals[i] or 0)
            if stacked:
                x, w = L + pw * i + pw * .18, pw * .64
                y0, y1 = y(base + v), y(base)
                base += v
            else:
                w = pw * .7 / max(1, k)
                x = L + pw * i + pw * .15 + w * si
                y0, y1 = y(v), y(0)
            if v > 0:
                out.append(f'<rect class="{PALETTE[si % 8]}" x="{x:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{max(.5, y1 - y0):.1f}" rx="2">'
                           f'<title>{escape(name)} · {escape(_mlabel(labels[i]))}: {vals[i]:,.0f}{unit}</title></rect>')
    for li, (name, vals) in enumerate(lines or []):
        pts = ' '.join(f'{L + pw * (i + .5):.1f},{y(v):.1f}' for i, v in enumerate(vals) if v is not None)
        out.append(f'<polyline class="ln l{li + 1}" fill="none" points="{pts}"><title>{escape(name)}</title></polyline>')
        for i, v in enumerate(vals):
            if v is not None:
                out.append(f'<circle class="dot l{li + 1}" cx="{L + pw * (i + .5):.1f}" cy="{y(v):.1f}" r="3">'
                           f'<title>{escape(name)} · {escape(_mlabel(labels[i]))}: {v:,.0f}{unit}</title></circle>')
    if ref:
        yy = y(ref[0])
        out.append(f'<line class="ref" x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
                   f'<text class="ax ref-t" x="{W - R}" y="{yy - 5:.1f}" text-anchor="end">{escape(ref[1])}</text>')
    out.append('</svg>')
    leg = ''.join(f'<span><i class="sw {PALETTE[i % 8]}"></i>{escape(n_)}</span>' for i, (n_, _) in enumerate(series))
    leg += ''.join(f'<span><i class="sw ln-sw l{i + 1}"></i>{escape(n_)}</span>' for i, (n_, _) in enumerate(lines or []))
    if ref:
        leg += f'<span><i class="sw ref-sw"></i>{escape(ref[1])}</span>'
    return '<figure class="fig">' + ''.join(out) + f'<figcaption class="legend">{leg}</figcaption></figure>'


def lines(labels, series, height=220, unit='', split_at=None, title='', vmin=None, xlab=None, dec=0):
    """series: [(name, values, dashed)]; split_at: index where the forecast starts.
    vmin: bottom of the y axis (default 0); xlab: function for x labels; dec: decimals in tooltips and axis."""
    W, H, L, R, T, B = 760, height, 52, 12, 14, 30
    n = len(labels) or 1
    vals = [v for _, vs, _ in series for v in vs if v is not None]
    lo = 0 if vmin is None else vmin
    vmax = _nice_max(max(vals + [0]) * 1.08) if vmin is None else max(vals + [lo + 1e-9]) + (max(vals + [lo]) - lo) * 0.08
    x = lambda i: L + (W - L - R) * (i / max(1, n - 1))
    y = lambda v: T + (H - T - B) * (1 - (v - lo) / ((vmax - lo) or 1))
    xl = xlab or _mlabel
    vf = (lambda v: f'{v:.{dec}f}') if dec else _fmt
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    for t in (0, .25, .5, .75, 1):
        vv = lo + (vmax - lo) * t
        yy = y(vv)
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
                   f'<text class="ax" x="{L - 6}" y="{yy + 4:.1f}" text-anchor="end">{vf(vv)}</text>')
    step = max(1, n // 12)
    for i, lab in enumerate(labels):
        if i % step == 0:
            out.append(f'<text class="ax" x="{x(i):.1f}" y="{H - 10}" text-anchor="middle">{escape(xl(lab))}</text>')
    if split_at is not None and 0 < split_at < n:
        xx = (x(split_at - 1) + x(split_at)) / 2
        out.append(f'<line class="now" x1="{xx:.1f}" x2="{xx:.1f}" y1="{T}" y2="{H - B}"/>'
                   f'<text class="ax" x="{xx + 4:.1f}" y="{T + 10}">plan →</text>')
    for si, (name, vs, dashed) in enumerate(series):
        pts = [(i, v) for i, v in enumerate(vs) if v is not None]
        if len(pts) >= 2:
            d = ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in pts)
            dash = ' stroke-dasharray="5 4"' if dashed else ''
            out.append(f'<polyline class="ln l{si + 1}" fill="none" points="{d}"{dash}><title>{escape(name)}</title></polyline>')
        if len(pts) > 2 and len({v for _, v in pts}) == 1:
            continue          # constant reference line (limit, target): no dots
        for i, v in pts:
            out.append(f'<circle class="dot l{si + 1}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.6">'
                       f'<title>{escape(name)} · {escape(xl(labels[i]))}: {v:,.{dec}f}{unit}</title></circle>')
    out.append('</svg>')
    leg = ''.join(f'<span><i class="sw ln-sw l{i + 1}{" dashed" if d else ""}"></i>{escape(n_)}</span>' for i, (n_, _, d) in enumerate(series))
    return '<figure class="fig">' + ''.join(out) + f'<figcaption class="legend">{leg}</figcaption></figure>'


def gantt(rows, start, end, today=None, height_per=24):
    """rows: [{'name', 'start': date, 'end': date, 'kind', 'readout': date|None}]"""
    W, L, R, T = 760, 210, 12, 22
    H = T + height_per * len(rows) + 10
    span = max(1, (end - start).days)
    x = lambda d: L + (W - L - R) * ((d - start).days / span)
    out = [f'<svg class="chart gantt" viewBox="0 0 {W} {H}" role="img" aria-label="Timeline">']
    # month ticks
    from datetime import date
    m = date(start.year, start.month, 1)
    while m <= end:
        if m >= start:
            xx = x(m)
            out.append(f'<line class="grid" x1="{xx:.1f}" x2="{xx:.1f}" y1="{T - 6}" y2="{H - 6}"/>'
                       f'<text class="ax" x="{xx + 3:.1f}" y="{T - 9}">{m:%b %y}</text>')
        m = date(m.year + (m.month // 12), m.month % 12 + 1, 1)
    for i, r in enumerate(rows):
        yy = T + i * height_per
        out.append(f'<text class="ax g-label" x="{L - 8}" y="{yy + 15}" text-anchor="end">{escape(r["name"][:32])}</text>')
        x0, x1 = x(r['start']), x(r['end'])
        out.append(f'<rect class="g-{r.get("kind", "osat")}" x="{x0:.1f}" y="{yy + 4}" width="{max(2, x1 - x0):.1f}" height="14" rx="3">'
                   f'<title>{escape(r["name"])}: {r["start"]:%d %b %Y} to {r["end"]:%d %b %Y}</title></rect>')
        if r.get('readout'):
            x2 = x(r['readout'])
            out.append(f'<rect class="g-readout" x="{x1:.1f}" y="{yy + 7}" width="{max(1, x2 - x1):.1f}" height="8" rx="2">'
                       f'<title>Readout to {r["readout"]:%d %b %Y}</title></rect>')
    for d, label, cls in (today or []):
        if start <= d <= end:
            xx = x(d)
            out.append(f'<line class="{cls}" x1="{xx:.1f}" x2="{xx:.1f}" y1="{T - 4}" y2="{H - 4}"/>'
                       f'<text class="ax {cls}-t" x="{xx + 3:.1f}" y="{H - 6}">{escape(label)}</text>')
    out.append('</svg>')
    return '<figure class="fig">' + ''.join(out) + '</figure>'


def flow_diagram(stages):
    """stages: [(name, qty_text, unit, tone)] drawn as a chain of boxes."""
    n = len(stages)
    W, H = 760, 108
    bw = (W - 16) / n - 14
    out = [f'<svg class="chart flowsvg" viewBox="0 0 {W} {H}" role="img" aria-label="Process flow">']
    for i, (name, qty, unit, tone) in enumerate(stages):
        x = 8 + i * (bw + 14)
        out.append(f'<rect class="fbox {tone}" x="{x:.1f}" y="18" width="{bw:.1f}" height="70" rx="10"/>'
                   f'<text class="fname" x="{x + bw / 2:.1f}" y="40" text-anchor="middle">{escape(name)}</text>'
                   f'<text class="fqty" x="{x + bw / 2:.1f}" y="64" text-anchor="middle">{escape(qty)}</text>'
                   f'<text class="funit" x="{x + bw / 2:.1f}" y="80" text-anchor="middle">{escape(unit)}</text>')
        if i < n - 1:
            ax = x + bw + 2
            out.append(f'<path class="farrow" d="M{ax:.1f},53 l9,0 m-4,-4 l4,4 l-4,4"/>')
    out.append('</svg>')
    return '<figure class="fig">' + ''.join(out) + '</figure>'


def donut(items, title='', unit=''):
    """items: [(label, value)] drawn as a donut with a legend."""
    import math
    tot = sum(max(0, v) for _, v in items) or 1
    W, H, cx, cy, r, w = 430, max(200, 40 + 24 * len(items)), 95, 100, 85, 26
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    a0 = -math.pi / 2
    for i, (lab, v) in enumerate(items):
        v = max(0, v)
        if v <= 0:
            continue
        a1 = a0 + 2 * math.pi * v / tot
        if v >= tot - 1e-9:
            a1 = a0 + 2 * math.pi - 1e-4
        large = 1 if a1 - a0 > math.pi else 0
        x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        ri = r - w
        xi1, yi1, xi0, yi0 = cx + ri * math.cos(a1), cy + ri * math.sin(a1), cx + ri * math.cos(a0), cy + ri * math.sin(a0)
        out.append(f'<path class="seg {PALETTE[i % 8]}" d="M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f} L{xi1:.1f},{yi1:.1f} '
                   f'A{ri},{ri} 0 {large} 0 {xi0:.1f},{yi0:.1f} Z"><title>{escape(lab)}: {v:,.0f}{unit} ({v / tot * 100:.1f}%)</title></path>')
        a0 = a1
    out.append(f'<text class="dn-v" x="{cx}" y="{cy + 2}" text-anchor="middle">{_fmt(tot)}</text>'
               f'<text class="ax" x="{cx}" y="{cy + 20}" text-anchor="middle">total{escape(unit)}</text>')
    for i, (lab, v) in enumerate(items):
        y = 36 + i * 24
        out.append(f'<rect class="{PALETTE[i % 8]}" x="205" y="{y - 10}" width="12" height="12" rx="3"/>'
                   f'<text class="dn-l" x="224" y="{y}">{escape(lab)}</text>'
                   f'<text class="dn-n" x="426" y="{y}" text-anchor="end">{_fmt(v)} · {max(0, v) / tot * 100:.0f}%</text>')
    out.append('</svg>')
    return '<figure class="fig">' + ''.join(out) + '</figure>'


def roadmap(lanes, start, end, today=None, deps=None):
    """Swimlane roadmap.
    lanes: [(lane label, [item])]; item: {'id', 'name', 'start': date, 'end': date, 'fc_end': date|None, 'cls': str,
           'gates': [(date, label, state)], 'tip': str}. state: passed | planned | late | conditional.
    deps: [(from id, to id, ok)] drawn as connectors from the end of one bar to the end of the other."""
    from datetime import date
    W, L, R, T, rowh, laneh = 1000, 150, 16, 30, 26, 22
    n_rows = sum(len(items) for _, items in lanes)
    H = T + n_rows * rowh + len(lanes) * laneh + 16
    span = max(1, (end - start).days)
    x = lambda d: L + (W - L - R) * (min(max((d - start).days, 0), span) / span)
    out = [f'<svg class="chart roadmap" viewBox="0 0 {W} {H}" role="img" aria-label="Roadmap">']
    y0 = T
    q = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    while q <= end:
        if q >= start:
            xx = x(q)
            out.append(f'<line class="grid{" yr" if q.month == 1 else ""}" x1="{xx:.1f}" x2="{xx:.1f}" y1="{T - 8}" y2="{H - 8}"/>'
                       f'<text class="ax" x="{xx + 3:.1f}" y="{T - 14}">{"Q" + str((q.month - 1) // 3 + 1)}{" " + str(q.year) if q.month == 1 or q == start else ""}</text>')
        q = date(q.year + (1 if q.month >= 10 else 0), (q.month + 2) % 12 + 1, 1)
    pos = {}
    for lane, items in lanes:
        out.append(f'<rect class="lane" x="0" y="{y0}" width="{W}" height="{laneh - 4}" rx="3"/>'
                   f'<text class="lane-t" x="8" y="{y0 + 13}">{escape(lane)}</text>')
        y0 += laneh
        for it in items:
            yy = y0 + 4
            x0, x1 = x(it['start']), x(it['end'])
            out.append(f'<text class="ax g-label" x="{L - 8}" y="{yy + 13}" text-anchor="end">{escape(it["name"][:22])}</text>')
            out.append(f'<rect class="rm {it.get("cls", "")}" x="{x0:.1f}" y="{yy}" width="{max(3, x1 - x0):.1f}" height="16" rx="4">'
                       f'<title>{escape(it.get("tip") or it["name"])}</title></rect>')
            if it.get('fc_end') and it['fc_end'] > it['end']:
                x2 = x(it['fc_end'])
                out.append(f'<rect class="rm-slip" x="{x1:.1f}" y="{yy + 3}" width="{max(2, x2 - x1):.1f}" height="10" rx="3">'
                           f'<title>Forecast release {it["fc_end"]:%b %Y}: {round((it["fc_end"] - it["end"]).days / 30.4)} months late</title></rect>')
                x1 = x2
            for d, lab, st in it.get('gates', []):
                if not (start <= d <= end):
                    continue
                gx = x(d)
                out.append(f'<path class="gate {st}" d="M{gx:.1f} {yy + 1} l6 7 -6 7 -6 -7z"><title>{escape(lab)} · {d:%d %b %Y} · {st}</title></path>')
            pos[it['id']] = (x1, yy + 8)
            y0 += rowh
    for a, b, ok in deps or []:
        if a in pos and b in pos:
            (xa, ya), (xb, yb) = pos[a], pos[b]
            mid = (xa + xb) / 2
            out.append(f'<path class="dep {"ok" if ok else "bad"}" d="M{xa:.1f} {ya:.1f} C{mid:.1f} {ya:.1f} {mid:.1f} {yb:.1f} {xb:.1f} {yb:.1f}"/>')
    for d, label, cls in (today or []):
        if start <= d <= end:
            xx = x(d)
            out.append(f'<line class="{cls}" x1="{xx:.1f}" x2="{xx:.1f}" y1="{T - 8}" y2="{H - 6}"/>'
                       f'<text class="ax {cls}-t" x="{xx + 3:.1f}" y="{H - 2}">{escape(label)}</text>')
    out.append('</svg>')
    return '<figure class="fig wide">' + ''.join(out) + '</figure>'


def bubble(points, xlabel, ylabel, height=300, xmax=None, ymax=None, quad=None):
    """points: [{'label', 'x', 'y', 'r' (size value), 'cls'}]. quad: (x split, y split, [tl, tr, bl, br] labels)."""
    import math
    W, H, L, R, T, B = 760, height, 56, 16, 16, 40
    xs = [p['x'] for p in points] or [1]
    ys = [p['y'] for p in points] or [1]
    xm = xmax or _nice_max(max(xs) * 1.1)
    ym = ymax or _nice_max(max(ys) * 1.1)
    rm = max([p['r'] for p in points] + [1])
    X = lambda v: L + (W - L - R) * v / xm
    Y = lambda v: T + (H - T - B) * (1 - v / ym)
    out = [f'<svg class="chart bubble" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(ylabel)} by {escape(xlabel)}">']
    for t in (0, .25, .5, .75, 1):
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{Y(ym * t):.1f}" y2="{Y(ym * t):.1f}"/>'
                   f'<text class="ax" x="{L - 6}" y="{Y(ym * t) + 4:.1f}" text-anchor="end">{_fmt(ym * t)}</text>'
                   f'<text class="ax" x="{X(xm * t):.1f}" y="{H - 22}" text-anchor="middle">{_fmt(xm * t)}</text>')
    if quad:
        qx, qy, labs = quad
        out.append(f'<line class="quad" x1="{X(qx):.1f}" x2="{X(qx):.1f}" y1="{T}" y2="{H - B}"/>'
                   f'<line class="quad" x1="{L}" x2="{W - R}" y1="{Y(qy):.1f}" y2="{Y(qy):.1f}"/>')
        for (tx, ty, anc), lab in zip(((L + 6, T + 12, 'start'), (W - R - 6, T + 12, 'end'), (L + 6, H - B - 6, 'start'),
                                        (W - R - 6, H - B - 6, 'end')), labs):
            out.append(f'<text class="quad-t" x="{tx}" y="{ty}" text-anchor="{anc}">{escape(lab)}</text>')
    out.append(f'<text class="ax" x="{(L + W - R) / 2:.0f}" y="{H - 4}" text-anchor="middle">{escape(xlabel)}</text>'
               f'<text class="ax" x="12" y="{(T + H - B) / 2:.0f}" transform="rotate(-90 12 {(T + H - B) / 2:.0f})" text-anchor="middle">{escape(ylabel)}</text>')
    for p in sorted(points, key=lambda p: -p['r']):
        r = 5 + 20 * math.sqrt(max(p['r'], 0) / rm)
        cx, cy = X(min(p['x'], xm)), Y(min(p['y'], ym))
        out.append(f'<circle class="bub {p.get("cls", "")}" cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"><title>{escape(p.get("tip") or p["label"])}</title></circle>'
                   f'<text class="bub-t" x="{cx:.1f}" y="{cy + 3:.1f}" text-anchor="middle">{escape(p["label"])}</text>')
    out.append('</svg>')
    return '<figure class="fig">' + ''.join(out) + '</figure>'
