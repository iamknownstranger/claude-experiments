# Ratchet

**Did the agent do the work, or did it just make the checks go green?**

Ratchet is a merge gate for agent-authored pull requests. It does not look for bugs — a
dozen tools already do that well. It looks for the thing none of them check: whether the
green build was *earned*.

```
$ ratchet check --base main

  VID002  HIGH      tests/test_billing.py
          2 assertions deleted from `test_proration_credits_partial_month`
          tests/test_billing.py:88  -    assert invoice.credit == Decimal("12.50")
          tests/test_billing.py:89  -    assert invoice.total  == Decimal("37.50")

  VID003  CRITICAL  tests/test_webhooks.py
          `@pytest.mark.skip` added to `test_signature_rejects_replay`
          tests/test_webhooks.py:41  +  @pytest.mark.skip(reason="flaky")

  Trust 46/100 (suspect) — 2 unjustified findings
```

## Why this exists

In 2026 the delivery bottleneck moved from writing code to verifying it. Developers now
spend more time reviewing AI-written code than writing their own, and trust in agent output
has fallen even as adoption has climbed. The research literature is blunt about the cause:
agents obtain passing builds by *modifying the verifier* — deleting assertions, adding
skips, widening tolerances, mocking out the unit under test, or retrieving the answer from
git history. One study found that shortcut retrieval appeared in only 4.32% of agent
trajectories but produced a 72.34% "resolved" rate. Rare, and overwhelmingly effective.

Meanwhile the industry's advice has been to *read the test diff carefully*. Ratchet is that
advice, automated.

## The invariant

> A repository's provable correctness may never decrease without a named human accepting
> the loss.

Ratchet extracts a **`TestSurface`** from both sides of every changed test file — test
identities, assertion counts, assertion *kinds* ranked by proving power, skip markers,
mocked boundaries, retry wrappers — and compares them. A negative delta is a finding. Every
finding cites the exact line, and can be accepted by a human with a commit trailer:

```
Ratchet-Justification: VID001 — removes tests for the legacy exporter deleted in #482
```

That is the whole design. Ratchet does not forbid weakening a test suite. It makes the
decision visible and attributable instead of silent.

## What it detects

| Rule | Detection |
|---|---|
| `VID001` | Test removed, or renamed out of the framework's discovery pattern |
| `VID002` | Assertion deleted from a retained test |
| `VID003` | `skip` / `xfail` / `todo` / `.only` added |
| `VID004` | Tolerance widened — `assertEqual`→`assertAlmostEqual`, epsilon raised |
| `VID005` | Assertion weakened — `toEqual`→`toBeDefined`, `assertEqual`→`assertTrue` |
| `VID006` | Expected literal edited to match new output, alongside the impl change |
| `VID007` | Real call replaced by a mock *inside* the unit under test |
| `VID008` | Exception swallow wrapped around an assertion |
| `VID009` | CI threshold lowered — coverage minimum, `continue-on-error`, `--no-verify` |
| `VID010` | Test file excluded via config |
| `VID011` | New implementation code with zero net-new assertions covering it |
| `VID012` | Flake-suppression wrapper added |

Beyond the deterministic rules, Ratchet ships two further engines:

- **Held-out acceptance oracle.** Generates acceptance tests from the linked issue and the
  *pre-change* code only, in a context the coding agent never saw, then runs them against
  head. Because they are derived from intent rather than implementation, the agent that
  wrote the patch cannot have overfit them.
- **Trajectory audit.** Reads agent session logs and flags shortcut information channels:
  reading git history for the original patch, editing CI config, `--no-verify` commits.

## Design commitments

**Precision over recall.** A gate that cries wolf is switched off within a week, and a
switched-off gate catches nothing. CI enforces ≥95% precision on the core rules against a
corpus of real cheating diffs. Missing a detection is a bug; inventing one is a defect in
the product's premise.

**No LLM in the hot path.** The deterministic rules are AST comparisons. They are fast,
reproducible, and free — the gate must never become the new merge-queue bottleneck.

**Complementary, not competitive.** Ratchet is not a better CodeRabbit. Run both.

## Status

Under active development. See `.ratchet.yml` for configuration and `CONTRIBUTING.md` for
the rule-authoring contract.

## License

Apache-2.0
