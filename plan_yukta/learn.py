"""Learn & practice: role capability map, daily practice drills and the ERM / portfolio glossary.

Talking points and data drills are built from the live portfolio, so they change with the data."""
from __future__ import annotations

from datetime import date
from html import escape

from . import portfolio as PF
from .views import K, callout, col, html, page, table


def _e(v):
    return escape('' if v is None else str(v))


def _ml(m):
    return PF._ml(m)


# ------------------------------------------------------------------ glossary
# term, definition, why it matters, page key
GLOSSARY = [
    ('Strategic portfolio management (SPM)', 'Choosing and steering the set of products, platforms and projects that best delivers strategy within the money and people available.',
     'The umbrella for roadmap, capacity, prioritisation and governance work.', 'pf-overview'),
    ('Enterprise resource management (ERM)', 'Planning, booking and tracking people and skills across the whole organisation rather than project by project.',
     'Stops each programme planning against the same engineers twice.', 'pf-capacity'),
    ('Demand intake', 'The single front door where new work and resource needs are raised in a standard form.',
     'Without it, demand arrives by email and hallway and nothing can be compared.', 'pf-requests'),
    ('Resource request', 'A formal ask for a number of FTE from a skill pool, for a project, over a time window, with priority and justification.',
     'The unit of work for the resource review.', 'pf-requests'),
    ('Soft booking', 'A tentative hold on capacity, visible to planners but not counted as committed.',
     'Lets you protect capacity for work awaiting a gate without locking it.', 'pf-requests'),
    ('Hard booking', 'A committed allocation of capacity to a project; it counts against the pool.',
     'The point at which capacity is really spent.', 'pf-requests'),
    ('Allocation', 'Assigning FTE from a pool (or named people) to a project over time.', 'Allocations add up to demand on a pool.', 'pf-capacity'),
    ('Generic vs named resources', 'Planning by role or skill ("2 verification FTE") versus by person ("Priya").',
     'Long-range plans use generic roles; near-term delivery uses named people.', 'pf-capacity'),
    ('Skill pool', 'A group of interchangeable engineers sharing a skill set, planned as one capacity.', 'Capacity is planned by pool, not by department.', 'pf-capacity'),
    ('FTE (full-time equivalent)', 'Work measured in units of one person working full time; 0.5 FTE is half a person\'s time.', 'The common currency of capacity planning.', 'pf-fte'),
    ('Effective FTE', 'Output-adjusted capacity: new joiners count below 1.0 while they ramp up; levers lift it.', 'Headcount is not capacity.', 'pf-fte'),
    ('Ramp-up', 'The months a new person takes to reach full output, often from about 0.5 to 1.0 FTE.', 'Hiring late means paying for capacity you cannot use yet.', 'pf-fte'),
    ('Headcount vs FTE', 'Headcount counts employees on the books; FTE counts all available effort, including contractors and partners.',
     'Budgets cap headcount; plans need FTE.', 'pf-fte'),
    ('Capacity', 'The FTE a pool can deliver in a month, after ramp-up and productivity.', 'The supply side of every plan.', 'pf-capacity'),
    ('Demand', 'The FTE that committed and proposed work needs from each pool per month.', 'The other side of the balance.', 'pf-capacity'),
    ('Utilisation', 'Demand ÷ capacity. Planned to a target (often 85-92%) to leave room for support, leave and surprises.', 'Above target = overload and slips.', 'pf-capacity'),
    ('Target utilisation', 'The share of capacity planned for project work.', 'Sets the line between healthy and overloaded.', 'pf-capacity'),
    ('Capacity heatmap', 'Pools × periods coloured by utilisation.', 'Shows bottlenecks at a glance for executives.', 'pf-overview'),
    ('Time-phased plan', 'Demand and capacity by month or quarter, not as one total.', 'Peaks hide inside annual totals.', 'pf-capacity'),
    ('Capacity ask', 'The extra FTE needed by pool and quarter to keep committed work at target.', 'The resource request to the board, costed.', 'pf-capacity'),
    ('Value-based prioritisation', 'Ranking work by a weighted score of value, strategic fit, customer demand, time criticality and risk.',
     'Moves debate from opinion to agreed criteria.', 'pf-priority'),
    ('Cost of delay', 'The value lost for each month a project is late; captured here as time criticality.', 'Drives sequencing, not just selection.', 'pf-priority'),
    ('WSJF', 'Weighted shortest job first: cost of delay ÷ job size. A common way to order work.', 'Favours high-value, small, urgent items.', 'pf-priority'),
    ('Funding line', 'The cut-off in a ranked list: what fits within capacity is funded, the rest waits.', 'Turns a ranking into a decision.', 'pf-priority'),
    ('Portfolio balance', 'The mix of investment across horizons, themes or BUs against targets.', 'Prevents all capacity going to today\'s products.', 'pf-governance'),
    ('Three horizons (H1/H2/H3)', 'H1 core business, H2 adjacent growth, H3 emerging bets.', 'A simple language for balance targets.', 'pf-governance'),
    ('Scenario planning (what-if)', 'Testing changes to timing, staffing, funding or demand against the baseline before deciding.', 'Shows trade-offs with numbers.', 'pf-scenarios'),
    ('Baseline', 'The approved plan against which change and progress are measured.', 'Without it there is no variance.', 'pf-scenarios'),
    ('Trade-off', 'Choosing one outcome at the cost of another (delay A to fund B).', 'The core of every board conversation.', 'pf-scenarios'),
    ('Roadmap', 'A time-based view of what will be delivered, when, and why, at agreed confidence.', 'The shared picture BUs, engineering and customers plan from.', 'pf-roadmap'),
    ('Roadmap standards', 'Agreed rules a roadmap entry must meet (owner, dates, value case, dependencies, confidence).', 'Makes roadmaps comparable and decision-ready.', 'pf-governance'),
    ('Decision-ready', 'An item with enough quality data for a forum to decide on it.', 'The bar for anything going to the board.', 'pf-governance'),
    ('Now / Next / Later', 'A roadmap convention: committed now, planned next, exploratory later, with falling confidence.', 'Honest about certainty.', 'pf-roadmap'),
    ('Dependency', 'Something one project needs from another (IP, platform, silicon, software).', 'Cross-BU roadmaps fail at dependencies.', 'pf-raid'),
    ('Critical path', 'The chain of dependent work that sets the earliest release date.', 'Where a slip moves the end date.', 'pf-roadmap'),
    ('Stage gate', 'A decision point between lifecycle phases (concept, plan, develop, alpha, beta, release).', 'Where the portfolio is steered.', 'pf-board'),
    ('Readiness review', 'Checking that a project meets the gate criteria before the decision.', 'Prevents approving on hope.', 'pf-board'),
    ('Portfolio Board', 'The executive forum that approves, funds, defers or stops work.', 'Where the function\'s recommendations land.', 'pf-board'),
    ('RAID log', 'Risks, assumptions, issues and dependencies, scored and owned.', 'The early-warning system.', 'pf-raid'),
    ('Operating model', 'How the planning function works: process, forums, roles, data and tools.', 'What you build in the first 100 days.', 'pf-governance'),
    ('Planning cadence', 'The rhythm of reviews: weekly resources, monthly portfolio, quarterly board, annual plan.', 'Makes planning a habit, not an event.', 'pf-governance'),
    ('RACI', 'Who is Responsible, Accountable, Consulted and Informed for each decision.', 'Clear decision rights speed decisions.', 'pf-governance'),
    ('Run / grow / transform', 'Splitting effort between keeping products running, growing them and new bets.', 'Another lens on balance.', 'pf-governance'),
    ('Attrition drag', 'Capacity always missing because leavers are replaced only after hiring lead time and ramp-up.', 'Plans that ignore it are optimistic.', 'pf-wfrisk'),
    ('Key-person risk', 'Knowledge held by one person with no trained backup.', 'One resignation can stop a project.', 'pf-wfrisk'),
    ('Stress test', 'Running the plan under shocks (attrition, freeze, site loss) to see what breaks.', 'Shows resilience before it is needed.', 'pf-wfrisk'),
    ('Executive narrative (SCQA)', 'Situation, Complication, Question, Answer: a structure for board papers and briefings.', 'Gets to the decision in two minutes.', 'pf-board'),
    ('Planning KPIs', 'Measures of the planning function itself: decision-readiness, predictability, utilisation, cycle time.', 'Shows the function adds value.', 'pf-governance'),
    ('AI-enabled planning', 'Generated insights, narratives and anomaly flags from portfolio data, plus a planning assistant.', 'Scales a small team.', 'pf-overview'),
]


