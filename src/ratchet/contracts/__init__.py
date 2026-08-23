"""Frozen contracts shared by every Ratchet component.

This package is the coordination point for the whole codebase. Extractors,
rules, scoring, the CLI, and the GitHub renderer all depend on it, and on
nothing of each other's. Changing anything here is a breaking change for every
work package at once, so treat it as an API: additive changes are cheap,
renames and removals are not.
"""

from ratchet.contracts.changes import ChangeKind, ChangeSet, FileChange, Hunk
from ratchet.contracts.config import (
    DEFAULT_JUSTIFICATION_TRAILER,
    DEFAULT_TEST_GLOBS,
    OracleSettings,
    RatchetConfig,
    RuleSetting,
)
from ratchet.contracts.findings import (
    Evidence,
    Finding,
    Severity,
    Side,
    sort_findings,
)
from ratchet.contracts.paths import is_test_path, matches_any, matches_glob
from ratchet.contracts.rules import (
    NullSurfaceProvider,
    RuleBase,
    RuleContext,
    SurfaceProvider,
    get_rule,
    register,
    registered_rules,
)
from ratchet.contracts.score import MAX_SCORE, TrustScore
from ratchet.contracts.surface import (
    Assertion,
    AssertionKind,
    MockUsage,
    RetryWrapper,
    SkipMarker,
    SkipReason,
    TestCase,
    TestPair,
    TestSurface,
    pair_tests,
)

__all__ = [
    "DEFAULT_JUSTIFICATION_TRAILER",
    "DEFAULT_TEST_GLOBS",
    "MAX_SCORE",
    "Assertion",
    "AssertionKind",
    "ChangeKind",
    "ChangeSet",
    "Evidence",
    "FileChange",
    "Finding",
    "Hunk",
    "MockUsage",
    "NullSurfaceProvider",
    "OracleSettings",
    "RatchetConfig",
    "RetryWrapper",
    "RuleBase",
    "RuleContext",
    "RuleSetting",
    "Severity",
    "Side",
    "SkipMarker",
    "SkipReason",
    "SurfaceProvider",
    "TestCase",
    "TestPair",
    "TestSurface",
    "TrustScore",
    "get_rule",
    "is_test_path",
    "matches_any",
    "matches_glob",
    "pair_tests",
    "register",
    "registered_rules",
    "sort_findings",
]
