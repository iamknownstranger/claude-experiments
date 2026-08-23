"""Ratchet — a merge gate that proves agent-authored PRs earned their green build.

Coding agents are documented to pass tests without doing the work: deleting
assertions, adding skips, widening tolerances, mocking out the unit under test,
or lifting the answer from git history. Every mainstream review tool inspects
the diff for *bugs*. Ratchet asks the other question — did the agent do the
work, or did it just make the checks go green?

The invariant is a one-way ratchet: a repository's provable correctness may
never decrease without a named human accepting the loss.
"""

__version__ = "0.2.0"