# ------------------------------------------------------------------ question bank: (theme, question, framework, outline)
QUESTIONS = [
    ('Vision & operating model', 'What would you do in your first 90 days to build the roadmap and capacity function?', 'Listen → Baseline → Design → Pilot',
     ['Days 1-30: meet BU leads, engineering, finance; map current forums, tools and data; find the three biggest pains.',
      'Days 31-60: one data model for demand and capacity; roadmap standards draft; weekly resource review started.',
      'Days 61-90: first capacity heatmap and funding line at the Portfolio Board; agree KPIs; quick wins public.',
      'Show the operating model page: intake → evaluation → decision → tracking → learning.']),
    ('Vision & operating model', 'How do you balance agility with structure in planning?', 'Principle → Mechanism → Example',
     ['Structure where decisions are expensive (gates, hard bookings, board); light touch where change is cheap (soft bookings, Next/Later).',
      'Fixed cadence, flexible content: weekly bookings can move; quarterly baseline is stable.',
      'Example: soft-book capacity for a proposal before its gate instead of committing early.']),
    ('Team leadership', 'How would you build and develop a small team covering roadmap, governance, capacity and delivery planning?', 'Roles → Skills → Rituals → Growth',
     ['One owner each for roadmap standards, capacity and resource review, governance and board papers, delivery tracking.',
      'Shared data model so anyone can cover any forum; rotate board-paper writing.',
      'Measure the team on planning KPIs, not activity.']),
    ('Roadmap governance', 'What makes a roadmap decision-ready?', 'Standard → Check → Consequence',
     ['Owner, value case, confidence, dated gates, resource demand, dependencies, risks, delivery link.',
      'Score each entry; below the bar it does not go to the board.',
      'Point to the standards score on the governance page.']),
    ('Capacity planning', 'Verification is over target next quarter. Walk me through your options.', 'Recommendation → Options → Trade-offs → Ask',
     ['Quantify: how many FTE over, which months, which projects drive it.',
      'Options: contractors or partner now; re-phase a proposed project; scale scope; permanent hiring for the lasting need.',
      'Trade-offs: cost premium and ramp-up vs delay and value at risk.',
      'Ask: approve contractors for the peak and requisitions for the base.']),
    ('Capacity planning', 'How do you plan capacity when new hires take months to become productive?', 'Concept → Number → Lever',
     ['Plan effective FTE, not headcount: ramp curves by type.',
      'Each permanent hire loses about 1.75 FTE-months of output; onboarding levers halve it.',
      'Open requisitions before the need: lead time + months to 80% output.']),
    ('Prioritisation', 'Two BUs want the same engineers. How do you decide?', 'Criteria → Data → Forum',
     ['Agreed value criteria and weights, set in advance, not per case.',
      'Score both, check the funding line and dependencies, show the scenario of each choice.',
      'Recommend; let the Portfolio Board decide; record and communicate.']),
    ('Prioritisation', 'How do you stop prioritisation becoming political?', 'Transparency → Consistency → Escalation',
     ['Publish criteria, weights and scores; same rules for every BU.',
      'Separate the scoring from the decision; challenge the inputs, not the outcome.',
      'Clear escalation path with a recommendation attached.']),
    ('Scenario planning', 'Tell me about a time you used scenarios to change a decision.', 'STAR',
     ['Situation and task: the decision and what was at stake.',
      'Action: built baseline and two or three scenarios with numbers (capacity, dates, cost).',
      'Result: what was decided and the measurable outcome.']),
    ('Lifecycle & readiness', 'How do you run a readiness review that is not a box-ticking exercise?', 'Criteria → Evidence → Recommendation',
     ['Criteria tied to the next phase\'s risks; evidence, not assertions.',
      'Recommendation with conditions and owners; follow up conditions at the next review.']),
    ('Executive influence', 'How do you present a recommendation the executives may not like?', 'SCQA',
     ['Situation in one line; complication with numbers; the question; the answer first.',
      'Show the alternatives you rejected and why; be clear on the ask and the cost of not deciding.']),
    ('Executive influence', 'Tell me about influencing a senior leader without authority.', 'STAR',
     ['Pick a cross-functional example (engineering, finance, commercial or manufacturing).',
      'Show how data and a shared goal changed the outcome; quantify it.']),
    ('Data & tools', 'What would you look for in an ERM or SPM platform?', 'Needs → Data → Adoption',
     ['One data model for demand, capacity, roadmap and finance; time-phased by skill.',
      'Scenarios, soft/hard booking, integrations with delivery tools and finance.',
      'Adoption: simple intake, role-based views, the board uses it live.']),
    ('Data & tools', 'How would you use AI in portfolio planning?', 'Use case → Guardrail → Value',
     ['Generated narratives and insights from portfolio data; anomaly flags on slips and overloads; an assistant for planners.',
      'Guardrails: humans decide; sources shown; data quality first.',
      'Value: a small team covers more forums with better papers.']),
    ('Semiconductor context', 'What is different about capacity planning in a processor IP and silicon business?', 'Context → Constraint → Practice',
     ['Long design cycles, scarce skills (verification, physical design), dependencies between IP, subsystems and test chips.',
      'Silicon adds external lead times (foundry, packaging, test) to roadmap dates.',
      'So: skill-based capacity, dependency-aware roadmaps, and a link from roadmap to silicon supply.']),
    ('Business judgement', 'How do you connect roadmap demand, capacity, investment and product outcomes in one decision?', 'Chain → Number → Decision',
     ['Demand (roadmap) → capacity (FTE by pool) → cost → value and timing → outcome.',
      'Show the funding line: what $M of value fits and what waits.',
      'Decide with the trade-off in view.']),
]

