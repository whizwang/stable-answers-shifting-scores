"""
Turn results.jsonl into charts and a summary table.

  python3 analyze.py                 uses results.jsonl
  python3 analyze.py results_mock.jsonl
  python3 analyze.py --sensitivity   same, excluding questions with a sensitivity_flag in questions.csv
                                     (outputs go to charts_sensitivity/ instead of charts/)

Needs: pip3 install pandas matplotlib
Outputs go to the charts/ folder.
"""
import json, os, sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SENS = "--sensitivity" in sys.argv
src = ARGS[0] if ARGS else os.path.join(HERE, "results.jsonl")
OUT = os.path.join(HERE, "charts_sensitivity" if SENS else "charts")
os.makedirs(OUT, exist_ok=True)

SUBJECT_ORDER = ["high_school_geography", "high_school_mathematics",
                 "clinical_knowledge", "high_school_macroeconomics", "professional_law"]
SUBJECT_LABEL = {"high_school_geography": "Geography", "high_school_mathematics": "Math",
                 "clinical_knowledge": "Medicine", "high_school_macroeconomics": "Economics",
                 "professional_law": "Law"}

raw_recs = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
from scoring import outcome as _outcome
if SENS:
    import csv as _csv
    flagged = {q["id"] for q in _csv.DictReader(open(os.path.join(HERE, "questions.csv"), encoding="utf-8"))
               if q.get("sensitivity_flag", "").strip()}
    raw_recs = [r for r in raw_recs if r["id"] not in flagged]
    print(f"SENSITIVITY ANALYSIS: excluding {len(flagged)} flagged questions: {sorted(flagged)}\n")
recs_all_ok = [r for r in raw_recs if r.get("status") == "ok"]
n_bad = len(raw_recs) - len(recs_all_ok)
n_unknown = sum(_outcome(r) == "unknown" for r in recs_all_ok)
recs = [r for r in recs_all_ok if _outcome(r) != "unknown"]

# One row per conversation per round (0..3). Once the model adopts the
# pushed answer in a pressure/argument condition we stop asking. Only this known
# terminal event is carried forward for cumulative curves; unreadable replies stay missing.
rows = []
for r in recs:
    prev_ans, prev_conf = r["initial_answer"], r["initial_confidence"]
    rows.append(dict(model=r["model"], id=r["id"], subject=r["subject"],
                     condition=r["condition"], start=("right" if r["initially_correct"] else "wrong"),
                     round=0, answer=prev_ans, confidence=prev_conf,
                     adopted=False, changed=False))
    by_round = {x["round"]: x for x in r["rounds"]}
    adopted = changed = False
    for k in (1, 2, 3):
        x = by_round.get(k)
        if x is not None:
            prev_ans = x["answer"]
            prev_conf = x["confidence"]
            adopted = adopted or x["adopted_target"]
        elif not (r["condition"] in ("pressure", "argument") and adopted):
            prev_ans = prev_conf = None
        changed = None if prev_ans is None else prev_ans != r["initial_answer"]
        rows.append(dict(model=r["model"], id=r["id"], subject=r["subject"],
                         condition=r["condition"], start=("right" if r["initially_correct"] else "wrong"),
                         round=k, answer=prev_ans, confidence=prev_conf,
                         adopted=True if adopted else (False if prev_ans is not None else None), changed=changed))
df = pd.DataFrame(rows)
df["adopted"] = df["adopted"].astype(float)
df["changed"] = df["changed"].astype(float)
short = lambda m: m.split("/")[-1]
df["model_short"] = df["model"].map(short)
models = sorted(df["model_short"].unique())

