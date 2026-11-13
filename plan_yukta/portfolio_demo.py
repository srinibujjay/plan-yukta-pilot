"""Synthetic portfolio and roadmap demo data: an IP and silicon company's engineering portfolio.

Codenames, owners, values and Jira keys are invented. Categories mirror a typical processor IP
business (CPU, GPU, AI accelerator, compute subsystems, system IP, software, test silicon)."""
from __future__ import annotations

from datetime import date


def _m(s, k):
    y, m = int(s[:4]), int(s[5:7])
    t = y * 12 + m - 1 + k
    return f'{t // 12}-{t % 12 + 1:02d}'


def _span(a, b):
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


# ProjectID, Name, BU, Category, Stage, Funding, Start, Launch, Owner, Confidence, Value $M, Fit, Demand, TimeCrit, Risk, size, JiraKey, SKU, Notes
PROJECTS = [
    ('PF-01', 'Basalt', 'Infrastructure', 'CPU IP', 'Develop', 'Committed', '2025-09', '2027-06', 'Infra CPU lead', 'High', 950, 5, 5, 5, 3, 1.0, 'PYRM-101', None,
     'Next-generation server performance core.'),
    ('PF-02', 'Obsidian', 'Infrastructure', 'Compute subsystem', 'Plan', 'Committed', '2026-07', '2028-03', 'Infra CSS lead', 'Medium', 1400, 5, 5, 4, 4, 1.1, 'PYRM-102', None,
     'Cloud compute subsystem built on Basalt and the Feldspar mesh; validated on the Quartz test chip.'),
    ('PF-03', 'Garnet', 'Client', 'CPU IP', 'Validate', 'Committed', '2025-03', '2027-01', 'Client CPU lead', 'High', 620, 4, 5, 4, 2, 0.8, 'PYRM-103', None,
     'High-efficiency client core.'),
    ('PF-04', 'Topaz', 'Client', 'GPU IP', 'Develop', 'Committed', '2026-01', '2027-09', 'Client GPU lead', 'Medium', 540, 4, 4, 4, 3, 0.9, 'PYRM-104', None,
     'Graphics core with ray-tracing and ML upgrades. Alpha slipped; release forecast three months late.'),
    ('PF-05', 'Jasper', 'Client', 'Compute subsystem', 'Concept', 'Proposed', '2026-12', '2028-06', 'Client CSS lead', 'Medium', 880, 5, 4, 4, 3, 1.0, None, None,
     'Mobile compute subsystem combining Garnet and Topaz.'),
    ('PF-06', 'Onyx', 'Automotive', 'CPU IP', 'Develop', 'Committed', '2025-11', '2027-12', 'Auto CPU lead', 'Medium', 410, 4, 4, 3, 3, 0.7, 'PYRM-106', None,
     'Safety-capable core with split-lock for functional-safety designs.'),
    ('PF-07', 'Beryl', 'Automotive', 'Compute subsystem', 'Concept', 'Proposed', '2027-02', '2028-12', 'Auto CSS lead', 'Low', 520, 4, 3, 3, 4, 0.8, None, None,
     'Automotive compute subsystem on Onyx for software-defined vehicles.'),
    ('PF-08', 'Feldspar', 'Platform', 'System IP', 'Develop', 'Committed', '2026-02', '2027-09', 'System IP lead', 'High', 300, 4, 3, 3, 2, 0.5, 'PYRM-108', None,
     'Coherent mesh interconnect for many-core designs.'),
    ('PF-09', 'Mica', 'IoT', 'CPU IP', 'Plan', 'Committed', '2026-06', '2027-12', 'IoT lead', 'High', 180, 3, 4, 3, 2, 0.4, 'PYRM-109', None,
     'Microcontroller-class core with a small neural unit.'),
    ('PF-10', 'Pyrite', 'Platform', 'Software & tools', 'Develop', 'Committed', '2026-01', '2027-06', 'Tools lead', 'High', 120, 4, 3, 4, 2, 0.5, 'PYRM-110', None,
     'Compilers and performance libraries for the new architecture features in Basalt.'),
    ('PF-11', 'Quartz', 'Infrastructure', 'Silicon & chiplets', 'Plan', 'Committed', '2026-09', '2027-12', 'Silicon lead', 'Medium', 60, 4, 2, 4, 4, 0.6, 'PYRM-111', 'NOVA',
     'Test chip to validate Obsidian in silicon before customer tape-outs. Linked to product NOVA in the supply plan.'),
    ('PF-12', 'Agate', 'Platform', 'Security IP', 'Concept', 'Proposed', '2027-03', '2028-06', 'Security lead', 'Medium', 220, 3, 3, 2, 3, 0.4, None, None,
     'Confidential-compute security block.'),
    ('PF-13', 'Zircon', 'Platform', 'AI accelerator IP', 'Concept', 'Proposed', '2027-01', '2028-09', 'AI IP lead', 'Low', 1100, 5, 4, 5, 5, 0.9, None, None,
     'Second-generation neural accelerator for client and edge AI.'),
    ('PF-14', 'Spinel', 'Client', 'Software & tools', 'Plan', 'Proposed', '2026-12', '2027-10', 'Developer platform lead', 'High', 90, 3, 3, 3, 1, 0.3, None, None,
     'Virtual prototypes so partners start software before silicon.'),
    ('PF-15', 'Galena', 'Infrastructure', 'System IP', 'Idea', 'Proposed', '2027-04', '2029-03', 'Chiplet lead', 'Low', 700, 5, 3, 3, 4, 0.8, None, None,
     'Next-generation die-to-die chiplet interface.'),
    ('PF-16', 'Hematite', 'Platform', 'CPU IP', 'Sustain', 'Committed', '2024-01', '2025-06', 'Sustaining lead', 'High', 80, 2, 3, 2, 1, 0.3, 'PYRM-116', None,
     'Maintenance releases and errata fixes for shipping cores.'),
]