ROLE = [  # (responsibility, ERM practice, page key, evidence fn, talking-point fn, practice question)
    ('Lead roadmap and capacity planning frameworks: vision, operating model, governance, execution rhythm',
     'Operating model; planning cadence; RACI', 'pf-governance',
     lambda pf, k, q: f'{len(q)} roadmap entries scored; cadence of 6 forums',
     lambda pf, k, q: 'I run planning as an operating model, not a spreadsheet: one front door for demand, a weekly resource review, a monthly portfolio and '
                      'capacity review, a quarterly Portfolio Board, each with clear decision rights.',
     'What would your planning cadence look like?'),
    ('Run and develop a small team: roadmap, portfolio governance, capacity, delivery planning',
     'Planning function roles and KPIs', 'pf-governance',
     lambda pf, k, q: f'{sum(1 for r in q if r["status"] == "Decision-ready")}/{len(q)} decision-ready',
     lambda pf, k, q: 'Each team member owns a forum and a KPI: roadmap decision-readiness, capacity utilisation, request cycle time, gate predictability.',
     'How would you structure and grow the team?'),
    ('Mature enterprise portfolio and roadmap capabilities with the Head of Portfolio',
     'Capability maturity; roadmap standards', 'pf-governance',
     lambda pf, k, q: f'average standards score {sum(r["score"] for r in q) / max(1, len(q)):.0f}%',
     lambda pf, k, q: f'Today {sum(1 for r in q if r["status"] == "Decision-ready")} of {len(q)} roadmap entries meet the standard; the gaps are owners, risk logs and '
                      'dependency conflicts. Raising that score is a measurable maturity goal.',
     'How do you measure planning maturity?'),
    ('Roadmaps standards-led, high quality, decision-ready, used in decisions', 'Roadmap standards; decision-ready score', 'pf-roadmap',
     lambda pf, k, q: f'{k["dep_conflicts"]} dependency conflict(s), {k["slipping"]} slipping release(s)',
     lambda pf, k, q: 'Every roadmap entry carries an owner, dated gates, a value case, confidence, dependencies and a delivery link, so the same roadmap drives '
                      'investment, lifecycle and delivery decisions.',
     'What makes a roadmap decision-ready?'),
    ('Coordination model for how resources are planned, reviewed, prioritised and raised', 'Demand intake; soft and hard booking; resource review',
     'pf-requests', lambda pf, k, q: f'{sum(1 for r, _ in pf.req_rows if r["Status"] in ("Submitted", "Draft", "Soft-booked"))} open requests',
     lambda pf, k, q: 'Requests come through one front door; the weekly review hard-books what fits, soft-books what waits for a gate, and escalates '
                      'critical requests that do not fit with the trade-off already costed.',
     'Walk me through how a resource request is handled.'),
    ('Resource prioritisation frameworks linking capacity to value, impact, risk and outcomes', 'Value-based prioritisation; funding line', 'pf-priority',
     lambda pf, k, q: f'${k["value_fundable"]:,.0f}M fundable, ${k["value_above"]:,.0f}M above the line',
     lambda pf, k, q: 'Projects are scored on value, fit, customer demand, cost of delay and risk; the funding line then places each proposal at the earliest '
                      'start capacity allows, so priority turns into a date, not just a rank.',
     'Two BUs want the same engineers. How do you decide?'),
    ('Roadmap and capacity scenario planning across demand, staffing, timing, dependencies and trade-offs', 'What-if scenarios; baseline comparison',
     'pf-scenarios', lambda pf, k, q: f'{k["overload_fte_m"]:.0f} FTE-months over target in the baseline',
     lambda pf, k, q: f'The baseline is {k["overload_fte_m"]:.0f} FTE-months over target. I test contractors, re-phasing and stopping lower-value work side by side and '
                      'bring the board the option with the best value at acceptable risk.',
     'Tell me about a time scenarios changed a decision.'),
    ('Product and solution approval and readiness across the lifecycle', 'Stage gates; readiness review', 'pf-board',
     lambda pf, k, q: f'{len(pf.upcoming_gates(120))} gates due in 120 days',
     lambda pf, k, q: 'Each gate gets a recommendation from readiness, capacity, risk and dependencies; conditions have owners and dates and are followed up.',
     'How do you run a readiness review well?'),
    ('Partner with BUs on strong proposals for executives and the Portfolio Board', 'Board pack; SCQA narrative', 'pf-board',
     lambda pf, k, q: 'Board pack in Excel and Confluence',
     lambda pf, k, q: 'I help BUs frame proposals as a decision: situation, complication, question, answer, with the capacity and value consequences already worked out.',
     'How do you help a BU build a strong proposal?'),
    ('Influence senior collaborators across BUs, Engineering, Finance, Commercial, Manufacturing', 'Integrated plan; roadmap to silicon', 'pf-roadmap',
     lambda pf, k, q: 'Roadmap linked to the supply plan',
     lambda pf, k, q: 'I bring every function to one set of numbers: engineering capacity, cost for finance, value for commercial, and silicon lead times for '
                      'manufacturing. That shared picture is what wins agreement.',
     'Tell me about influencing without authority.'),
    ('Build the function: agility with structure, shared ownership, data and tools, constructive challenge', 'Planning KPIs; tooling; AI insights',
     'pf-overview', lambda pf, k, q: 'Executive summary generated from data',
     lambda pf, k, q: 'Structure where decisions are expensive, flexibility where change is cheap; data and tools so a small team scales; open scoring so people challenge inputs, not motives.',
     'How do you balance agility with structure?'),
    ('Skill: ERM tools, capacity processes, value-led prioritisation', 'ERM vocabulary', 'learn-glossary',
     lambda pf, k, q: f'{len(GLOSSARY)} terms', lambda pf, k, q: 'Demand intake, soft and hard booking, skill-based capacity, effective FTE, funding line, scenarios: I use them daily.',
     'What would you look for in an ERM or SPM platform?'),
    ('Skill: connect demand, constraints, investment, lifecycle readiness and outcomes', 'Funding line; balance; gates', 'pf-priority',
     lambda pf, k, q: f'capacity used {k["util12"]:.0f}% next 12 months', lambda pf, k, q: 'Demand becomes FTE, FTE becomes cost and dates, dates become value and outcomes: that chain is the decision.',
     'How do you connect roadmap demand to product outcomes?'),
    ('Skill: semiconductor industry and processor product range', 'Roadmap to silicon', 'pf-roadmap',
     lambda pf, k, q: 'IP, subsystems, test chip linked to NPI dates', lambda pf, k, q: 'A processor roadmap runs from IP to subsystems to test silicon; I plan the people and the silicon lead times together.',
     'What is different about capacity planning in an IP and silicon business?'),
    ('Nice to have: SoC / engineering background; connecting finance, delivery, commercial and manufacturing data', 'Integrated decision framework',
     'pf-overview', lambda pf, k, q: 'Supply-chain planning + portfolio planning in one tool',
     lambda pf, k, q: 'My background is in semiconductor operations and NPI, so I can connect engineering capacity with manufacturing capacity, which most portfolio planners cannot.',
     'What do you bring that others do not?'),
]