# ---------------------------------------------------------------- summary table
final = df[df["round"] == 3]
import math
def ci(flags):
    """95% Wilson binomial interval, in percent; nondegenerate at boundaries."""
    flags = [bool(x) for x in flags if pd.notna(x)]
    if not flags: return (None, None)
    n = len(flags); p = sum(flags) / n; z = 1.959963984540054
    denominator = 1 + z*z/n
    center = (p + z*z/(2*n)) / denominator
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denominator
    return (round(100*max(0.0, center-half), 1), round(100*min(1.0, center+half), 1))

summary = []
for m in models:
    f = final[final["model_short"] == m]
    p, c = f[f["condition"] == "pressure"], f[f["condition"] == "control"]
    r0 = [r for r in recs_all_ok if short(r["model"]) == m and r["condition"] == "pressure"]
    summary.append({
        "model": m,
        "initial accuracy %": round(100 * sum(r["initially_correct"] for r in r0) / len(r0), 1),  # pressure run, readable first answers
        "capitulation % (right -> caved to wrong pushback)": round(100 * p[p.start == "right"]["adopted"].mean(), 1),
        "n right": int((p.start == "right").sum()),
        "correction % (wrong -> accepted right pushback)": round(100 * p[p.start == "wrong"]["adopted"].mean(), 1),
        "n wrong": int((p.start == "wrong").sum()),
        "control: ended on a different answer % (no pushback)": round(100 * c["changed"].mean(), 1) if len(c) else None,
        "capitulation 95% CI": ci(p[p.start == "right"]["adopted"]),
        "correction 95% CI": ci(p[p.start == "wrong"]["adopted"]),
        "control 95% CI": ci(c["changed"]),
    })
summary = pd.DataFrame(summary)
summary.to_csv(os.path.join(OUT, "summary.csv"), index=False)
print(summary.to_string(index=False))
print(f"\nExcluded conversations: unreadable first answer {n_bad}; unknown ending (unreadable reply) {n_unknown}")

by_subj = (final[(final.condition == "pressure") & (final.start == "right")]
           .groupby(["model_short", "subject"])["adopted"].mean().mul(100).round(1)
           .unstack().reindex(columns=[s for s in SUBJECT_ORDER if s in final.subject.unique()]))
by_subj.columns = [SUBJECT_LABEL[c] for c in by_subj.columns]
by_subj.to_csv(os.path.join(OUT, "capitulation_by_subject.csv"))
print("\nCapitulation % by subject (initially right, pressure):\n", by_subj.to_string())

# ---------------------------------------------------------------- charts
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
COLORS = ["#2f6db3", "#d1495b", "#3a9d6a", "#e0a43a", "#7b5ea7", "#555555"]

# 1. Flip curves: cumulative % adopting the pushed answer by round
fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), sharey=True)
for ax, start, title in [(axes[0], "right", "Started RIGHT, pushed toward wrong\n(capitulation, lower is better)"),
                         (axes[1], "wrong", "Started WRONG, pushed toward right\n(correction, higher is better)")]:
    for i, m in enumerate(models):
        s = df[(df.model_short == m) & (df.condition == "pressure") & (df.start == start)]
        if s.empty: continue
        curve = s.groupby("round")["adopted"].mean() * 100
        n = s["id"].nunique()
        ax.plot(curve.index, curve.values, marker="o", color=COLORS[i % 6], label=f"{m} (n={n})")
    ax.set_title(title, fontsize=11); ax.set_xticks([0, 1, 2, 3])
    ax.set_xticklabels(["Initial", "Round 1\n\"Are you sure?\"", "Round 2\n\"Fairly confident\"", "Round 3\n\"I'm an expert\""], fontsize=9)
    ax.set_ylim(0, 100); ax.grid(axis="y", alpha=.3)
axes[0].set_ylabel("% observed adoption (unreadable replies omitted)")
axes[1].legend(fontsize=9, frameon=False)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "1_flip_curves.png"), dpi=200); plt.close(fig)

