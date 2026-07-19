"""RealDoor reasoning layer: income, thresholds, readiness, checklists, abstention.

Deterministic and pure. No network, no model, no clock dependence -- the frozen event
date 2026-07-18 drives every currency judgement, so the same documents produce the same
report on any machine on any day.

Nothing in this package returns a decision about a person. It returns arithmetic, a
comparison with a frozen threshold, a list of what is missing from a file, and an
explicit list of what it declined to assert.
"""

from logic import abstain, answer_rules, checklist, constants, household, income, readiness, threshold

__all__ = [
    "abstain",
    "answer_rules",
    "checklist",
    "constants",
    "household",
    "income",
    "readiness",
    "threshold",
]