def role_map(R, args, ws):
    pf = PF.Portfolio(ws)
    k = pf.kpis()
    q = PF.roadmap_quality(pf)
    rows = []
    for resp, practice, key, ev, tp, ques in ROLE:
        try:
            evidence = ev(pf, k, q)
            talk = tp(pf, k, q)
        except Exception:                       # never break the page on odd data
            evidence, talk = '–', ''
        rows.append({'resp': resp, 'practice': practice, 'where': key, 'link': f'/m/{key}', 'evidence': evidence, 'talk': talk, 'ques': ques})
    sections = [{'type': 'kpis', 'items': [
        K('Responsibilities and skills mapped', str(len(rows)), 'each with a page, live evidence and a talking point'),
        K('ERM terms', str(len(GLOSSARY)), 'in the glossary'),
        K('Practice questions', str(len(QUESTIONS)), 'plus live data drills'),
        K('Today\'s drill', 'Daily Practice', 'a new set every day', 'ok'),
    ]}]
    sections.append(callout('How to use it: read a row, open the page, look at the live number, then say the talking point aloud in under 60 seconds. '
                            'Change data or run a scenario and the talking points change with it.', 'info'))
    sections.append(table('Capability map', [col('resp', 'Responsibility / skill'), col('practice', 'ERM practice'), col('where', 'Show it on', 'link'),
                                             col('evidence', 'Live evidence'), col('talk', '60-second talking point'), col('ques', 'Practise answering')], rows))
    return page('learn-role', sections)