POOLS = [  # Pool, FTE, target util %, cost per FTE-year $k, countries, attrition %/yr, hiring lead months
    ('Architecture', 22, 90, 260, 'US 60 / Canada 40', 5, 8),
    ('CPU design', 105, 90, 230, 'US 50 / India 50', 9, 6),
    ('GPU & ML design', 36, 90, 230, 'Canada 70 / Taiwan 30', 8, 6),
    ('Verification', 190, 92, 200, 'India 70 / US 30', 14, 4),
    ('Physical design', 66, 90, 210, 'India 60 / Taiwan 40', 13, 5),
    ('Performance modelling', 22, 85, 240, 'US 100', 7, 6),
    ('Software & tools', 66, 88, 190, 'India 60 / Canada 40', 12, 3),
    ('Silicon & test', 13, 85, 210, 'Taiwan 85 / US 15', 8, 5),
    ('Program management', 26, 90, 180, 'US 50 / India 50', 7, 3),
]

DESIGN_POOL = {'CPU IP': 'CPU design', 'GPU IP': 'GPU & ML design', 'AI accelerator IP': 'GPU & ML design',
               'Compute subsystem': 'CPU design', 'System IP': 'CPU design', 'Security IP': 'CPU design'}


def _phases(cat):
    """(pool, start fraction, end fraction, FTE at size 1, months after launch)"""
    if cat == 'Software & tools':
        return [('Software & tools', 0.0, 1.0, 24, 2), ('Performance modelling', 0.0, 0.5, 2, 0), ('Program management', 0.0, 1.0, 1.5, 0)]
    if cat == 'Silicon & chiplets':
        return [('Architecture', 0.0, 0.25, 3, 0), ('Physical design', 0.1, 0.7, 14, 0), ('Verification', 0.05, 0.6, 10, 0),
                ('Silicon & test', 0.5, 1.0, 12, 3), ('Software & tools', 0.6, 1.0, 6, 1), ('Program management', 0.0, 1.0, 2, 0)]
    d = DESIGN_POOL[cat]
    rows = [('Architecture', 0.0, 0.35, 8, 0), (d, 0.15, 0.8, 26, 0), ('Verification', 0.3, 1.0, 34, 0), ('Physical design', 0.55, 1.0, 12, 0),
            ('Performance modelling', 0.0, 0.6, 5, 0), ('Software & tools', 0.5, 1.0, 10, 3), ('Program management', 0.0, 1.0, 3, 0)]
    if cat == 'Compute subsystem':
        rows = [(p, a, b, f * (1.6 if p == 'Physical design' else 0.6 if p == d else 1.0), x) for p, a, b, f, x in rows]
        rows.append(('Silicon & test', 0.8, 1.0, 4, 2))
    return rows


