"""
Workforce side of the portfolio: FTE ramp-up economics, productivity levers, hire-vs-contract options,
capacity stress tests and the capacity risk register. Formulas: CALCULATIONS.md section 21a.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, timedelta

from . import portfolio as PF
from .cockpit import month_add

MN = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def ml(m):
    return f'{MN[int(m[5:7]) - 1]} {m[:4]}' if m and len(m) >= 7 else str(m)


CONTRACT_LEAD = {'Contractor': 1, 'Partner': 2}      # months from decision to start


def countries(text):
    """'India 70 / US 30' -> [('India', 70.0), ('US', 30.0)]; plain lists split evenly."""
    parts = [p.strip() for p in re.split(r'[/,;]', str(text or '')) if p.strip()]
    out = []
    for p in parts:
        m = re.match(r'^(.*?)[\s:]+(\d+(?:\.\d+)?)\s*%?$', p)
        out.append((m.group(1).strip(), float(m.group(2))) if m else (p, None))
    if out and any(v is None for _, v in out):
        out = [(c, 100.0 / len(out)) for c, _ in out]
    tot = sum(v for _, v in out) or 0
    return [(c, v / tot * 100) for c, v in out] if tot else []


def ramp_loss(st, rm, sf):
    """FTE-months of output lost per new person before reaching the steady factor (vs a fully productive person)."""
    if rm <= 0:
        return 0.0
    return sum(sf - PF.Portfolio.factor(st, rm, sf, k) for k in range(rm))


def months_to(st, rm, sf, level):
    if st >= level:
        return 0
    if sf < level or rm <= 0:
        return None
    return math.ceil((level - st) / (sf - st) * rm)


# ------------------------------------------------------------------ FTE ramp and levers
def lever_impacts(pf):
    """FTE-months each lever adds over the horizon, alone, against no levers."""
    ch = pf.t['pf_capacity_changes']
    _, base, _ = pf.effective_supply(ch, [], True)
    tot0 = sum(sum(v) for v in base.values())
    out = []
    for l in pf.t.get('pf_levers') or []:
        _, eff, _ = pf.effective_supply(ch, [l], True)
        gain = sum(sum(v) for v in eff.values()) - tot0
        pools = [l['Pool']] if l['Pool'] in pf.pools else list(pf.pools)
        cost_fte_m = sum(float(pf.pools[p]['CostPerFTEk']) for p in pools) / len(pools) / 12 if pools else 0
        cost = float(l.get('CostUSDk') or 0)
        out.append(dict(l, gain=gain, value_k=gain * cost_fte_m, cost_k=cost,
                        roi=(gain * cost_fte_m / cost) if cost else None, counted=l in pf.active_levers()))
    return out


def per_hire(pf, pool):
    """Ramp economics per new person in a pool, by type: baseline vs with counted levers."""
    lev = pf.active_levers()
    rows = []
    for typ, (st, rm, sf, prem) in pf.ramp_prof.items():
        st2, rm2, sf2 = pf.ramp_for(pool, typ, '9999-12', lev)
        rows.append({'type': typ, 'start': st, 'ramp': rm, 'steady': sf, 'premium': prem, 'loss': ramp_loss(st, rm, sf),
                     'start2': st2, 'ramp2': rm2, 'loss2': ramp_loss(st2, rm2, sf2),
                     'to90': months_to(st, rm, sf, 0.9 * sf if sf else 0.9), 'to90_2': months_to(st2, rm2, sf2, 0.9 * sf2 if sf2 else 0.9)})
    return rows


def hire_vs_contract(pf, pool, load=None):
    """Options to cover the pool's first over-target month in the next 12: people needed and 12-month cost by type."""
    load = load or pf.load_committed
    gap_m, gap = None, 0.0
    for i in range(min(12, pf.H)):
        g = load[pool][i] - pf.supply[pool][i] * pf.target[pool]
        if g > 0.5 and gap_m is None:
            gap_m = i
        if gap_m is not None:
            gap = max(gap, g)
    if gap_m is None:
        return None
    lead_perm = int(pf.pools[pool].get('HiringLeadMonths') or 6)
    cost = float(pf.pools[pool]['CostPerFTEk'])
    lev = pf.active_levers()
    out = []
    for typ, lead in (('Permanent hire', lead_perm), ('Contractor', CONTRACT_LEAD['Contractor']), ('Partner', CONTRACT_LEAD['Partner']),
                      ('Transfer', 1)):
        if typ not in pf.ramp_prof:
            continue
        st, rm, sf = pf.ramp_for(pool, typ, month_add(pf.start, lead), lev)
        k = gap_m - lead
        f = PF.Portfolio.factor(st, rm, sf, k) if k >= 0 else 0.0
        prem = pf.ramp_prof[typ][3]
        n = math.ceil(gap / f) if f > 0 else None
        out.append({'type': typ, 'lead': lead, 'start_m': month_add(pf.start, lead), 'factor': f, 'people': n,
                    'cost12': (n * cost * (1 + prem / 100) / 1000) if n else None, 'premium': prem,
                    'ok': f > 0, 'steady_people': math.ceil(gap / sf) if sf else None})
    return {'pool': pool, 'gap_month': pf.months[gap_m], 'gap': gap, 'options': out}


