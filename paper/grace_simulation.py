"""
Seeded simulation of the grace-period parameter in AttendanceEngine.

Model: 50 participants join at t=0 and stay until the end of a 90-minute meeting
(scan interval 5 min -> 19 scans, t=0..90) or leave permanently at a random scan.
Each scan independently fails to see each present participant with probability p
(transient read error: panel re-render, scroll-position miss, reconnect).

Metrics per (grace, p), averaged over TRIALS independent meetings:
  sessions_per_person : ideal 1.0; >1 means the person's attendance was fragmented
  fragmented_pct      : % of participants with more than one recorded session
  duration_mae_min    : mean |recorded total minutes - true minutes| (true = first to
                        last scan at which the person was truly present)
  false_leave_pct     : % of participants with at least one false leave event

This exercises the real AttendanceEngine from GMA_tracker_dom.py; no browser needed.
Run:  python paper/grace_simulation.py   ->  paper/grace_results.json
"""
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import logging
logging.disable(logging.CRITICAL)
from GMA_tracker_dom import AttendanceEngine  # noqa: E402

N_PEOPLE, SCANS, INTERVAL, TRIALS = 50, 19, 5, 300
GRACES = (1, 2, 3)
PROBS = (0.0, 0.01, 0.02, 0.05, 0.10)
T0 = datetime(2025, 1, 1, 10, 0, 0)


def one_meeting(grace, p, rng):
    # true presence: each person present for scans 0..last (half leave early at a random scan)
    last = {i: (SCANS - 1 if rng.random() < 0.5 else rng.randrange(3, SCANS - 1)) for i in range(N_PEOPLE)}
    eng = AttendanceEngine(grace_scans=grace, your_name="")
    for s in range(SCANS):
        now = T0 + timedelta(minutes=s * INTERVAL)
        seen = [f"P{i}" for i in range(N_PEOPLE) if s <= last[i] and rng.random() >= p]
        eng.update({"Main Call": seen}, now)
    eng.finalize(T0 + timedelta(minutes=(SCANS - 1) * INTERVAL))
    per = {}
    for s in eng.rooms["Main Call"].sessions if "Main Call" in eng.rooms else []:
        per.setdefault(s.name, []).append(s)
    sessions = frag = false_leaves = 0
    err = 0.0
    counted = 0
    for i in range(N_PEOPLE):
        ss = per.get(f"P{i}", [])
        if not ss:          # never seen at all (possible only if every scan missed)
            continue
        counted += 1
        sessions += len(ss)
        frag += len(ss) > 1
        false_leaves += len(ss) > 1
        rec = sum((x.leave_time - x.join_time).total_seconds() for x in ss) / 60
        first = min(x.join_time for x in ss)
        true_min = (last[i] * INTERVAL) - ((first - T0).total_seconds() / 60)
        err += abs(rec - true_min)
    return counted, sessions, frag, false_leaves, err


def main():
    out = []
    for grace in GRACES:
        for p in PROBS:
            rng = random.Random(1000 * grace + int(p * 1000))
            C = S = F = FL = 0
            E = 0.0
            for _ in range(TRIALS):
                c, s, f, fl, e = one_meeting(grace, p, rng)
                C += c; S += s; F += f; FL += fl; E += e
            out.append(dict(grace_scans=grace, miss_prob=p, trials=TRIALS, people=C,
                            sessions_per_person=round(S / C, 4),
                            fragmented_pct=round(100 * F / C, 2),
                            false_leave_pct=round(100 * FL / C, 2),
                            duration_mae_min=round(E / C, 3)))
            print(f"grace={grace} p={p:4.2f}  sessions/person={S / C:.3f}  fragmented={100 * F / C:5.2f}%  MAE={E / C:5.2f} min")
    (Path(__file__).parent / "grace_results.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