# ------------------------------------------------------------------ data drills built from the live plan
def drills(pf, ws):
    out = []
    k = pf.kpis()
    ov = sorted(pf.overloads(pf.load_committed), key=lambda x: -x[2])
    if ov:
        pool, i, x = ov[0]
        out.append(('Capacity', f'{pool} is {x:.0f} FTE over target in {_ml(pf.months[i])} on committed work. The BU asks for more people. What do you recommend?',
                    ['Size it: which months, how many FTE, which projects drive it (Capacity vs Demand).',
                     'Check timing: can permanent hires arrive and ramp in time? (FTE Ramp & Productivity → hire vs contract).',
                     'Options with numbers: contractors now; re-phase a proposed project (Scenario Planner); scope.',
                     'Ask: approve contractors for the peak, requisitions for the lasting need.']))
    ev = [r for r in PF.evaluate_requests(pf) if r['rec'] == 'Escalate']
    if ev:
        r = ev[0]
        out.append(('Resource review', f'Request {r["RequestID"]}: {r["FTE"]:.0f} {r["Pool"]} FTE for {r["project"]} ({r["Priority"]}). It does not fit. Present it to the board.',
                    [f'State the gap: {r["over"]:.1f} FTE over target in {_ml(r["over_month"])}.', 'Give two or three options and their impact on other projects.',
                     'Recommend one, with cost and risk; say what happens if the board does not decide.']))
    slip = sorted([p for p in pf.projects.values() if p['launch_slip'] > 0], key=lambda p: -p['launch_slip'])
    if slip:
        p = slip[0]
        out.append(('Roadmap', f'{p["Name"]} is forecast {p["launch_slip"]} months late. Explain the impact and your plan in 60 seconds.',
                    ['Impact on dependent projects and customers (Roadmap → dependencies).', 'Recovery options and their cost.',
                     'Decision needed and by when.']))
    prop = sorted([p for p in pf.projects.values() if p['Funding'] == 'Proposed'], key=lambda p: -p['score'])
    if prop:
        p = prop[0]
        out.append(('Funding line', f'{p["Name"]} scores {p["score"]:.0f} with ${p["ValueUSDm"]:,.0f}M value but {str(p.get("funding_result", "")).lower()}. Make the case.',
                    ['Why it ranks high (criteria).', 'What it costs in FTE and $M.', 'What must move to start it earlier, and the trade-off.']))
    bal = PF.balance(pf)
    off = [b for b in bal if b['target'] is not None and abs(b['gap']) >= 5]
    if off:
        b = off[0]
        out.append(('Balance', f'{b["h"]} is {b["actual"]:.0f}% of effort against a {b["target"]:.0f}% target. Does it matter, and what would you change?',
                    ['Why the target exists (risk of an empty future pipeline or a neglected core).', 'Which projects move the mix.',
                     'Recommend gradually, through the funding line, not by cancelling work.']))
    q = [r for r in PF.roadmap_quality(pf) if r['status'] != 'Decision-ready']
    if q:
        r = q[0]
        out.append(('Standards', f'{r["name"]} is "{r["status"]}" ({r["score"]:.0f}%): {", ".join(r["missing"])}. What do you do before the board?',
                    ['Send it back with specific gaps and an owner.', 'Explain why standards protect the board\'s time.', 'Offer help to close the gaps quickly.']))
    b = PF.exec_brief(pf)
    out.append(('Executive narrative', 'Give the two-minute portfolio update to the executive team.',
                [f'Situation: {b["S"]}', f'Complication: {b["C"]}', f'Question: {b["Q"]}', f'Answer: {b["A"]}']))
    return out