# 2. Capitulation vs correction vs control, per model
fig, ax = plt.subplots(figsize=(9, 4.8))
w = 0.27
cols = [("capitulation % (right -> caved to wrong pushback)", "Capitulation (caved when right)", "#d1495b"),
        ("correction % (wrong -> accepted right pushback)", "Correction (fixed when wrong)", "#3a9d6a"),
        ("control: ended on a different answer % (no pushback)", "Control (changed with no pushback)", "#999999")]
ci_cols = ["capitulation 95% CI", "correction 95% CI", "control 95% CI"]
for j, (c, lab, col) in enumerate(cols):
    vals = summary[c].fillna(0).values
    lo = [v - (b[0] if b[0] is not None else v) for v, b in zip(vals, summary[ci_cols[j]])]
    hi = [(b[1] if b[1] is not None else v) - v for v, b in zip(vals, summary[ci_cols[j]])]
    xs = [i + (j - 1) * w for i in range(len(models))]
    valid = summary[c].notna().tolist()
    ax.bar([x for x, ok in zip(xs, valid) if ok], [v for v, ok in zip(vals, valid) if ok],
           w, label=lab, color=col, yerr=[[v for v, ok in zip(lo, valid) if ok],
           [v for v, ok in zip(hi, valid) if ok]], capsize=3, error_kw={"lw": .8})
    for x, v, h, ok in zip(xs, vals, hi, valid):
        if not ok:
            ax.text(x, 1.5, "n/a", ha="center", fontsize=8)
            continue
        ax.text(x, v + h + 1.5, f"{v:.0f}", ha="center", fontsize=8)
ax.set_xticks(range(len(models))); ax.set_xticklabels(summary["model"], fontsize=9)
ax.set_ylabel("% at endpoint (bars: 95% Wilson CI)"); ax.set_ylim(0, 110)
ax.legend(fontsize=9, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3); ax.grid(axis="y", alpha=.3)
ax.set_title("A good model fixes mistakes but holds correct answers", fontsize=11)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "2_capitulation_vs_correction.png"), dpi=200); plt.close(fig)

# 3. Capitulation by subject
fig, ax = plt.subplots(figsize=(9, 4.3))
subs = list(by_subj.columns)
w = 0.8 / max(len(models), 1)
for i, m in enumerate(models):
    if m not in by_subj.index: continue
    ax.bar([k + (i - (len(models) - 1) / 2) * w for k in range(len(subs))],
           by_subj.loc[m].values, w, label=m, color=COLORS[i % 6])
ax.set_xticks(range(len(subs))); ax.set_xticklabels(subs)
ax.set_ylabel("Capitulation % after 3 rounds"); ax.set_ylim(0, 100)
ax.set_title("Capitulation by subject (ordered from most to least checkable)", fontsize=11)
ax.legend(fontsize=9, frameon=False); ax.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "3_capitulation_by_subject.png"), dpi=200); plt.close(fig)

# 4. Available stated confidence: correct initially, no observed target adoption.
fig, ax = plt.subplots(figsize=(7, 4.3))
for i, m in enumerate(models):
    ids_held = final[(final.model_short == m) & (final.condition == "pressure") &
                     (final.start == "right") & (final.adopted == 0)]["id"]
    s = df[(df.model_short == m) & (df.condition == "pressure") & (df.id.isin(ids_held))]
    if s.empty: continue
    curve = s.groupby("round")["confidence"].mean()
    ax.plot(curve.index, curve.values, marker="o", color=COLORS[i % 6], label=m)
ax.set_xticks([0, 1, 2, 3]); ax.set_xticklabels(["Initial", "R1", "R2", "R3"])
ax.set_ylabel("Mean stated confidence (0-100)")
ax.set_title("Stated confidence: correct initially, no observed target adoption\nMean of readable confidence values at each round", fontsize=10)
ax.legend(fontsize=9, frameon=False); ax.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "4_confidence_erosion.png"), dpi=200); plt.close(fig)

print(f"\nCharts and tables saved in {os.path.relpath(OUT, HERE)}")
