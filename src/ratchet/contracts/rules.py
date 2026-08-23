"""The Rule contract, and the context a rule is allowed to see.

A rule is a pure function of its context. It does not touch git, the network,
the filesystem, or the clock. Everything it needs arrives on `RuleContext`,
which means every rule is testable from string literals alone — and that is
what makes the 95%-precision gate affordable to maintain.

Rules self-register by subclassing `RuleBase`; discovery walks the `rules`
package. There is no shared list file to edit, so rules written in parallel
never collide.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from ratchet.contracts.changes import ChangeSet, FileChange
from ratchet.contracts.config import RatchetConfig
from ratchet.contracts.findings import Evidence, Finding, Severity, Side
from ratchet.contracts.surface import TestSurface


class SurfaceProvider(Protocol):
    """Supplies parsed test surfaces without exposing which extractor ran.

    This is the seam between the language extractors and the rules: rules ask
    for a surface, and never learn whether it came from the Python or the
    TypeScript path.
    """

    def surface(self, change: FileChange, side: Side) -> TestSurface | None:
        """Return the surface for one side, or None if this is not a test file."""
        ...


@dataclass(frozen=True, slots=True)
class NullSurfaceProvider:
    """Stand-in for rules that need no AST, and for tests of those rules."""

    def surface(self, change: FileChange, side: Side) -> TestSurface | None:
        return None


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule may look at."""

    changes: ChangeSet
    config: RatchetConfig = field(default_factory=RatchetConfig.default)
    surfaces: SurfaceProvider = field(default_factory=NullSurfaceProvider)

    def test_files(self) -> tuple[FileChange, ...]:
        """Changed files that the config classifies as tests."""
        from ratchet.contracts.paths import is_test_path

        return tuple(
            change
            for change in self.changes.changes
            if not change.is_binary and is_test_path(change.path, self.config)
        )

    def non_test_files(self) -> tuple[FileChange, ...]:
        from ratchet.contracts.paths import is_test_path

        return tuple(
            change
            for change in self.changes.changes
            if not change.is_binary and not is_test_path(change.path, self.config)
        )


class RuleBase(ABC):
    """Convenience base that wires a rule's defaults to repository config.

    Subclasses set the class-level metadata and implement `check`. Severity and
    penalty resolution, config disabling, and evidence construction are handled
    here so that thirteen rules written by different agents report consistently.
    """

    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    default_severity: ClassVar[Severity] = Severity.MEDIUM
    default_penalty: ClassVar[int] = 10
    requires_ast: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "id", None):
            raise TypeError(f"{cls.__name__} must define a rule id")
        _REGISTRY[cls.id] = cls

    @abstractmethod
    def check(self, ctx: RuleContext) -> Sequence[Finding]:
        """Detect losses of verification strength. Must be pure."""

    def apply(self, ctx: RuleContext) -> Sequence[Finding]:
        """Run the rule unless the repository disabled it."""
        if not ctx.config.is_enabled(self.id):
            return ()
        return self.check(ctx)

    def finding(
        self,
        ctx: RuleContext,
        *,
        title: str,
        detail: str,
        path: str,
        evidence: Sequence[Evidence] = (),
        severity: Severity | None = None,
        penalty: int | None = None,
    ) -> Finding:
        """Build a finding with config-resolved severity and penalty."""
        return Finding(
            rule_id=self.id,
            severity=ctx.config.severity_for(self.id, severity or self.default_severity),
            title=title,
            detail=detail,
            path=path,
            penalty=ctx.config.penalty_for(self.id, penalty or self.default_penalty),
            evidence=tuple(evidence),
        )


_REGISTRY: dict[str, type[RuleBase]] = {}


def register(rule_cls: type[RuleBase]) -> type[RuleBase]:
    """Explicit registration, for rules that cannot subclass `RuleBase`."""
    _REGISTRY[rule_cls.id] = rule_cls
    return rule_cls


def registered_rules() -> tuple[type[RuleBase], ...]:
    """Every rule class discovered so far, in stable rule-id order."""
    return tuple(_REGISTRY[key] for key in sorted(_REGISTRY))


def get_rule(rule_id: str) -> type[RuleBase] | None:
    return _REGISTRY.get(rule_id)