# ------------------------------------------------------------------ stress and risk
def attrition_drag(pf, pool, mult=1.0):
    """Steady-state effective FTE missing because leavers are replaced only after the hiring lead time and ramp-up."""
    r = pf.pools[pool]
    attr = float(r.get('AttritionPct') or 0) / 100 * mult
    lead = int(r.get('HiringLeadMonths') or 0)
    st, rm, sf, _ = pf.ramp_prof.get('Permanent hire', (0.5, 6, 1.0, 0))
    ramp_gap = (rm * (sf - (st + sf) / 2)) if rm else 0
    return float(r['FTE']) * attr / 12 * (lead + ramp_gap)


def stressed(ws, base_changes=None, attr_mult=1.0, freeze=False, contractor_exit=None, lose_country=None, lose_month=None, label=None):
    """Portfolio with expected attrition drag and optional stresses applied as capacity changes."""
    pf0 = PF.Portfolio(ws, base_changes, label)
    ch = [dict(c) for c in pf0.t['pf_capacity_changes'] if not (freeze and c.get('Reason') == 'Hiring plan')]
    notes = []
    if attr_mult:
        for p in pf0.pools:
            d = attrition_drag(pf0, p, attr_mult)
            if d > 0.05:
                ch.append({'Pool': p, 'Month': pf0.start, 'DeltaFTE': -d, 'Reason': 'Attrition'})
        notes.append(f'attrition at {attr_mult:.1f}× each pool\'s rate, backfilled after hiring lead time and ramp-up')
    if contractor_exit:
        for c in list(ch):
            if c.get('Reason') in ('Contractors', 'Partner', 'Scenario') and float(c['DeltaFTE']) > 0:
                ch.append({'Pool': c['Pool'], 'Month': max(contractor_exit, c['Month']), 'DeltaFTE': -float(c['DeltaFTE']), 'Reason': 'Attrition'})
        notes.append(f'all contractors and partners leave from {ml(contractor_exit)}')
    if freeze:
        notes.append('hiring freeze: planned permanent hires do not join')
    if lose_country:
        m = lose_month or pf0.start
        for p, r in pf0.pools.items():
            share = dict(countries(r.get('Countries'))).get(lose_country, 0)
            if share:
                ch.append({'Pool': p, 'Month': m, 'DeltaFTE': -float(r['FTE']) * share / 100, 'Reason': 'Attrition'})
        notes.append(f'{lose_country} sites unavailable from {ml(m)}')
    tables = dict(pf0.t)
    tables['pf_capacity_changes'] = ch
    ws2 = {'tables': dict(ws['tables'], **tables)}
    pf = PF.Portfolio(ws2, None, label)
    pf.stress_notes = notes
    return pf


