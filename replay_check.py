"""Replays every saved transcript through the final fliprate.py with a fake client that returns the
saved model replies, and checks that the script would send exactly the same user messages and
produce the same scored fields. No API calls."""
import json, sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fliprate as F

class Replay:
    def __init__(self, saved, finishes=None):
        self.saved, self.finishes, self.i = saved, finishes or [], 0
    def chat(self, model, msgs):
        n = len(msgs)
        if [m['content'] for m in msgs] != [m['content'] for m in self.saved[:n]]:
            raise AssertionError('prompt mismatch')
        r = F.Reply(self.saved[n]['content']) if n < len(self.saved) else F.Reply('')
        r.finish = self.finishes[self.i] if self.i < len(self.finishes) else None
        self.i += 1
        return r

qs = {q['id']: q for q in F.load_questions()}
args = F.load_arguments()
keys = ['initial_answer', 'initial_confidence', 'initially_correct', 'target', 'status']
def check(name, recs, fn, fields):
    bad = 0
    for x in recs:
        if not x.get('messages'):
            continue
        try:
            y = fn(x)
            diffs = [k for k in fields if x.get(k) != y.get(k)]
            if diffs or [m['content'] for m in y['messages']] != [m['content'] for m in x['messages']]:
                bad += 1; print('  differs:', x['model'], x.get('id', x.get('essay_id')), x.get('condition', x.get('framing')), diffs)
        except AssertionError:
            bad += 1; print('  prompt mismatch:', x['model'], x.get('id', x.get('essay_id')), x.get('condition', x.get('framing')))
    print(f"{name}: {len(recs)} records, {bad} differ from what the final script would send/score")

P = [json.loads(l) for l in open('results.jsonl', encoding='utf-8')]
A = [json.loads(l) for l in open('results_argument.jsonl', encoding='utf-8')]
T = [json.loads(l) for l in open('results_timing.jsonl', encoding='utf-8')]
FB = [json.loads(l) for l in open('results_feedback.jsonl', encoding='utf-8')]
check('Exp 1', P, lambda x: F.run_one(Replay(x['messages']), x['model'], qs[x['id']], x['condition']), keys)
check('Exp 2', A, lambda x: F.run_one(Replay(x['messages'], x.get('finish_reasons')), x['model'], qs[x['id']], 'argument', args), keys + ['argument'])
saved = F.load_saved_answers()
check('Exp 3', T, lambda x: F.run_timing_one(Replay(x['messages'], [x.get('finish_reason')]), x['model'], qs[x['id']], x['condition'], args, saved),
      ['answer', 'confidence', 'adopted_target', 'correct', 'status', 'target', 'claim'])
E = {e['essay_id']: e for e in F.load_essays()}
check('Exp 4', FB, lambda x: F.run_feedback_one(Replay(x['messages'], [x.get('finish_reason')]), x['model'], E[x['essay_id']], x['framing']),
      ['score', 'error_flag', 'error_description', 'status'])