def _gates(pid, start, launch, as_of):
    n = max(6, _span(start, launch))
    plan = [('G0 Concept', -4), ('G1 Plan approval', 0), ('G2 Development commit', round(n * 0.25)), ('G3 Alpha', round(n * 0.55)),
            ('G4 Beta', round(n * 0.8)), ('G5 Release', n)]
    out = []
    for g, k in plan:
        d = f'{_m(start, k)}-15'
        out.append({'ProjectID': pid, 'Gate': g, 'Planned': d, 'Forecast': None, 'Status': 'Passed' if d < as_of else 'Planned',
                    'Readiness': 100 if d < as_of else None, 'Decided': d if d < as_of else None, 'Notes': None})
    return out


def build(as_of='2026-11-10'):
    t = {}
    proj = []
    for r in PROJECTS:
        (pid, name, bu, cat, stage, fund, st, la, own, conf, val, fit, dem, tc, risk, size, jk, sku, note) = r
        proj.append(dict(ProjectID=pid, Name=name, BU=bu, Category=cat, Stage=stage, Funding=fund, Start=st, Launch=la, Owner=own,
                         Confidence=conf, ValueUSDm=val, StrategicFit=fit, CustomerDemand=dem, TimeCriticality=tc, TechRisk=risk,
                         JiraKey=jk, LinkedSKU=sku, Notes=note))
    t['pf_projects'] = proj
    t['pf_pools'] = [dict(Pool=p, FTE=f, TargetUtilPct=u, CostPerFTEk=c, Countries=s, AttritionPct=a, HiringLeadMonths=l)
                     for p, f, u, c, s, a, l in POOLS]
    t['pf_ramp'] = [
        dict(Type='Permanent hire', StartFactor=0.5, RampMonths=6, SteadyFactor=1.0, CostPremiumPct=0,
             Notes='Learns the design flow, tools and codebase; full output after about six months.'),
        dict(Type='Contractor', StartFactor=0.5, RampMonths=3, SteadyFactor=0.9, CostPremiumPct=35,
             Notes='Experienced but new to our flow; usually kept on well-scoped tasks.'),
        dict(Type='Partner', StartFactor=0.6, RampMonths=2, SteadyFactor=0.85, CostPremiumPct=20,
             Notes='Design-services team working to a statement of work.'),
        dict(Type='Transfer', StartFactor=0.7, RampMonths=3, SteadyFactor=1.0, CostPremiumPct=0,
             Notes='Internal move: knows the tools, new to the project.'),
    ]
    t['pf_levers'] = [
        dict(LeverID='L-01', Lever='Structured onboarding with a named buddy and a 30-60-90 plan', Pool='Verification', From='2026-12',
             Effect='Shorter ramp (months)', Value=2, CostUSDk=60, Status='Approved', Owner='Verification director',
             Notes='First task scoped in week 1; buddy spends 20% of time for 8 weeks.'),
        dict(LeverID='L-02', Lever='Reusable verification environment and testbench library', Pool='Verification', From='2027-02',
             Effect='Productivity uplift %', Value=5, CostUSDk=180, Status='Planned', Owner='Verification methodology lead', Notes=None),
        dict(LeverID='L-03', Lever='Pre-start access and a knowledge pack for contractors and new hires', Pool='All', From='2026-12',
             Effect='Higher start factor', Value=0.15, CostUSDk=40, Status='Approved', Owner='Engineering operations',
             Notes='Accounts, tools, licences and design documents ready on day one.'),
        dict(LeverID='L-04', Lever='One project per engineer: no splits below 0.5 FTE', Pool='CPU design', From='2027-01',
             Effect='Productivity uplift %', Value=4, CostUSDk=0, Status='Planned', Owner='CPU design director',
             Notes='Context switching between projects costs output.'),
        dict(LeverID='L-05', Lever='Regression and implementation-flow automation', Pool='Physical design', From='2027-03',
             Effect='Productivity uplift %', Value=6, CostUSDk=250, Status='Idea', Owner='Implementation lead', Notes=None),
        dict(LeverID='L-06', Lever='Design-flow certification for new physical design engineers', Pool='Physical design', From='2027-01',
             Effect='Shorter ramp (months)', Value=1, CostUSDk=30, Status='Approved', Owner='Implementation lead', Notes=None),
        dict(LeverID='L-07', Lever='Shared IP documentation and design-review checklists', Pool='All', From='2027-04',
             Effect='Productivity uplift %', Value=2, CostUSDk=90, Status='Planned', Owner='Engineering operations', Notes=None),
    ]
    t['pf_key_roles'] = [
        dict(RoleID='K-01', Role='Coherency architect', Pool='Architecture', ProjectID='PF-08', Holders=1, Backups=0, Country='US', Notes=None),
        dict(RoleID='K-02', Role='Memory-tagging verification lead', Pool='Verification', ProjectID='PF-01', Holders=1, Backups=0, Country='India', Notes=None),
        dict(RoleID='K-03', Role='Functional-safety manager', Pool='Program management', ProjectID='PF-06', Holders=1, Backups=1, Country='US', Notes=None),
        dict(RoleID='K-04', Role='Test-chip package engineer', Pool='Silicon & test', ProjectID='PF-11', Holders=1, Backups=0, Country='Taiwan', Notes=None),
        dict(RoleID='K-05', Role='Shader architect', Pool='GPU & ML design', ProjectID='PF-04', Holders=2, Backups=1, Country='Canada', Notes=None),
        dict(RoleID='K-06', Role='Implementation methodology lead', Pool='Physical design', ProjectID=None, Holders=1, Backups=1, Country='India', Notes=None),
        dict(RoleID='K-07', Role='Compiler back-end lead', Pool='Software & tools', ProjectID='PF-10', Holders=1, Backups=0, Country='Canada', Notes=None),
        dict(RoleID='K-08', Role='Performance model owner', Pool='Performance modelling', ProjectID='PF-02', Holders=1, Backups=0, Country='US', Notes=None),
    ]
    t['pf_capacity_changes'] = [
        dict(Pool='Verification', Month='2027-03', DeltaFTE=8, Reason='Hiring plan'),
        dict(Pool='Physical design', Month='2027-04', DeltaFTE=6, Reason='Hiring plan'),
        dict(Pool='GPU & ML design', Month='2027-01', DeltaFTE=-4, Reason='Attrition'),
        dict(Pool='Software & tools', Month='2027-02', DeltaFTE=10, Reason='Partner'),
        dict(Pool='CPU design', Month='2027-07', DeltaFTE=-6, Reason='Transfer'),
    ]
    dem = []
    for r in PROJECTS:
        pid, cat, st, la, size = r[0], r[3], r[6], r[7], r[15]
        if cat == 'CPU IP' and r[4] == 'Sustain':      # sustaining: small flat team across the horizon
            for pool, f in (('CPU design', 6), ('Verification', 8), ('Software & tools', 3), ('Program management', 1)):
                dem.append(dict(ProjectID=pid, Pool=pool, From='2026-01', To='2028-12', FTE=f))
            continue
        n = max(6, _span(st, la))
        for pool, a, b, f, after in _phases(cat):
            fr, to = _m(st, round(n * a)), _m(st, round(n * b) + after)
            dem.append(dict(ProjectID=pid, Pool=pool, From=fr, To=to, FTE=round(f * size, 1)))
    t['pf_demand'] = dem
    gates = []
    for r in PROJECTS:
        if r[4] == 'Sustain':
            continue
        gates += _gates(r[0], r[6], r[7], as_of)
    upd = {  # (project, gate): changes that tell the story
        ('PF-04', 'G3 Alpha'): dict(Forecast='2026-12-15', Notes='Shader core timing closure late; recovery plan agreed.'),
        ('PF-04', 'G4 Beta'): dict(Forecast='2027-07-15'),
        ('PF-04', 'G5 Release'): dict(Forecast='2027-12-15', Notes='Release forecast three months late after the alpha slip.'),
        ('PF-06', 'G3 Alpha'): dict(Forecast='2027-01-29', Readiness=62, Notes='Safety documentation behind plan.'),
        ('PF-02', 'G2 Development commit'): dict(Readiness=78, Notes='Needs the Quartz test-chip plan and verification staffing confirmed.'),
        ('PF-09', 'G2 Development commit'): dict(Readiness=85),
        ('PF-05', 'G1 Plan approval'): dict(Readiness=70, Notes='Business case ready; capacity not yet secured.'),
        ('PF-14', 'G1 Plan approval'): dict(Readiness=90),
        ('PF-13', 'G1 Plan approval'): dict(Readiness=40, Notes='Architecture options still open.'),
        ('PF-03', 'G4 Beta'): dict(Status='Passed', Decided='2026-08-20'),
        ('PF-03', 'G5 Release'): dict(Readiness=88),
        ('PF-08', 'G3 Alpha'): dict(Status='Conditional', Decided='2026-10-20', Readiness=92, Notes='Passed with condition: close two coherency bugs by December.'),
        ('PF-01', 'G4 Beta'): dict(Readiness=55),
        ('PF-11', 'G2 Development commit'): dict(Readiness=80, Notes='Floorplan done; package substrate supplier still in qualification.'),
    }
    for i, g in enumerate(gates):          # readiness for planned gates in the next four months
        if g['Status'] == 'Planned' and g['Planned'] <= '2027-03-15' and g['Readiness'] is None:
            g['Readiness'] = 55 + (i * 17) % 40
    for g in gates:
        u = upd.get((g['ProjectID'], g['Gate']))
        if u:
            g.update(u)
        # proposed projects have not passed their plan approval yet
        if g['ProjectID'] in ('PF-05', 'PF-07', 'PF-12', 'PF-13', 'PF-14', 'PF-15') and g['Gate'] != 'G0 Concept':
            g['Status'] = 'Planned'
            g['Decided'] = None
            if g['Readiness'] == 100:
                g['Readiness'] = None
    t['pf_gates'] = gates
    t['pf_dependencies'] = [
        dict(From='PF-01', To='PF-02', Type='IP delivery', LagMonths=9, Note='Obsidian integrates the Basalt core.'),
        dict(From='PF-08', To='PF-02', Type='IP delivery', LagMonths=6, Note='Obsidian uses the Feldspar mesh.'),
        dict(From='PF-11', To='PF-02', Type='Silicon validation', LagMonths=3, Note='Quartz silicon results before Obsidian release.'),
        dict(From='PF-03', To='PF-05', Type='IP delivery', LagMonths=6, Note=None),
        dict(From='PF-04', To='PF-05', Type='IP delivery', LagMonths=7, Note='Jasper needs a released Topaz.'),
        dict(From='PF-06', To='PF-07', Type='IP delivery', LagMonths=9, Note=None),
        dict(From='PF-10', To='PF-01', Type='Software enablement', LagMonths=0, Note='Compilers ready at Basalt release.'),
        dict(From='PF-14', To='PF-05', Type='Software enablement', LagMonths=-6, Note='Virtual prototype six months before Jasper.'),
        dict(From='PF-13', To='PF-05', Type='Platform', LagMonths=-3, Note='Optional: Jasper premium tier would carry Zircon.'),
    ]
    t['pf_value_weights'] = [
        dict(Criterion='Value', WeightPct=35, Notes='Lifetime value, scaled 1-5 across the portfolio.'),
        dict(Criterion='Strategic fit', WeightPct=20, Notes=None),
        dict(Criterion='Customer demand', WeightPct=20, Notes=None),
        dict(Criterion='Time criticality', WeightPct=15, Notes='Cost of delay.'),
        dict(Criterion='Technical risk', WeightPct=10, Notes='Counts against: 5 = riskiest.'),
    ]
    t['pf_risks'] = [
        dict(RiskID='R-01', ProjectID='PF-04', Type='Issue', Title='Alpha slipped 3 months: release now December 2027', Probability=5, Impact=4,
             Owner='Client GPU lead', Mitigation='Two physical design engineers moved from Mica; weekly timing review', Due='2026-12-15', Status='Mitigating'),
        dict(RiskID='R-02', ProjectID='PF-02', Type='Risk', Title='Verification staffing short in 2027 H1', Probability=4, Impact=5,
             Owner='Verification director', Mitigation='Contractor bid out; scenario "Verification contractors" prepared', Due='2027-01-31', Status='Open'),
        dict(RiskID='R-03', ProjectID='PF-11', Type='Dependency', Title='Test-chip qualification could slip into Obsidian validation', Probability=3, Impact=4,
             Owner='Silicon lead', Mitigation='Pull in engineering lots; check NPI plan for NOVA', Due='2027-02-28', Status='Open'),
        dict(RiskID='R-04', ProjectID='PF-06', Type='Risk', Title='Safety case evidence behind plan for alpha', Probability=3, Impact=3,
             Owner='Auto CPU lead', Mitigation='Safety team priority call', Due='2027-01-15', Status='Open'),
        dict(RiskID='R-05', ProjectID='PF-13', Type='Assumption', Title='Lead partner commits to a 2028 design-in', Probability=3, Impact=5,
             Owner='AI IP lead', Mitigation='Letter of intent targeted before G1', Due='2027-02-15', Status='Open'),
        dict(RiskID='R-06', ProjectID='PF-05', Type='Dependency', Title='Jasper depends on Topaz release, now late', Probability=4, Impact=4,
             Owner='Client CSS lead', Mitigation='Option: start Jasper one quarter later (scenario)', Due='2027-01-31', Status='Open'),
        dict(RiskID='R-07', ProjectID='PF-01', Type='Risk', Title='New memory-tagging feature grows verification scope', Probability=2, Impact=4,
             Owner='Infra CPU lead', Mitigation='Formal verification for the tagging unit', Due='2027-03-31', Status='Mitigating'),
        dict(RiskID='R-08', ProjectID='PF-08', Type='Issue', Title='Two coherency bugs open after alpha', Probability=4, Impact=2,
             Owner='System IP lead', Mitigation='Fix by December (alpha condition)', Due='2026-12-15', Status='Mitigating'),
        dict(RiskID='R-09', ProjectID='PF-15', Type='Risk', Title='Chiplet interface standard still changing', Probability=3, Impact=3,
             Owner='Chiplet lead', Mitigation='Track the standard body; keep Galena at Idea until it settles', Due='2027-06-30', Status='Open'),
        dict(RiskID='R-10', ProjectID='PF-03', Type='Risk', Title='Lead licensee tape-out date moves earlier', Probability=2, Impact=3,
             Owner='Client CPU lead', Mitigation=None, Due=None, Status='Closed'),
    ]
    t['pf_decisions'] = [
        dict(DecisionID='D-101', Date='2026-03-18', Forum='Portfolio Board', ProjectID='PF-01', Gate='G2 Development commit', Decision='Approve',
             Summary='Basalt committed to development; scope frozen at the March feature list.', Owner='Infra CPU lead', ActionDue=None),
        dict(DecisionID='D-102', Date='2026-06-17', Forum='Portfolio Board', ProjectID='PF-02', Gate='G1 Plan approval', Decision='Approve with conditions',
             Summary='Obsidian plan approved; test-chip plan required before development commit.', Owner='Infra CSS lead', ActionDue='2026-11-30'),
        dict(DecisionID='D-103', Date='2026-06-17', Forum='Portfolio Board', ProjectID='PF-11', Gate='G1 Plan approval', Decision='Approve',
             Summary='Quartz test chip funded as an Obsidian enabler.', Owner='Silicon lead', ActionDue=None),
        dict(DecisionID='D-104', Date='2026-08-20', Forum='BU review', ProjectID='PF-03', Gate='G4 Beta', Decision='Approve',
             Summary='Garnet beta release to lead licensees.', Owner='Client CPU lead', ActionDue=None),
        dict(DecisionID='D-105', Date='2026-09-16', Forum='Portfolio Board', ProjectID='PF-12', Gate='-', Decision='Defer',
             Summary='Agate deferred to the next planning cycle: no capacity in 2027 H1.', Owner='Security lead', ActionDue='2027-03-17'),
        dict(DecisionID='D-106', Date='2026-10-20', Forum='BU review', ProjectID='PF-08', Gate='G3 Alpha', Decision='Approve with conditions',
             Summary='Feldspar alpha with two open coherency bugs to close by December.', Owner='System IP lead', ActionDue='2026-12-15'),
        dict(DecisionID='D-107', Date='2026-10-21', Forum='Portfolio Board', ProjectID='PF-04', Gate='G3 Alpha', Decision='Re-scope',
             Summary='Topaz alpha moved to December; ML extensions moved to a later drop.', Owner='Client GPU lead', ActionDue='2026-12-15'),
        dict(DecisionID='D-108', Date='2026-10-21', Forum='Exec staff', ProjectID='PF-13', Gate='-', Decision='Approve with conditions',
             Summary='Zircon concept work continues; business case with partner commitment for G1 in February.', Owner='AI IP lead', ActionDue='2027-02-17'),
    ]
    t['pf_scenarios'] = [
        dict(Scenario='Delay Jasper one quarter', Seq=1, Change='Delay months', ProjectID='PF-05', Pool=None, Month=None, Value=3,
             Note='Start after the Topaz recovery; frees verification in 2027 H1.'),
        dict(Scenario='Verification contractors', Seq=1, Change='Add FTE', ProjectID=None, Pool='Verification', Month='2027-01', Value=20,
             Note='Contractor team for 2027.'),
        dict(Scenario='Verification contractors', Seq=2, Change='Add FTE', ProjectID=None, Pool='Physical design', Month='2027-02', Value=8,
             Note='Implementation partner.'),
        dict(Scenario='Fund Zircon, stop Agate', Seq=1, Change='Fund', ProjectID='PF-13', Pool=None, Month=None, Value=None, Note=None),
        dict(Scenario='Fund Zircon, stop Agate', Seq=2, Change='Stop', ProjectID='PF-12', Pool=None, Month=None, Value=None, Note=None),
        dict(Scenario='Automotive push', Seq=1, Change='Fund', ProjectID='PF-07', Pool=None, Month=None, Value=None, Note=None),
        dict(Scenario='Automotive push', Seq=2, Change='Delay months', ProjectID='PF-15', Pool=None, Month=None, Value=6, Note='Galena waits.'),
        dict(Scenario='Automotive push', Seq=3, Change='Scale demand %', ProjectID='PF-07', Pool=None, Month=None, Value=-15,
             Note='Reuse Onyx verification environment.'),
    ]
    t['pf_jira'] = [
        dict(JiraKey='PYRM-101', Summary='Basalt: server performance core', Status='In Progress', DueDate='2027-06-30', Done=212, InProgress=64, Total=410, Synced='demo'),
        dict(JiraKey='PYRM-102', Summary='Obsidian: cloud compute subsystem', Status='In Progress', DueDate='2028-03-31', Done=18, InProgress=22, Total=260, Synced='demo'),
        dict(JiraKey='PYRM-103', Summary='Garnet: efficiency core', Status='In Progress', DueDate='2027-01-29', Done=341, InProgress=19, Total=372, Synced='demo'),
        dict(JiraKey='PYRM-104', Summary='Topaz: graphics core', Status='At Risk', DueDate='2027-12-17', Done=120, InProgress=58, Total=330, Synced='demo'),
        dict(JiraKey='PYRM-106', Summary='Onyx: safety core', Status='In Progress', DueDate='2027-12-17', Done=96, InProgress=41, Total=290, Synced='demo'),
        dict(JiraKey='PYRM-108', Summary='Feldspar: coherent mesh', Status='In Progress', DueDate='2027-09-30', Done=118, InProgress=26, Total=190, Synced='demo'),
        dict(JiraKey='PYRM-109', Summary='Mica: microcontroller core', Status='In Progress', DueDate='2028-02-28', Done=14, InProgress=11, Total=120, Synced='demo'),
        dict(JiraKey='PYRM-110', Summary='Pyrite: compilers and libraries', Status='In Progress', DueDate='2027-06-30', Done=88, InProgress=30, Total=160, Synced='demo'),
        dict(JiraKey='PYRM-111', Summary='Quartz: Obsidian test chip', Status='In Progress', DueDate='2027-12-17', Done=9, InProgress=14, Total=140, Synced='demo'),
        dict(JiraKey='PYRM-116', Summary='Hematite: sustaining releases', Status='In Progress', DueDate=None, Done=64, InProgress=8, Total=80, Synced='demo'),
    ]
    return t
