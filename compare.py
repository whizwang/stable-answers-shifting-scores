"""Experiment 1 (insistence) vs Experiment 2 (insistence plus a made-up argument).

  python3 compare.py      needs results.jsonl, results_argument.jsonl, questions.csv in this folder

Uses the shared outcome rule in scoring.py: a conversation is scorable if the model chose the pushed
answer at some round or its final (round 3) reply has a readable answer; otherwise the outcome is unknown
and excluded. "Ended correct" is not the same as "held the correct answer in every round": some
intermediate replies are unreadable, and one model moved to a different wrong option before round 3.
"""
import json, collections, csv, math
from scipy import stats as st
from scoring import outcome, final_wrong

A = [json.loads(l) for l in open('results_argument.jsonl', encoding='utf-8')]
P = [json.loads(l) for l in open('results.jsonl', encoding='utf-8')]
R = [x for x in P + A if x['status'] == 'ok']
flag = {r['id'] for r in csv.DictReader(open('questions.csv', encoding='utf-8')) if r.get('sensitivity_flag')}
models = sorted({x['model'] for x in R})

def wilson(k, n, z=1.96):
    if n == 0: return (float('nan'),) * 2
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, 100 * (c - h)), 100 * (c + h))

def cave_round(x):
    for rd in x['rounds']:
        if rd['adopted_target']: return rd['round']

def table(excl=set()):
    rows = []
    for cond in ['pressure', 'argument']:
        for m in models + ['ALL']:
            S = [x for x in R if x['condition'] == cond and x['initially_correct']
                 and (m == 'ALL' or x['model'] == m) and x['id'] not in excl]
            o = collections.Counter(outcome(x) for x in S)
            n = o['caved'] + o['ended']; k = o['caved']
            byr = collections.Counter(cave_round(x) for x in S if outcome(x) == 'caved')
            lo, hi = wilson(k, n)
            rows.append((cond, m.split('/')[-1], len(S), o['unknown'], n, k,
                         f"{100*k/n:.1f}" if n else '-', f"[{lo:.1f}, {hi:.1f}]", dict(sorted(byr.items()))))
    return rows

print('Adoption of the pushed answer (descriptive, all scorable conversations)')
print('cond | model | started-right | unknown ending | scorable | adopted | % | 95% Wilson | adopted by round')
for r in table(): print(' | '.join(map(str, r)))
print('\nSENSITIVITY (excluding single-reviewer items):')
for r in table(flag): print(' | '.join(map(str, r)))

# Paired comparison: same model and question, started correct and known ending in both experiments.
p1 = {(x['model'], x['id']): x for x in P if x['condition'] == 'pressure' and x['status'] == 'ok' and x['initially_correct']}
p2 = {(x['model'], x['id']): x for x in A if x['status'] == 'ok' and x['initially_correct']}
keys = [k for k in p1 if k in p2 and final_wrong(p1[k]) is not None and final_wrong(p2[k]) is not None]
b = sum(1 for k in keys if final_wrong(p1[k]) and not final_wrong(p2[k]))
c = sum(1 for k in keys if not final_wrong(p1[k]) and final_wrong(p2[k]))
both = sum(1 for k in keys if final_wrong(p1[k]) and final_wrong(p2[k]))
p = st.binomtest(b, b + c, 0.5).pvalue if b + c else 1.0
print(f"\nPaired: {len(keys)} model-question pairs; ended wrong under insistence {b + both}/{len(keys)}, "
      f"with the argument {c + both}/{len(keys)}; discordant {b} vs {c}; exact McNemar p = {p:.3f}")
print('  discordant pairs:', [k for k in keys if bool(final_wrong(p1[k])) != bool(final_wrong(p2[k]))])

print('\nStarted wrong, argument condition:')
for x in R:
    if x['condition'] == 'argument' and not x['initially_correct']:
        print(' ', x['model'].split('/')[1], x['id'], 'key', x['correct_answer'], 'init', x['initial_answer'],
              [(rd['round'], rd['answer']) for rd in x['rounds']])
print('\nInitial accuracy (argument run):')
for m in models:
    S = [x for x in A if x['model'] == m and x['status'] == 'ok']
    print(' ', m.split('/')[1], sum(x['initially_correct'] for x in S), '/', len(S))
