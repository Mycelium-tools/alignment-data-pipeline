"""
TEMPORARY TEST FILE — DO NOT REVIEW BY HAND, DO NOT MERGE.

This file exists only to verify that the automated Claude Code Review
GitHub workflow posts inline comments on same-repo PRs after the
permission fixes. The PR that adds it will be closed and the branch
deleted as soon as the automated review has run.

It intentionally contains one small, obvious defect so the automated
reviewer has something concrete to flag.
"""


def running_total(value, totals=[]):
    # Intentional defect: the mutable default argument is shared across
    # every call, so unrelated callers accumulate into the same list.
    totals.append(value)
    return sum(totals)
