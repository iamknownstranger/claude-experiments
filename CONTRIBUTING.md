# Contributing to Ratchet

Most work here is done by agents working in parallel on separate branches. This document
is the contract that lets that happen without the branches fighting each other.

## The one rule that matters

**`src/ratchet/contracts/` is frozen.** Every work package is written against it and
against nothing of each other's. Adding to it is cheap; renaming or removing anything in it
breaks every other branch in flight at once. If you believe a contract is wrong, say so
before changing it.

## Writing a rule

A rule is a pure function of its `RuleContext`. It does not touch git, the network, the
filesystem, or the clock. Everything it may look at arrives on the context, which is what
makes rules testable from string literals alone.

```python
from collections.abc import Sequence

from ratchet.contracts import Evidence, Finding, RuleBase, RuleContext, Severity


class TestRemoved(RuleBase):
    id = "VID001"
    name = "Test removed"
    description = "A test was deleted or renamed out of the discovery pattern."
    default_severity = Severity.HIGH
    default_penalty = 25
    requires_ast = True

    def check(self, ctx: RuleContext) -> Sequence[Finding]:
        findings = []
        for change in ctx.test_files():
            base = ctx.surfaces.surface(change, "base")
            head = ctx.surfaces.surface(change, "head")
            if base is None or head is None or not base.parse_ok:
                continue  # unknown is not the same as "nothing was there"
            ...
        return findings
```

Rules self-register by subclassing `RuleBase`. There is no shared registry file to edit,
which is precisely why two people can add rules on the same day.

### Non-negotiables for rule authors

1. **A parse failure is not a deletion.** If `surface.parse_ok` is `False`, return nothing.
   Reading "I couldn't parse this" as "the tests are gone" is the single fastest way to
   make the gate untrustworthy.
2. **Every finding carries evidence.** A finding without a `path:line` a reviewer can jump
   to is an accusation, not a review comment.
3. **Precision over recall.** When you are unsure, do not fire. CI enforces ≥95% precision
   on VID001–VID005 against the corpus. Missing a detection is a bug; inventing one
   undermines the product's entire premise.
4. **Never call an LLM from a `VID*` rule.** The deterministic engine must stay fast,
   reproducible, and free. Model calls belong in `ratchet.oracle`.

## Local checks

Run these before pushing — they are exactly what CI runs.

```bash
uv sync --all-extras
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -m "not oracle"
```

## Commits and PRs

Commits and PR titles are [Conventional Commits](https://www.conventionalcommits.org/).
Releases are derived from them automatically on every merge, so the subject line is the
changelog entry:

```
feat(rules): add VID003 skip-marker detection
fix(diff): keep base line numbers across renames
```

Scopes in use: `contracts`, `diff`, `parse`, `langs`, `rules`, `score`, `policy`, `cli`,
`github`, `oracle`, `trajectory`, `corpus`, `ci`.

PRs merge automatically once required checks pass. That makes CI the only reviewer most
changes get, so treat a red check as a blocking review and never weaken a check to get
past it — which is, after all, the exact behaviour this project exists to detect.

## Accepting a verification loss

Sometimes deleting a test is correct. Ratchet does not forbid it; it requires that a human
own it, via a commit trailer:

```
Ratchet-Justification: VID001 — removes tests for the legacy exporter deleted in #482
```

The finding stays in the report with its evidence intact, and stops costing trust points.
