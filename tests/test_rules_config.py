"""Tests for the config-reading rules: VID009 and VID010, plus discovery.

Both rules are pure functions of `RuleContext`, so every case here is built
from string literals — no git, no fixtures on disk, no filesystem access.
`make_change` derives realistic `Hunk`s (correct 1-indexed line numbers on
both sides) from a before/after string pair with `difflib`, the same way a
real diff would, so evidence-line assertions exercise the real code path
rather than a hand-picked shortcut.
"""

from __future__ import annotations

import difflib

from ratchet.contracts import (
    ChangeKind,
    ChangeSet,
    FileChange,
    Finding,
    Hunk,
    RatchetConfig,
    RuleContext,
    RuleSetting,
    Severity,
)
from ratchet.rules.discovery import discover_rules
from ratchet.rules.vid009_ci_threshold_lowered import CIThresholdLowered
from ratchet.rules.vid010_test_excluded import TestExcludedViaConfig


def make_change(
    path: str, base: str, head: str, *, kind: ChangeKind = ChangeKind.MODIFIED
) -> FileChange:
    """Build a `FileChange` with real hunks from a before/after content pair."""
    base_lines = base.splitlines()
    head_lines = head.splitlines()
    matcher = difflib.SequenceMatcher(a=base_lines, b=head_lines, autojunk=False)
    hunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = tuple((i + 1, base_lines[i]) for i in range(i1, i2))
        added = tuple((j + 1, head_lines[j]) for j in range(j1, j2))
        hunks.append(
            Hunk(
                base_start=i1 + 1,
                base_lines=i2 - i1,
                head_start=j1 + 1,
                head_lines=j2 - j1,
                added=added,
                removed=removed,
            )
        )
    return FileChange(
        path=path, kind=kind, base_content=base, head_content=head, hunks=tuple(hunks)
    )


def ctx_for(change: FileChange, *, config: RatchetConfig | None = None) -> RuleContext:
    return RuleContext(
        changes=ChangeSet(changes=(change,)), config=config or RatchetConfig.default()
    )


def disabled_config(rule_id: str) -> RatchetConfig:
    return RatchetConfig(rules={rule_id: RuleSetting(enabled=False)})


class TestDiscovery:
    def test_finds_both_config_rules(self) -> None:
        # Discovery walks the package rather than an edited import list — this
        # is the guarantee that makes that safe.
        ids = {rule.id for rule in discover_rules()}
        assert {"VID009", "VID010"} <= ids

    def test_skips_itself_and_stays_importable_twice(self) -> None:
        # Re-running discovery must not explode just because the modules are
        # already imported (Python no-ops a repeat import).
        first = discover_rules()
        second = discover_rules()
        assert first == second