def daily(R, args, ws):
    pf = PF.Portfolio(ws)
    today = pf.as_of if args.get('use') == 'plan' else date.today()
    try:
        offset = int(args.get('day') or 0)
    except ValueError:
        offset = 0
    n = today.toordinal() + offset
    concept = GLOSSARY[n % len(GLOSSARY)]
    lead = QUESTIONS[n % len(QUESTIONS)]
    dr = drills(pf, ws)
    drill = dr[n % len(dr)] if dr else None
    narrative = dr[-1] if dr else None
    key = (date.fromordinal(n)).isoformat()
    cards = []

    def card(i, kind, title, body, outline, link=None, framework=None):
        ol = ''.join(f'<li>{_e(x)}</li>' for x in outline)
        return (f'<section class="panel practice" data-item="{i}"><div class="panel-head"><h2>{_e(kind)}</h2>'
                f'{"<span class=badge>" + _e(framework) + "</span>" if framework else ""}</div>'
                f'<p class="pq">{_e(title)}</p>{body}'
                f'<details><summary class="btn ghost sm">Show a model answer outline</summary><ol class="exec">{ol}</ol>'
                f'{"<p class=small><a href=" + chr(34) + link + chr(34) + ">See it in Plan Yukta</a></p>" if link else ""}</details>'
                f'<div class="actions" style="margin-top:10px"><button class="btn ghost sm" type="button" data-timer>Start 60-second answer</button>'
                f'<span class="muted small" data-left></span><span class="rate">How did it go? '
                f'<button class="chip" type="button" data-rate="1">Shaky</button><button class="chip" type="button" data-rate="2">OK</button>'
                f'<button class="chip" type="button" data-rate="3">Strong</button></span></div></section>')

    cards.append(card(1, 'Concept of the day', concept[0], f'<p>{_e(concept[1])}</p><p class="muted small">Why it matters: {_e(concept[2])}</p>'
                      f'<p class="small">Practise: use "{_e(concept[0])}" in one sentence about this portfolio.</p>',
                      [f'Definition: {concept[1]}', f'Why: {concept[2]}', 'Example: tie it to a number on the linked page.'], f'/m/{concept[3]}'))
    if drill:
        cards.append(card(2, f'Data drill · {drill[0]}', drill[1], '<p class="muted small">Built from today\'s plan data.</p>', drill[2], None,
                          'Recommendation → Options → Trade-offs → Ask'))
    cards.append(card(3, f'Leadership question · {lead[0]}', lead[1], '', lead[3], None, lead[2]))
    if narrative:
        cards.append(card(4, 'Executive narrative', narrative[1], '<p class="muted small">Answer first, then the evidence. Two minutes.</p>', narrative[2], '/m/pf-board', 'SCQA'))
    plan = [
        ('Week 1', 'Language and the model', 'Glossary 5 terms a day; walk Portfolio Overview, Capacity vs Demand, FTE Ramp & Productivity.'),
        ('Week 2', 'Prioritisation and scenarios', 'Funding line, value weights, three scenarios; explain each in 60 seconds.'),
        ('Week 3', 'Governance and the board', 'Operating model, RACI, standards, gates; write one SCQA board brief.'),
        ('Week 4', 'Mock interviews', 'Capability map rows aloud; record yourself; two STAR stories per responsibility.'),
    ]
    script = """
<script>
(function(){
  var KEY='py_practice_v1', day=%s;
  function load(){ try { return JSON.parse(localStorage.getItem(KEY)||'{}'); } catch(e){ return {}; } }
  function save(d){ try { localStorage.setItem(KEY, JSON.stringify(d)); } catch(e){} }
  function streak(d){ var s=0, t=new Date(); for(var i=0;i<400;i++){ var k=new Date(t.getTime()-i*864e5).toISOString().slice(0,10);
      if(d[k] && Object.keys(d[k]).length){ s++; } else if(i>0){ break; } } return s; }
  function paint(){ var d=load(), today=d[day]||{};
    document.querySelectorAll('.practice').forEach(function(c){ var i=c.dataset.item;
      c.querySelectorAll('[data-rate]').forEach(function(b){ b.classList.toggle('on', String(today[i])===b.dataset.rate); }); });
    var done=Object.keys(today).length, el=document.getElementById('py-streak');
    if(el){ el.textContent = streak(d)+' day streak · '+done+' of '+document.querySelectorAll('.practice').length+' done today · '+Object.keys(d).length+' days practised'; } }
  document.addEventListener('click', function(e){
    var r=e.target.closest('[data-rate]'); if(r){ var c=r.closest('.practice'), d=load(); d[day]=d[day]||{}; d[day][c.dataset.item]=+r.dataset.rate; save(d); paint(); }
    var t=e.target.closest('[data-timer]'); if(t){ var c2=t.closest('.practice'), out=c2.querySelector('[data-left]'), left=60; t.disabled=true;
      var iv=setInterval(function(){ left--; out.textContent=left+'s'; if(left<=0){ clearInterval(iv); out.textContent='Time. Rate yourself.'; t.disabled=false; } },1000); out.textContent='60s'; }
  });
  paint();
})();
</script>""" % (repr(key).replace("'", '"'))
    sections = [html(f'<section class="panel insights"><div class="panel-head"><h2>Practice for {date.fromordinal(n):%A %d %B %Y}</h2>'
                     f'<div class="chips"><a class="chip" href="?day={offset - 1}">◀ Previous day</a><a class="chip" href="?day=0">Today</a>'
                     f'<a class="chip" href="?day={offset + 1}">Next day ▶</a></div></div>'
                     f'<p id="py-streak" class="small"></p><p class="muted small">Four items, about 15 minutes. Say each answer aloud with the timer, then rate yourself. '
                     f'Your streak stays in this browser.</p></section>')]
    sections += [html(c) for c in cards]
    sections.append(table('30-day plan', [col('w', 'When'), col('t', 'Theme'), col('d', 'Daily routine')],
                          [{'w': a, 't': b, 'd': c} for a, b, c in plan], search=False))
    sections.append(table('All practice questions', [col('t', 'Theme'), col('q', 'Question'), col('f', 'Framework')],
                          [{'t': t, 'q': q, 'f': f} for t, q, f, _ in QUESTIONS]))
    sections.append(html(script))
    return page('learn-daily', sections)


def glossary(R, args, ws):
    from .modules import NAV
    labels = {k: lbl for k, _, lbl, _ in NAV}
    rows = [{'term': t, 'def': d, 'why': w, 'where': labels.get(p, p), 'link': f'/m/{p}'} for t, d, w, p in sorted(GLOSSARY, key=lambda x: x[0].lower())]
    sections = [callout(f'{len(rows)} terms used in enterprise resource management, strategic portfolio management and roadmap governance. '
                        'Each links to the page where the concept is working on live data.', 'info'),
                table('Glossary', [col('term', 'Term'), col('def', 'Meaning'), col('why', 'Why it matters'), col('where', 'In Plan Yukta', 'link')], rows)]
    return page('learn-glossary', sections)
