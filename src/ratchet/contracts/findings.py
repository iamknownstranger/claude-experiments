"""Findings — what a rule reports when it detects verification strength loss.

Every rule speaks this language and nothing else. A finding is inert data: it
carries the evidence a human needs to agree or disagree, and the penalty the
scorer applies. Rules never decide policy; they only report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

Side = Literal["base", "head"]


class Severity(StrEnum):
    """How badly a finding undermines trust in the build being green."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


@dataclass(frozen=True, slots=True)
class Evidence:
    """One citation backing a finding.

    Evidence always points at a real line in a real version of a real file, so
    a reviewer can jump straight to it. A finding without evidence is an
    accusation; a finding with evidence is a review comment.
    """

    path: str
    line: int
    side: Side
    snippet: str

    def __post_init__(self) -> None:
        if self.line < 1:
            raise ValueError(f"evidence line must be 1-indexed, got {self.line}")

    def locator(self) -> str:
        """Render as ``path:line``, the clickable form."""
        return f"{self.path}:{self.line}"


@dataclass(frozen=True, slots=True)
class Finding:
    """A single detected loss of verification strength."""

    rule_id: str
    severity: Severity
    title: str
    detail: str
    path: str
    penalty: int
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    justification: str | None = None

    def __post_init__(self) -> None:
        if self.penalty < 0:
            raise ValueError(f"penalty must be non-negative, got {self.penalty}")

    @property
    def justified(self) -> bool:
        """True when a human accepted this loss via a commit trailer."""
        return self.justification is not None

    @property
    def effective_penalty(self) -> int:
        """Justified findings stay visible in the report but cost nothing."""
        return 0 if self.justified else self.penalty

    def with_justification(self, reason: str) -> Finding:
        """Return a copy accepted by a human, preserving the original evidence."""
        return Finding(
            rule_id=self.rule_id,
            severity=self.severity,
            title=self.title,
            detail=self.detail,
            path=self.path,
            penalty=self.penalty,
            evidence=self.evidence,
            justification=reason,
        )

    def primary_location(self) -> str:
        return self.evidence[0].locator() if self.evidence else self.path


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Order findings most-severe first, then by location — stable for snapshots."""
    return sorted(
        findings,
        key=lambda f: (-f.severity.rank, -f.penalty, f.rule_id, f.primary_location()),
    )
