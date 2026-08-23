"""Tests for the frozen contracts.

These are load-bearing beyond their own correctness: every work package is
written against this module, so a silent behaviour change here breaks rules
written by people who never read this file. The assertions below are the
written-down version of what those authors are entitled to assume.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ratchet.contracts import (
    Assertion,
    AssertionKind,
    ChangeKind,
    ChangeSet,
    Evidence,
    FileChange,
    Finding,
    Hunk,
    RatchetConfig,
    RuleBase,
    RuleContext,
    RuleSetting,
    Severity,
    SkipMarker,
    SkipReason,
    TestCase,
    TestSurface,
    TrustScore,
    is_test_path,
    matches_glob,
    pair_tests,
    sort_findings,
)


def make_test(
    name: str,
    *,
    assertions: tuple[Assertion, ...] = (),
    skips: tuple[SkipMarker, ...] = (),
    discoverable: bool = True,
) -> TestCase:
    return TestCase(
        id=f"tests/test_x.py::{name}",
        name=name,
        qualname=name,
        line_start=1,
        line_end=10,
        is_discoverable=discoverable,
        assertions=assertions,
        skip_markers=skips,
    )


def equality(line: int = 1, *operands: str) -> Assertion:
    return Assertion(
        kind=AssertionKind.EQUALITY,
        callee="assertEqual",
        line=line,
        operands=operands or ("actual", "expected"),
    )


class TestAssertionStrength:
    def test_every_kind_is_ranked(self) -> None:
        # A rule comparing strengths must never hit a KeyError mid-review.
        for kind in AssertionKind:
            assert isinstance(kind.strength, int)

    def test_equality_outranks_truthiness_outranks_existence(self) -> None:
        # This ordering is the entire basis of VID005.
        assert (
            AssertionKind.EQUALITY.strength
            > AssertionKind.TRUTHINESS.strength
            > AssertionKind.EXISTENCE.strength
        )

    def test_unknown_sits_mid_range(self) -> None:
        # An unrecognised assertion must not read as a weakening on its own,
        # or every unsupported framework becomes a wall of false positives.
        assert (
            AssertionKind.EXISTENCE.strength
            < AssertionKind.UNKNOWN.strength
            < AssertionKind.EQUALITY.strength
        )

    def test_signature_ignores_line_but_not_operands(self) -> None:
        # Unrelated edits shift lines constantly; pairing must survive that.
        assert equality(1, "a", "b").signature() == equality(99, "a", "b").signature()
        assert equality(1, "a", "b").signature() != equality(1, "a", "c").signature()


class TestTestCase:
    def test_total_strength_sums_assertions(self) -> None:
        case = make_test("t", assertions=(equality(1), equality(2)))
        assert case.total_strength == 2 * AssertionKind.EQUALITY.strength

    def test_skip_marks_test_as_not_running(self) -> None:
        case = make_test("t", skips=(SkipMarker(reason=SkipReason.SKIP, line=3),))
        assert case.is_skipped
        assert not case.will_run

    def test_exclusive_focus_is_not_a_skip_of_itself(self) -> None:
        # `.only` silences siblings; the focused test itself still runs.
        case = make_test("t", skips=(SkipMarker(reason=SkipReason.EXCLUSIVE_FOCUS, line=3),))
        assert not case.is_skipped
        assert case.will_run

    def test_undiscoverable_test_does_not_run(self) -> None:
        assert not make_test("t", discoverable=False).will_run


class TestTestSurface:
    def test_total_strength_excludes_tests_that_will_not_run(self) -> None:
        running = make_test("runs", assertions=(equality(),))
        skipped = TestCase(
            id="tests/test_x.py::skipped",
            name="skipped",
            qualname="skipped",
            line_start=1,
            line_end=2,
            assertions=(equality(),),
            skip_markers=(SkipMarker(reason=SkipReason.SKIP, line=1),),
        )
        surface = TestSurface(
            path="tests/test_x.py",
            language="python",
            framework="pytest",
            tests=(running, skipped),
        )
        # Both tests contribute assertions, but only one contributes strength —
        # that gap is what makes adding a skip register as a loss.
        assert surface.assertion_count == 2
        assert surface.total_strength == AssertionKind.EQUALITY.strength

    def test_by_id_is_memoized_on_a_frozen_instance(self) -> None:
        surface = TestSurface(
            path="p", language="python", framework="pytest", tests=(make_test("t"),)
        )
        assert surface.by_id is surface.by_id

    def test_unparsed_is_distinguishable_from_empty(self) -> None:
        # Rules must never read a parse failure as "the tests were deleted".
        empty = TestSurface.empty("tests/test_x.py")
        broken = TestSurface.unparsed("tests/test_x.py", "syntax error")
        assert empty.parse_ok and not empty.tests
        assert not broken.parse_ok and broken.parse_error == "syntax error"


class TestPairTests:
    def test_matches_by_id_and_reports_removals_and_additions(self) -> None:
        base = TestSurface(
            path="p",
            language="python",
            framework="pytest",
            tests=(make_test("kept"), make_test("gone")),
        )
        head = TestSurface(
            path="p",
            language="python",
            framework="pytest",
            tests=(make_test("kept"), make_test("new")),
        )
        pairs = {
            (p.base.name if p.base else None, p.head.name if p.head else None)
            for p in pair_tests(base, head)
        }
        assert pairs == {("kept", "kept"), ("gone", None), (None, "new")}

    def test_strength_delta_is_negative_when_assertions_are_dropped(self) -> None:
        base = TestSurface(
            path="p",
            language="python",
            framework="pytest",
            tests=(make_test("t", assertions=(equality(1), equality(2))),),
        )
        head = TestSurface(
            path="p",
            language="python",
            framework="pytest",
            tests=(make_test("t", assertions=(equality(1),)),),
        )
        (pair,) = pair_tests(base, head)
        assert pair.strength_delta == -AssertionKind.EQUALITY.strength


class TestFinding:
    def test_justification_zeroes_the_penalty_but_keeps_the_record(self) -> None:
        finding = Finding(
            rule_id="VID001",
            severity=Severity.HIGH,
            title="Test removed",
            detail="",
            path="tests/test_x.py",
            penalty=25,
        )
        accepted = finding.with_justification("legacy exporter deleted in #482")

        assert finding.effective_penalty == 25
        assert accepted.effective_penalty == 0
        assert accepted.justified
        # The evidence survives acceptance — the audit trail is the point.
        assert accepted.severity is Severity.HIGH
        assert accepted.penalty == 25

    def test_evidence_rejects_zero_indexed_lines(self) -> None:
        with pytest.raises(ValueError, match="1-indexed"):
            Evidence(path="a.py", line=0, side="head", snippet="")

    def test_negative_penalty_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            Finding(
                rule_id="X",
                severity=Severity.LOW,
                title="",
                detail="",
                path="a",
                penalty=-1,
            )

    def test_sort_is_severity_first_then_stable(self) -> None:
        low = Finding(
            rule_id="VID009",
            severity=Severity.LOW,
            title="",
            detail="",
            path="b",
            penalty=1,
        )
        critical = Finding(
            rule_id="VID003",
            severity=Severity.CRITICAL,
            title="",
            detail="",
            path="a",
            penalty=1,
        )
        assert sort_findings([low, critical]) == [critical, low]


class TestGlobMatching:
    @pytest.mark.parametrize(
        ("path", "pattern", "expected"),
        [
            # `**/` must match zero directories, so root-level tests are caught.
            ("test_x.py", "**/test_*.py", True),
            ("a/b/test_x.py", "**/test_*.py", True),
            # `*` must not cross a separator — this is why fnmatch is unusable.
            ("src/a/b.py", "src/*.py", False),
            ("src/b.py", "src/*.py", True),
            ("a/tests/deep/t.py", "**/tests/**/*.py", True),
            ("src/main.py", "**/test_*.py", False),
            ("app/foo.spec.ts", "**/*.spec.ts", True),
        ],
    )
    def test_glob_semantics(self, path: str, pattern: str, expected: bool) -> None:
        assert matches_glob(path, pattern) is expected

    def test_ignore_globs_win_over_test_globs(self) -> None:
        config = RatchetConfig(ignore_globs=["**/fixtures/**"])
        assert is_test_path("tests/test_a.py", config)
        assert not is_test_path("tests/fixtures/test_a.py", config)


class TestConfig:
    def test_unknown_version_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unsupported"):
            RatchetConfig(version=2)

    def test_unknown_keys_are_rejected(self) -> None:
        # A typo'd key must fail loudly rather than silently disable a rule.
        with pytest.raises(ValidationError):
            RatchetConfig(fail_undr=50)  # type: ignore[call-arg]

    def test_penalty_cannot_exceed_the_trust_budget(self) -> None:
        with pytest.raises(ValidationError, match="100-point"):
            RuleSetting(penalty=101)

    def test_overrides_fall_back_to_rule_defaults(self) -> None:
        config = RatchetConfig(rules={"VID001": RuleSetting(severity=Severity.LOW)})
        assert config.severity_for("VID001", Severity.HIGH) is Severity.LOW
        assert config.penalty_for("VID001", 25) == 25
        assert config.severity_for("VID999", Severity.HIGH) is Severity.HIGH

    def test_oracle_is_opt_in(self) -> None:
        assert RatchetConfig.default().oracle.enabled is False


class TestTrustScore:
    def test_bands(self) -> None:
        assert TrustScore(value=95).band == "trusted"
        assert TrustScore(value=75).band == "acceptable"
        assert TrustScore(value=50).band == "suspect"
        assert TrustScore(value=10).band == "untrusted"

    def test_threshold_drives_pass(self) -> None:
        assert TrustScore(value=70, threshold=70).passed
        assert not TrustScore(value=69, threshold=70).passed

    def test_out_of_range_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            TrustScore(value=101)

    def test_justified_findings_do_not_set_worst_severity(self) -> None:
        finding = Finding(
            rule_id="VID001",
            severity=Severity.CRITICAL,
            title="",
            detail="",
            path="a",
            penalty=30,
        ).with_justification("accepted")
        score = TrustScore(value=100, findings=(finding,))
        assert score.worst_severity is None
        assert score.justified == (finding,)


class TestFileChange:
    def test_line_lookup_is_one_indexed_and_bounds_safe(self) -> None:
        change = FileChange(
            path="a.py",
            kind=ChangeKind.MODIFIED,
            head_content="first\nsecond\n",
            base_content="first\n",
        )
        assert change.head_line(1) == "first"
        assert change.head_line(2) == "second"
        assert change.head_line(99) == ""
        assert change.base_line(2) == ""

    def test_added_and_removed_lines_flatten_across_hunks(self) -> None:
        change = FileChange(
            path="a.py",
            kind=ChangeKind.MODIFIED,
            hunks=(
                Hunk(1, 1, 1, 1, added=((1, "a"),), removed=((1, "x"),)),
                Hunk(9, 1, 9, 1, added=((9, "b"),), removed=()),
            ),
        )
        assert change.added_lines == ((1, "a"), (9, "b"))
        assert change.removed_lines == ((1, "x"),)
        assert change.added_text == "a\nb"


class TestRuleBase:
    def test_subclass_registers_itself_and_honours_config(self) -> None:
        class ExampleRule(RuleBase):
            id = "VIDTEST"
            name = "example"
            default_severity = Severity.HIGH
            default_penalty = 20

            def check(self, ctx: RuleContext) -> list[Finding]:
                return [self.finding(ctx, title="t", detail="d", path="a.py", evidence=())]

        from ratchet.contracts import get_rule

        assert get_rule("VIDTEST") is ExampleRule

        rule = ExampleRule()
        ctx = RuleContext(changes=ChangeSet())
        (finding,) = rule.apply(ctx)
        assert finding.severity is Severity.HIGH
        assert finding.penalty == 20

        # A disabled rule must produce nothing at all, not a zero-penalty finding.
        disabled = RuleContext(
            changes=ChangeSet(),
            config=RatchetConfig(rules={"VIDTEST": RuleSetting(enabled=False)}),
        )
        assert rule.apply(disabled) == ()

    def test_rule_without_an_id_is_a_definition_time_error(self) -> None:
        with pytest.raises(TypeError, match="rule id"):

            class Broken(RuleBase):  # pyright: ignore[reportUnusedClass]
                name = "broken"

                def check(self, ctx: RuleContext) -> list[Finding]:
                    return []

    def test_context_partitions_test_and_non_test_files(self) -> None:
        ctx = RuleContext(
            changes=ChangeSet(
                changes=(
                    FileChange(path="tests/test_a.py", kind=ChangeKind.MODIFIED),
                    FileChange(path="src/app.py", kind=ChangeKind.MODIFIED),
                    FileChange(path="logo.png", kind=ChangeKind.MODIFIED, is_binary=True),
                )
            )
        )
        assert [c.path for c in ctx.test_files()] == ["tests/test_a.py"]
        assert [c.path for c in ctx.non_test_files()] == ["src/app.py"]
