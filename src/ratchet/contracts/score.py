"""TrustScore — the single number that drives merge policy.

Scoring starts from a full 100-point budget and spends it on evidence. This is
the opposite of a bug-finder's "count the issues": the question is not how many
problems exist, but how much of the build's claim to being green survives.

The type lives in `contracts` because the CLI, the GitHub renderer, and the
merge-queue ordering all consume it; the computation lives in `ratchet.score`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ratchet.contracts.findings import Finding, Severity

MAX_SCORE = 100


@dataclass(frozen=True, slots=True)
class TrustScore:
    """How much a PR's green build can be believed, and why."""

    value: int
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    threshold: int = 70

    def __post_init__(self) -> None:
        if not 0 <= self.value <= MAX_SCORE:
            raise ValueError(f"trust score out of range: {self.value}")

    @property
    def passed(self) -> bool:
        return self.value >= self.threshold

    @property
    def unjustified(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if not f.justified)

    @property
    def justified(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.justified)

    @property
    def worst_severity(self) -> Severity | None:
        unjustified = self.unjustified
        if not unjustified:
            return None
        return max((f.severity for f in unjustified), key=lambda s: s.rank)

    @property
    def band(self) -> str:
        """Coarse label used for merge-queue ordering and check summaries."""
        if self.value >= 90:
            return "trusted"
        if self.value >= self.threshold:
            return "acceptable"
        if self.value >= 40:
            return "suspect"
        return "untrusted"

    def summary(self) -> str:
        count = len(self.unjustified)
        if count == 0:
            return f"Trust {self.value}/100 ({self.band}) — no verification loss detected"
        noun = "finding" if count == 1 else "findings"
        return f"Trust {self.value}/100 ({self.band}) — {count} unjustified {noun}"