def _impact(gap, fte):
    r = gap / fte * 100 if fte else 0
    return 5 if r >= 8 else 4 if r >= 4 else 3 if r >= 1.5 else 2 if gap > 0.05 else 1


def risk_register(ws, pf_base, pf_risk):
    """Capacity and workforce risks per pool, scored 1-25, with mitigations and dates."""
    out = []
    as_of = pf_base.as_of
    lev = pf_base.active_levers()
    keyroles = ws['tables'].get('pf_key_roles', [])
    names = {pid: p['Name'] for pid, p in pf_base.projects.items()}

    def add(cat, pool, title, p, i, mitigation, due, owner=None, measure=None):
        out.append({'cat': cat, 'pool': pool, 'title': title, 'P': p, 'I': i, 'score': p * i, 'mitigation': mitigation,
                    'due': due, 'owner': owner or f'{pool} director', 'measure': measure})

    for pool, r in pf_risk.pools.items():
        fte = float(r['FTE'])
        attr = float(r.get('AttritionPct') or 0)
        lead = int(r.get('HiringLeadMonths') or 0)
        load = pf_risk.load_committed[pool]
        gaps = [load[i] - pf_risk.supply[pool][i] * pf_risk.target[pool] for i in range(pf_risk.H)]
        peak = max(gaps) if gaps else 0
        drag = attrition_drag(pf_base, pool)
        if attr > 0:
            add('Attrition', pool, f'{attr:.0f}% a year leave; backfills take {lead} months plus ramp-up, so about {drag:.1f} effective FTE are always missing'
                + (f'. With that, the pool is {peak:.1f} FTE over target at its peak.' if peak > 0.05 else '.'),
                4 if attr >= 12 else 3 if attr >= 8 else 2 if attr >= 5 else 1, _impact(max(peak, 0), fte),
                'Retention plan for critical skills; keep a rolling requisition so backfills start before people leave; '
                'cross-train a second engineer on each block.', as_of + timedelta(days=90), measure=f'{drag:.1f} FTE drag')
        # hiring lead time vs first gap
        first = next((i for i, g in enumerate(gaps) if g > 0.5), None)
        if first is not None:
            st, rm, sf = pf_base.ramp_for(pool, 'Permanent hire', pf_risk.months[first], lev)
            k80 = months_to(st, rm, sf, 0.8) or 0
            need = pf_risk.months[first]
            req_by = month_add(need, -(lead + k80))
            gap_fte = max(gaps[first:first + 3])
            if req_by < pf_risk.start:
                add('Hiring lead time', pool, f'Over target from {ml(need)} by {gap_fte:.1f} FTE; a permanent hire opened today would reach 80% output only in '
                    f'{ml(month_add(pf_risk.start, lead + k80))}.', 5, _impact(gap_fte, fte),
                    'Too late for permanent hiring: bring in contractors or a design partner now (1-2 months to start), or move a proposed '
                    'project later; open permanent requisitions for the following quarters.', as_of + timedelta(days=14), measure=f'{gap_fte:.1f} FTE')
            else:
                add('Hiring lead time', pool, f'Over target from {ml(need)} by {gap_fte:.1f} FTE: requisitions must open by {ml(req_by)} '
                    f'({lead} months to hire + {k80} months to reach 80% output).', 2, _impact(gap_fte, fte),
                    f'Open {math.ceil(gap_fte / 0.8)} requisitions by {ml(req_by)}; prepare onboarding (buddy, accounts, first task) before start.',
                    date(int(req_by[:4]), int(req_by[5:7]), 1), measure=f'{gap_fte:.1f} FTE')
        # ramp timing: new people still ramping in an over-target month
        for c in pf_base.cohorts:
            if c['pool'] != pool or c['fte'] <= 0:
                continue
            for i in range(pf_base.H):
                if gaps[i] > 0.5 and c['eff'][i] > 0:
                    short = c['fte'] * c['steady'] - c['eff'][i]
                    if short > 0.5:
                        add('Ramp-up', pool, f'{c["fte"]:.0f} {c["type"].lower()} FTE from {ml(c["month"])} give only {c["eff"][i]:.1f} effective FTE in '
                            f'{ml(pf_base.months[i])}, a month that is over target.', 4, _impact(short, fte),
                            'Shorten ramp-up: named buddy, scoped first tasks, pre-start access (FTE Ramp & Productivity); '
                            'or start the cohort earlier.', date(int(c['month'][:4]), int(c['month'][5:7]), 1) - timedelta(days=30),
                            measure=f'{short:.1f} FTE short')
                    break
        # contractor dependency
        con = [sum(c['eff'][i] for c in pf_risk.cohorts if c['pool'] == pool and c['type'] in ('Contractor', 'Partner') and c['fte'] > 0)
               for i in range(pf_risk.H)]
        share = max([con[i] / pf_risk.supply[pool][i] * 100 for i in range(pf_risk.H) if pf_risk.supply[pool][i] > 0] + [0])
        if share >= 15:
            add('Contractor dependency', pool, f'Contractors and partners reach {share:.0f}% of effective capacity: knowledge leaves with them and '
                'they can exit at short notice.', 3, 4 if share >= 25 else 3,
                'Keep architecture and sign-off with permanent staff; pair each contractor with an owner; document as you go; '
                'plan conversion of key contractors.', as_of + timedelta(days=60), measure=f'{share:.0f}%')
        # site concentration
        cs = countries(r.get('Countries'))
        if cs:
            c0, s0 = max(cs, key=lambda x: x[1])
            if s0 >= 80:
                add('Site concentration', pool, f'{s0:.0f}% of {pool} is in {c0}: a regional disruption, visa or export change stops the pool.',
                    2, 4, f'Build a second site or partner outside {c0}; keep design data and flows reproducible at another site.',
                    as_of + timedelta(days=120), measure=f'{s0:.0f}% in {c0}')
        # sustained high utilisation
        run = best = 0
        for i in range(pf_risk.H):
            s_ = pf_risk.supply[pool][i]
            u = load[i] / s_ if s_ else 0
            run = run + 1 if u >= pf_risk.target[pool] - 0.02 else 0
            best = max(best, run)
        if best >= 4:
            add('Burnout', pool, f'At or near target utilisation for {best} months in a row: overtime and attrition risk rise.', 3, 3,
                'Phase demand, protect leave, rotate engineers off the busiest project, track overtime monthly.',
                as_of + timedelta(days=60), measure=f'{best} months')
    for k in keyroles:
        if int(k['Backups']) > 0:
            continue
        p = pf_base.projects.get(k.get('ProjectID') or '')
        imp = 5 if (p and p['Funding'] == 'Committed' and p['score'] >= 70) else 4 if (p and p['Funding'] == 'Committed') else 3
        attr = float(pf_base.pools.get(k['Pool'], {}).get('AttritionPct') or 0)
        add('Key person', k['Pool'], f'{k["Role"]}' + (f' on {names.get(k["ProjectID"], k["ProjectID"])}' if k.get('ProjectID') else '')
            + f': {k["Holders"]} holder{"s" if int(k["Holders"]) != 1 else ""}, no trained backup' + (f' ({k["Country"]})' if k.get('Country') else '') + '.',
            4 if attr >= 10 else 3, imp, 'Name and train a backup within 60 days; record the role\'s design knowledge; add a retention agreement.',
            as_of + timedelta(days=60), owner='Project lead')
    out.sort(key=lambda r: (-r['score'], r['pool']))
    for i, r in enumerate(out, start=1):
        r['id'] = f'WR-{i:02d}'
    return out
