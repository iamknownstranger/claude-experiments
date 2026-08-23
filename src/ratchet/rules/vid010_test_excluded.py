"""VID010 — a test still exists, but a config change stopped it from running.

Deleting a test file is loud: it shows up as a deletion in the diff and
VID001 catches it. Excluding it from discovery is quiet — the file sits in
the repo, green in every listing, while `--ignore=`, `norecursedirs`,
`testPathIgnorePatterns`, or a new `.gitignore` line steer the runner around
it. Nothing here needs an AST; these are collection/exclusion settings in
config files, read as text.

The list-valued settings (`norecursedirs`, `omit`, `testPathIgnorePatterns`,
...) are compared as sets extracted from the *whole* file on each side
(`_list_items`), not from the line-level diff. That is deliberate: an
exclusion list frequently gets reformatted (reordered, rewrapped) in the same
commit that adds one real entry, and diffing lines would either miss the
addition or misreport which line it lives on. Comparing sets gets the
semantics right; a second text search on the head side recovers a real line
number for evidence. Per CONTRIBUTING's precision rule, anything this can't
confidently parse — an unterminated array, an unrecognised shape — is left
alone rather than guessed at.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ratchet.contracts import (
    Evidence,
    FileChange,
    Finding,
    RuleBase,
    RuleContext,
    Severity,
    matches_any,
    matches_glob,
)

_PYTEST_CONFIG_GLOBS: tuple[str, ...] = (
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
)
_CONFTEST_GLOB = "**/conftest.py"
_JS_CONFIG_GLOBS: tuple[str, ...] = ("jest.config.*", "vitest.config.*", "package.json")
_COVERAGE_CONFIG_GLOBS: tuple[str, ...] = (".coveragerc", "pyproject.toml", "setup.cfg")
_GITIGNORE_GLOBS: tuple[str, ...] = (".gitignore", "**/.gitignore")

_PYTEST_IGNORE_FLAG = re.compile(r"--ignore=(?P<path>\S+)")

_TOKEN = re.compile(r'"([^"]*)"|\'([^\']*)\'|([A-Za-z0-9_.\-/*]+)')


def _key_regex(key: str) -> re.Pattern[str]:
    return re.compile(rf"""["']?\b{re.escape(key)}\b["']?\s*[:=]""")


def _closing_bracket(lines: list[str], start: int, first_line: str) -> tuple[str, int] | None:
    """Join lines from `start` until bracket depth returns to zero."""
    depth = 0
    collected: list[str] = []
    for i in range(start, len(lines)):
        text = first_line if i == start else lines[i]
        depth += text.count("[") - text.count("]")
        collected.append(text)
        if depth <= 0:
            return "\n".join(collected), i
    return None  # unterminated array — malformed, report nothing


def _tokenize(text: str) -> frozenset[str]:
    items: set[str] = set()
    for match in _TOKEN.finditer(text):
        value = next((g for g in match.groups() if g is not None), None)
        if value:
            items.add(value)
    return frozenset(items)


def _list_items(content: str, key: str) -> frozenset[str] | None:
    """The item set of a `key = [...]` array or a single-line ini-style list.

    Returns `None` when the key is absent, or its value takes a shape this
    does not recognise (a multi-line flat list, an unterminated array) —
    both cases the caller must treat as "nothing to compare" rather than an
    empty list, or a reformatted-but-unchanged file would look like a full
    removal.
    """
    lines = content.splitlines()
    pattern = _key_regex(key)
    for i, line in enumerate(lines):
        match = pattern.search(line)
        if match is None:
            continue
        rest = line[match.end() :]
        if "[" in rest:
            block = _closing_bracket(lines, i, rest)
        elif i + 1 < len(lines) and lines[i + 1].lstrip().startswith("["):
            block = _closing_bracket(lines, i + 1, lines[i + 1])
        else:
            block = (rest, i)  # single-line flat ini list
        if block is None:
            return None
        return _tokenize(block[0])
    return None


def _locate(content: str, token: str) -> int | None:
    """First 1-indexed line containing `token`, quoted or bare."""
    needles = (f'"{token}"', f"'{token}'", token)
    for i, line in enumerate(content.splitlines(), start=1):
        if any(needle in line for needle in needles):
            return i
    return None


def _looks_test_related(item: str, test_globs: Sequence[str]) -> bool:
    """Precision guard: only flag exclusions that plausibly target tests.

    `norecursedirs`/`omit`/`--ignore` are also used for perfectly ordinary
    housekeeping (`migrations`, `node_modules`, `build`); flagging every
    addition would swamp real findings in noise. Requiring the item to look
    test-shaped keeps the rule quiet on those.
    """
    lowered = item.lower()
    if "test" in lowered or "spec" in lowered:
        return True
    return matches_any(item, tuple(test_globs))


class TestExcludedViaConfig(RuleBase):
    """A test file still exists but a config change stopped it from running."""

    id = "VID010"
    name = "Test file excluded via config"
    description = "A test file was newly excluded from discovery, collection, or coverage."
    default_severity = Severity.HIGH
    default_penalty = 20
    requires_ast = False

    def check(self, ctx: RuleContext) -> Sequence[Finding]:
        findings: list[Finding] = []
        for change in ctx.changes.changes:
            if change.is_binary:
                continue
            findings.extend(self._gitignore_addition(ctx, change))
            if matches_any(change.path, _PYTEST_CONFIG_GLOBS) or matches_glob(
                change.path, _CONFTEST_GLOB
            ):
                findings.extend(self._pytest_exclusions(ctx, change))
            if matches_any(change.path, _JS_CONFIG_GLOBS):
                findings.extend(self._js_exclusions(ctx, change))
            if matches_any(change.path, _COVERAGE_CONFIG_GLOBS):
                findings.extend(self._coverage_exclusions(ctx, change))
        return findings

    def _list_addition_findings(
        self,
        ctx: RuleContext,
        change: FileChange,
        key: str,
        *,
        title: str,
        detail: str,
        filter_test_related: bool = True,
    ) -> list[Finding]:
        if change.base_content is None or change.head_content is None:
            return []
        head_items = _list_items(change.head_content, key)
        if not head_items:
            return []
        base_items = _list_items(change.base_content, key) or frozenset()
        added = head_items - base_items
        findings: list[Finding] = []
        for item in sorted(added):
            if filter_test_related and not _looks_test_related(item, ctx.config.test_globs):
                continue
            line = _locate(change.head_content, item)
            if line is None:
                continue
            findings.append(
                self.finding(
                    ctx,
                    title=title,
                    detail=detail.format(item=item, path=change.path, key=key),
                    path=change.path,
                    evidence=(Evidence(path=change.path, line=line, side="head", snippet=item),),
                )
            )
        return findings

    def _list_removal_findings(
        self,
        ctx: RuleContext,
        change: FileChange,
        key: str,
        *,
        title: str,
        detail: str,
    ) -> list[Finding]:
        """For inclusion lists (`testpaths`, `testMatch`) — narrowing excludes tests too."""
        if change.base_content is None or change.head_content is None:
            return []
        base_items = _list_items(change.base_content, key)
        if not base_items:
            return []
        head_items = _list_items(change.head_content, key) or frozenset()
        removed = base_items - head_items
        findings: list[Finding] = []
        for item in sorted(removed):
            line = _locate(change.base_content, item)
            if line is None:
                continue
            findings.append(
                self.finding(
                    ctx,
                    title=title,
                    detail=detail.format(item=item, path=change.path, key=key),
                    path=change.path,
                    evidence=(Evidence(path=change.path, line=line, side="base", snippet=item),),
                )
            )
        return findings

    def _pytest_exclusions(self, ctx: RuleContext, change: FileChange) -> list[Finding]:
        findings: list[Finding] = []

        removed_text = "\n".join(text for _, text in change.removed_lines)
        for line_no, text in change.added_lines:
            for match in _PYTEST_IGNORE_FLAG.finditer(text):
                path = match.group("path")
                if match.group(0) in removed_text:
                    continue  # same flag survived a reformat, not a new exclusion
                if not _looks_test_related(path, ctx.config.test_globs):
                    continue
                findings.append(
                    self.finding(
                        ctx,
                        title="Test path newly ignored by pytest",
                        detail=f"`--ignore={path}` was added in {change.path}.",
                        path=change.path,
                        evidence=(
                            Evidence(
                                path=change.path,
                                line=line_no,
                                side="head",
                                snippet=text.strip(),
                            ),
                        ),
                    )
                )

        findings.extend(
            self._list_addition_findings(
                ctx,
                change,
                "norecursedirs",
                title="Test directory added to `norecursedirs`",
                detail="`{item}` was added to `norecursedirs` in {path}, so pytest skips it.",
            )
        )
        findings.extend(
            self._list_addition_findings(
                ctx,
                change,
                "collect_ignore",
                title="Test file added to `collect_ignore`",
                detail="`{item}` was added to `collect_ignore` in {path}.",
            )
        )
        findings.extend(
            self._list_removal_findings(
                ctx,
                change,
                "testpaths",
                title="`testpaths` narrowed",
                detail="`{item}` was dropped from `testpaths` in {path}; pytest no longer discovers it.",
            )
        )
        return findings

    def _js_exclusions(self, ctx: RuleContext, change: FileChange) -> list[Finding]:
        findings: list[Finding] = []
        for key in ("testPathIgnorePatterns", "exclude"):
            findings.extend(
                self._list_addition_findings(
                    ctx,
                    change,
                    key,
                    title="Test path newly excluded",
                    detail="`{item}` was added to `{key}` in {path}.",
                )
            )
        findings.extend(
            self._list_removal_findings(
                ctx,
                change,
                "testMatch",
                title="`testMatch` narrowed",
                detail="`{item}` was dropped from `testMatch` in {path}; matching tests stop running.",
            )
        )
        return findings

    def _coverage_exclusions(self, ctx: RuleContext, change: FileChange) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(
            self._list_addition_findings(
                ctx,
                change,
                "omit",
                title="Test file added to coverage `omit`",
                detail="`{item}` was added to `omit` in {path}.",
            )
        )
        # `exclude_lines` widening is only worth flagging when the new pattern
        # itself targets tests (`def test_...`) — generic patterns like
        # `pragma: no cover` are ordinary, high-volume, legitimate use.
        findings.extend(
            self._list_addition_findings(
                ctx,
                change,
                "exclude_lines",
                title="Coverage `exclude_lines` widened to hide tests",
                detail="A new pattern `{item}` was added to `exclude_lines` in {path}.",
            )
        )
        return findings

    def _gitignore_addition(self, ctx: RuleContext, change: FileChange) -> list[Finding]:
        if not matches_any(change.path, _GITIGNORE_GLOBS):
            return []
        findings: list[Finding] = []
        for line_no, text in change.added_lines:
            cleaned = text.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            if matches_any(cleaned, tuple(ctx.config.test_globs)):
                findings.append(
                    self.finding(
                        ctx,
                        title="Test path added to `.gitignore`",
                        detail=f"`{cleaned}` was added to {change.path} and matches the test globs.",
                        path=change.path,
                        evidence=(
                            Evidence(
                                path=change.path,
                                line=line_no,
                                side="head",
                                snippet=cleaned,
                            ),
                        ),
                    )
                )
        return findings