class TestCIThresholdLowered:
    rule = CIThresholdLowered()

    def test_coverage_fail_under_lowered_fires(self) -> None:
        change = make_change(
            "pyproject.toml",
            "[tool.coverage.report]\nfail_under = 90\n",
            "[tool.coverage.report]\nfail_under = 60\n",
        )
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.rule_id == "VID009"
        assert finding.severity is Severity.HIGH
        assert [e.side for e in finding.evidence] == ["base", "head"]
        assert finding.evidence[1].line == 2

    def test_coverage_fail_under_raised_does_not_fire(self) -> None:
        # The inverse of the true positive: the gate got *stricter*.
        change = make_change(
            "pyproject.toml",
            "[tool.coverage.report]\nfail_under = 60\n",
            "[tool.coverage.report]\nfail_under = 90\n",
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_cov_fail_under_flag_lowered_fires(self) -> None:
        change = make_change(
            "pytest.ini",
            "[pytest]\naddopts = --cov-fail-under=85\n",
            "[pytest]\naddopts = --cov-fail-under=40\n",
        )
        findings = self.rule.check(ctx_for(change))
        assert len(findings) == 1
        assert "85" in findings[0].detail and "40" in findings[0].detail

    def test_jest_coverage_threshold_lowered_fires(self) -> None:
        change = make_change(
            "jest.config.js",
            "module.exports = {\n  coverageThreshold: {\n    global: {\n      lines: 80,\n    },\n  },\n};\n",
            "module.exports = {\n  coverageThreshold: {\n    global: {\n      lines: 10,\n    },\n  },\n};\n",
        )
        findings = self.rule.check(ctx_for(change))
        assert len(findings) == 1
        assert "coverageThreshold" in findings[0].detail
        assert findings[0].evidence[1].snippet == "lines: 10,"

    def test_ambiguous_double_edit_does_not_fire(self) -> None:
        # Two edits to the same key in one diff are ambiguous — precision
        # over recall means staying quiet rather than guessing which pairs up.
        change = make_change(
            "pyproject.toml",
            "fail_under = 50\nfail_under = 60\n",
            "fail_under = 10\nfail_under = 20\n",
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_malformed_config_yields_no_findings_and_does_not_raise(self) -> None:
        # `fail_under 60` (no `=`) never matches the pattern at all; a rule
        # that has to *parse* TOML/YAML would choke on this, ratchet's
        # regex-based read of it just sees nothing to report.
        change = make_change(
            "pyproject.toml",
            "[tool.coverage.report\nfail_under 90\n",
            "[tool.coverage.report\nfail_under 60\nbroken >>> {{{\n",
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_disabled_rule_produces_nothing(self) -> None:
        change = make_change(
            "pyproject.toml",
            "fail_under = 90\n",
            "fail_under = 60\n",
        )
        ctx = ctx_for(change, config=disabled_config("VID009"))
        assert self.rule.apply(ctx) == ()

    def test_continue_on_error_added_fires(self) -> None:
        base = "name: CI\njobs:\n  test:\n    steps:\n      - run: pytest\n"
        head = base + "        continue-on-error: true\n"
        change = make_change(".github/workflows/ci.yml", base, head)
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.title == "`continue-on-error: true` added"

    def test_continue_on_error_false_does_not_fire(self) -> None:
        base = "name: CI\njobs:\n  test:\n    steps:\n      - run: pytest\n"
        head = base + "        continue-on-error: false\n"
        change = make_change(".github/workflows/ci.yml", base, head)
        assert self.rule.check(ctx_for(change)) == []

    def test_no_verify_added_fires(self) -> None:
        change = make_change("Makefile", "test:\n\tpytest\n", "test:\n\tpytest --no-verify\n")
        findings = self.rule.check(ctx_for(change))
        assert any(f.title.startswith("`--no-verify`") for f in findings)

    def test_husky_zero_added_fires(self) -> None:
        change = make_change(
            "package.json",
            '{\n  "scripts": {\n    "commit": "git commit"\n  }\n}\n',
            '{\n  "scripts": {\n    "commit": "HUSKY=0 git commit"\n  }\n}\n',
        )
        findings = self.rule.check(ctx_for(change))
        assert any("HUSKY=0" in f.title for f in findings)

    def test_mypy_strict_downgraded_fires(self) -> None:
        change = make_change("mypy.ini", "[mypy]\nstrict = True\n", "[mypy]\nstrict = False\n")
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.title == "mypy `strict` downgraded"

    def test_mypy_strict_left_true_does_not_fire(self) -> None:
        change = make_change(
            "mypy.ini",
            "[mypy]\nstrict = True\nwarn_unused = 1\n",
            "[mypy]\nstrict = True\nwarn_unused = 2\n",
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_exit_zero_added_fires(self) -> None:
        change = make_change(
            "Makefile", "lint:\n\truff check .\n", "lint:\n\truff check . --exit-zero\n"
        )
        findings = self.rule.check(ctx_for(change))
        assert any("--exit-zero" in f.title for f in findings)

    def test_or_true_appended_to_existing_command_fires(self) -> None:
        change = make_change("Makefile", "test:\n\tpytest\n", "test:\n\tpytest || true\n")
        findings = self.rule.check(ctx_for(change))
        assert any(f.title == "`|| true` appended to a check command" for f in findings)

    def test_or_true_on_a_brand_new_command_does_not_fire(self) -> None:
        # The base command never existed before, so this isn't a command that
        # used to be able to fail and no longer can — nothing was weakened.
        change = make_change(
            "Makefile", "test:\n\tpytest\n", "test:\n\tpytest\nlint:\n\truff check . || true\n"
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_timeout_raised_substantially_fires(self) -> None:
        change = make_change(
            ".github/workflows/ci.yml",
            "jobs:\n  test:\n    timeout-minutes: 10\n",
            "jobs:\n  test:\n    timeout-minutes: 30\n",
        )
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.title == "Test timeout raised substantially"

    def test_timeout_raised_slightly_does_not_fire(self) -> None:
        # Under the 2x bar — ordinary flake tolerance, not a defeated gate.
        change = make_change(
            ".github/workflows/ci.yml",
            "jobs:\n  test:\n    timeout-minutes: 10\n",
            "jobs:\n  test:\n    timeout-minutes: 12\n",
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_retry_wrapper_around_test_step_fires(self) -> None:
        base = "jobs:\n  test:\n    steps:\n      - name: run tests\n        run: pytest\n"
        head = (
            "jobs:\n  test:\n    steps:\n      - name: run tests\n"
            "        uses: nick-fields/retry@v2\n        with:\n"
            "          max_attempts: 3\n          command: pytest\n"
        )
        change = make_change(".github/workflows/ci.yml", base, head)
        findings = self.rule.check(ctx_for(change))
        assert any(f.title == "Retry wrapper added around a test step" for f in findings)

    def test_retry_wrapper_around_non_test_step_does_not_fire(self) -> None:
        base = (
            "jobs:\n  deploy:\n    steps:\n      - name: push image\n        run: docker push app\n"
        )
        head = (
            "jobs:\n  deploy:\n    steps:\n      - name: push image\n"
            "        uses: nick-fields/retry@v2\n        with:\n"
            "          max_attempts: 3\n          command: docker push app\n"
        )
        change = make_change(".github/workflows/ci.yml", base, head)
        assert self.rule.check(ctx_for(change)) == []

    def test_file_outside_scope_is_ignored(self) -> None:
        change = make_change("src/app.py", "fail_under = 90\n", "fail_under = 10\n")
        assert self.rule.check(ctx_for(change)) == []


class TestTestExcludedViaConfig:
    rule = TestExcludedViaConfig()

    def test_pytest_ignore_flag_added_for_a_test_path_fires(self) -> None:
        change = make_change(
            "pytest.ini",
            "[pytest]\naddopts = -q\n",
            "[pytest]\naddopts = -q --ignore=tests/test_flaky.py\n",
        )
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.rule_id == "VID010"
        assert finding.severity is Severity.HIGH
        assert "tests/test_flaky.py" in finding.detail

    def test_pytest_ignore_flag_for_non_test_dir_does_not_fire(self) -> None:
        # `--ignore=` is routine housekeeping too (migrations, vendored code);
        # only a plausibly test-shaped path is worth flagging.
        change = make_change(
            "pytest.ini",
            "[pytest]\naddopts = -q\n",
            "[pytest]\naddopts = -q --ignore=migrations\n",
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_norecursedirs_gains_a_test_directory_fires(self) -> None:
        change = make_change(
            "pyproject.toml",
            '[tool.pytest.ini_options]\nnorecursedirs = ["build"]\n',
            '[tool.pytest.ini_options]\nnorecursedirs = ["build", "tests/slow"]\n',
        )
        findings = self.rule.check(ctx_for(change))
        assert any("norecursedirs" in f.detail for f in findings)

    def test_norecursedirs_losing_an_entry_does_not_fire(self) -> None:
        # A removal from an *exclusion* list means more gets collected, not
        # less — the opposite of what this rule polices.
        change = make_change(
            "pyproject.toml",
            '[tool.pytest.ini_options]\nnorecursedirs = ["build", "tests/slow"]\n',
            '[tool.pytest.ini_options]\nnorecursedirs = ["build"]\n',
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_testpaths_narrowed_fires(self) -> None:
        change = make_change(
            "pyproject.toml",
            '[tool.pytest.ini_options]\ntestpaths = ["tests", "integration_tests"]\n',
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        )
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.title == "`testpaths` narrowed"
        assert "integration_tests" in finding.detail

    def test_testpaths_widened_does_not_fire(self) -> None:
        change = make_change(
            "pyproject.toml",
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            '[tool.pytest.ini_options]\ntestpaths = ["tests", "integration_tests"]\n',
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_collect_ignore_addition_fires(self) -> None:
        change = make_change(
            "conftest.py",
            "collect_ignore = []\n",
            'collect_ignore = ["test_legacy.py"]\n',
        )
        findings = self.rule.check(ctx_for(change))
        assert any("collect_ignore" in f.detail for f in findings)

    def test_jest_test_path_ignore_patterns_addition_fires(self) -> None:
        change = make_change(
            "jest.config.js",
            "module.exports = {\n  testPathIgnorePatterns: ['/node_modules/'],\n};\n",
            "module.exports = {\n  testPathIgnorePatterns: ['/node_modules/', 'test_checkout'],\n};\n",
        )
        findings = self.rule.check(ctx_for(change))
        assert any("test_checkout" in f.detail for f in findings)

    def test_jest_test_match_narrowed_fires(self) -> None:
        change = make_change(
            "jest.config.js",
            "module.exports = {\n  testMatch: ['**/*.test.js', '**/*.spec.js'],\n};\n",
            "module.exports = {\n  testMatch: ['**/*.test.js'],\n};\n",
        )
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.title == "`testMatch` narrowed"

    def test_coverage_omit_addition_for_a_test_file_fires(self) -> None:
        change = make_change(
            ".coveragerc",
            "[run]\nomit = src/legacy.py\n",
            "[run]\nomit = src/legacy.py, tests/test_billing.py\n",
        )
        findings = self.rule.check(ctx_for(change))
        assert any("omit" in f.detail for f in findings)

    def test_exclude_lines_targeting_tests_fires(self) -> None:
        change = make_change(
            "pyproject.toml",
            '[tool.coverage.report]\nexclude_lines = ["pragma: no cover"]\n',
            '[tool.coverage.report]\nexclude_lines = ["pragma: no cover", "def test_.*"]\n',
        )
        findings = self.rule.check(ctx_for(change))
        assert any("exclude_lines" in f.detail for f in findings)

    def test_exclude_lines_ordinary_boilerplate_does_not_fire(self) -> None:
        # `pragma: no cover` / `TYPE_CHECKING` are extremely common, legitimate
        # exclusions — only a pattern that looks aimed at tests is suspicious.
        change = make_change(
            "pyproject.toml",
            '[tool.coverage.report]\nexclude_lines = ["pragma: no cover"]\n',
            '[tool.coverage.report]\nexclude_lines = ["pragma: no cover", "if TYPE_CHECKING:"]\n',
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_gitignore_addition_matching_test_globs_fires(self) -> None:
        change = make_change(".gitignore", "*.log\n", "*.log\ntests/test_flaky.py\n")
        (finding,) = self.rule.check(ctx_for(change))
        assert finding.title == "Test path added to `.gitignore`"

    def test_gitignore_addition_not_matching_test_globs_does_not_fire(self) -> None:
        change = make_change(".gitignore", "*.log\n", "*.log\nbuild/\n")
        assert self.rule.check(ctx_for(change)) == []

    def test_malformed_array_yields_no_findings_and_does_not_raise(self) -> None:
        # An unterminated `[` — the array never closes — is left unrecognised
        # rather than guessed at.
        change = make_change(
            "pyproject.toml",
            '[tool.pytest.ini_options]\nnorecursedirs = ["build"]\n',
            '[tool.pytest.ini_options]\nnorecursedirs = ["build", "tests/slow"\n',
        )
        assert self.rule.check(ctx_for(change)) == []

    def test_disabled_rule_produces_nothing(self) -> None:
        change = make_change(".gitignore", "*.log\n", "*.log\ntests/test_flaky.py\n")
        ctx = ctx_for(change, config=disabled_config("VID010"))
        assert self.rule.apply(ctx) == ()

    def test_file_outside_scope_is_ignored(self) -> None:
        # `norecursedirs` growing in a random text file is not a pytest config.
        change = make_change(
            "notes.txt",
            'norecursedirs = ["build"]\n',
            'norecursedirs = ["build", "tests/slow"]\n',
        )
        assert self.rule.check(ctx_for(change)) == []


def test_rule_findings_are_finding_instances() -> None:
    # Sanity check that `self.finding(...)` was used throughout rather than
    # a hand-built `Finding`, so config overrides for severity/penalty apply.
    change = make_change("pyproject.toml", "fail_under = 90\n", "fail_under = 10\n")
    ctx = RuleContext(
        changes=ChangeSet(changes=(change,)),
        config=RatchetConfig(rules={"VID009": RuleSetting(severity=Severity.CRITICAL, penalty=42)}),
    )
    (finding,) = CIThresholdLowered().apply(ctx)
    assert isinstance(finding, Finding)
    assert finding.severity is Severity.CRITICAL
    assert finding.penalty == 42
