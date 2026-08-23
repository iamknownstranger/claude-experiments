"""TestSurface — the language-independent shape of a test file's checking power.

Every language extractor produces this, and every AST rule consumes only this.
That boundary is what lets a Python extractor and a TypeScript extractor be
written by different people at the same time and still feed the same rules.

The central idea is that assertions are *ranked*. `assertEqual(x, 3)` proves
more than `assertTrue(x)`, which proves more than `assertIsNotNone(x)`. Ranking
them is what makes "the agent weakened this test" a computable claim rather
than a judgement call.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property


class AssertionKind(StrEnum):
    """What an assertion actually proves, independent of framework spelling.

    Members are ordered by proving power via :attr:`strength`. A change that
    lowers strength is a weakening, which is the whole basis of VID005.
    """

    EQUALITY = "equality"
    IDENTITY = "identity"
    APPROXIMATE = "approximate"
    COMPARISON = "comparison"
    MEMBERSHIP = "membership"
    EXCEPTION = "exception"
    SNAPSHOT = "snapshot"
    TYPE = "type"
    CALL = "call"
    TRUTHINESS = "truthiness"
    EXISTENCE = "existence"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

    @property
    def strength(self) -> int:
        """How much this assertion proves. Higher is stronger."""
        return _ASSERTION_STRENGTH[self]


# Deliberately coarse. The gap between tiers must be wide enough that ordinary
# refactors do not cross one, because every crossing costs a reviewer's time.
_ASSERTION_STRENGTH: dict[AssertionKind, int] = {
    AssertionKind.EQUALITY: 100,
    AssertionKind.IDENTITY: 100,
    AssertionKind.SNAPSHOT: 90,
    AssertionKind.APPROXIMATE: 80,
    AssertionKind.EXCEPTION: 75,
    AssertionKind.COMPARISON: 70,
    AssertionKind.MEMBERSHIP: 70,
    AssertionKind.TYPE: 50,
    AssertionKind.CALL: 45,
    AssertionKind.CUSTOM: 40,
    AssertionKind.TRUTHINESS: 30,
    AssertionKind.EXISTENCE: 20,
    AssertionKind.UNKNOWN: 40,
}


class SkipReason(StrEnum):
    """Why a test will not run."""

    SKIP = "skip"
    SKIP_IF = "skip_if"
    EXPECTED_FAILURE = "expected_failure"
    TODO = "todo"
    EXCLUSIVE_FOCUS = "exclusive_focus"
    """`.only` / `fit` — not a skip of itself, but it silences every sibling."""


@dataclass(frozen=True, slots=True)
class Assertion:
    """One check inside a test."""

    kind: AssertionKind
    callee: str
    line: int
    operands: tuple[str, ...] = field(default_factory=tuple)
    tolerance: float | None = None
    negated: bool = False

    @property
    def strength(self) -> int:
        return self.kind.strength

    def signature(self) -> str:
        """Identity used to pair assertions across base and head.

        Operands are included because two `assertEqual` calls in one test are
        different assertions; the line number is not, because unrelated edits
        shift lines constantly and would produce noise.
        """
        return f"{self.kind}:{self.callee}:{'|'.join(self.operands)}"


@dataclass(frozen=True, slots=True)
class SkipMarker:
    reason: SkipReason
    line: int
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class MockUsage:
    """A stubbed-out boundary.

    `target` is the symbol being replaced. When that symbol is the unit the
    test claims to exercise, the test no longer tests anything — VID007.
    """

    target: str
    line: int
    callee: str


@dataclass(frozen=True, slots=True)
class RetryWrapper:
    """Flake suppression: reruns until green, hiding a real failure — VID012."""

    callee: str
    line: int
    max_attempts: int | None = None


@dataclass(frozen=True, slots=True)
class TestCase:
    """One test, normalized across frameworks."""

    # These contract types are named `Test*` because that is what they model.
    # Without this, pytest tries to collect them as test classes in every module
    # that imports them and warns on each one.
    __test__ = False

    id: str
    name: str
    qualname: str
    line_start: int
    line_end: int
    is_discoverable: bool = True
    assertions: tuple[Assertion, ...] = field(default_factory=tuple)
    skip_markers: tuple[SkipMarker, ...] = field(default_factory=tuple)
    mocks: tuple[MockUsage, ...] = field(default_factory=tuple)
    retries: tuple[RetryWrapper, ...] = field(default_factory=tuple)
    exercised_symbols: frozenset[str] = field(default_factory=frozenset)

    @property
    def assertion_count(self) -> int:
        return len(self.assertions)

    @property
    def total_strength(self) -> int:
        """Summed proving power. The scalar VID002 and VID005 compare."""
        return sum(a.strength for a in self.assertions)

    @property
    def is_skipped(self) -> bool:
        return any(m.reason is not SkipReason.EXCLUSIVE_FOCUS for m in self.skip_markers)

    @property
    def will_run(self) -> bool:
        return self.is_discoverable and not self.is_skipped


# No `slots=True` here: `by_id` is a `cached_property`, which needs an instance
# `__dict__` to memoize into. `frozen=True` is still fine — cached_property
# writes through `__dict__` directly rather than via `__setattr__`.
@dataclass(frozen=True)
class TestSurface:
    """Every test in one file, as one version of that file.

    `parse_ok=False` means the extractor could not read the file. Rules must
    treat that as "unknown", never as "no tests" — inferring deletion from a
    parse failure is exactly the false positive that gets a gate disabled.
    """

    __test__ = False

    path: str
    language: str
    framework: str
    tests: tuple[TestCase, ...] = field(default_factory=tuple)
    parse_ok: bool = True
    parse_error: str | None = None

    @cached_property
    def by_id(self) -> Mapping[str, TestCase]:
        return {t.id: t for t in self.tests}

    @property
    def assertion_count(self) -> int:
        return sum(t.assertion_count for t in self.tests)

    @property
    def total_strength(self) -> int:
        return sum(t.total_strength for t in self.tests if t.will_run)

    @property
    def running_tests(self) -> tuple[TestCase, ...]:
        return tuple(t for t in self.tests if t.will_run)

    @classmethod
    def empty(cls, path: str, language: str = "unknown", framework: str = "unknown") -> TestSurface:
        """The surface of a file that does not exist yet (added files)."""
        return cls(path=path, language=language, framework=framework)

    @classmethod
    def unparsed(cls, path: str, error: str, language: str = "unknown") -> TestSurface:
        return cls(
            path=path,
            language=language,
            framework="unknown",
            parse_ok=False,
            parse_error=error,
        )


@dataclass(frozen=True, slots=True)
class TestPair:
    """The same test, before and after. Either side may be absent."""

    __test__ = False

    base: TestCase | None
    head: TestCase | None

    @property
    def removed(self) -> bool:
        return self.base is not None and self.head is None

    @property
    def added(self) -> bool:
        return self.base is None and self.head is not None

    @property
    def strength_delta(self) -> int:
        base = self.base.total_strength if self.base else 0
        head = self.head.total_strength if self.head else 0
        return head - base


def pair_tests(base: TestSurface, head: TestSurface) -> tuple[TestPair, ...]:
    """Match tests across two versions of a file by stable id.

    Shared by every AST rule so that "the same test" means one thing across the
    whole rule set. Renames surface as a removal plus an addition — deliberately,
    since a rename out of the discovery pattern is itself the VID001 signal.
    """
    base_ids = list(base.by_id)
    head_by_id = head.by_id
    seen: set[str] = set()
    pairs: list[TestPair] = []

    for test_id in base_ids:
        seen.add(test_id)
        pairs.append(TestPair(base=base.by_id[test_id], head=head_by_id.get(test_id)))

    for test_id, test in head_by_id.items():
        if test_id not in seen:
            pairs.append(TestPair(base=None, head=test))

    return tuple(pairs)
