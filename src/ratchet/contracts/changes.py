"""FileChange — one file's before and after, as the rules see it.

Produced by `ratchet.diff`, consumed by every rule. Rules never touch git and
never re-read the working tree; if it is not on the `FileChange`, it did not
happen. That keeps rules pure and trivially testable from string literals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ChangeKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class Hunk:
    """One contiguous region of change, with both sides' line numbers intact.

    Line numbers matter more here than usual: a finding that cites the wrong
    line teaches reviewers to distrust the tool, so both sides are tracked
    explicitly rather than reconstructed later.
    """

    base_start: int
    base_lines: int
    head_start: int
    head_lines: int
    added: tuple[tuple[int, str], ...] = field(default_factory=tuple)
    removed: tuple[tuple[int, str], ...] = field(default_factory=tuple)

    @property
    def added_text(self) -> str:
        return "\n".join(text for _, text in self.added)

    @property
    def removed_text(self) -> str:
        return "\n".join(text for _, text in self.removed)


@dataclass(frozen=True, slots=True)
class FileChange:
    """A single file's transition from base to head."""

    path: str
    """Head-side path — or the base-side path when the file was deleted."""

    kind: ChangeKind

    base_path: str | None = None
    """Pre-rename path. Set only for `ChangeKind.RENAMED`; `None` otherwise."""

    base_content: str | None = None
    """Whole file as of base. `None` for added and binary files."""

    head_content: str | None = None
    """Whole file as of head. `None` for deleted and binary files."""

    hunks: tuple[Hunk, ...] = field(default_factory=tuple)
    is_binary: bool = False

    @property
    def added_lines(self) -> tuple[tuple[int, str], ...]:
        return tuple(line for hunk in self.hunks for line in hunk.added)

    @property
    def removed_lines(self) -> tuple[tuple[int, str], ...]:
        return tuple(line for hunk in self.hunks for line in hunk.removed)

    @property
    def added_text(self) -> str:
        return "\n".join(text for _, text in self.added_lines)

    @property
    def removed_text(self) -> str:
        return "\n".join(text for _, text in self.removed_lines)

    def head_line(self, line: int) -> str:
        """1-indexed lookup into head content; empty string when out of range."""
        return _nth_line(self.head_content, line)

    def base_line(self, line: int) -> str:
        return _nth_line(self.base_content, line)


def _nth_line(content: str | None, line: int) -> str:
    if content is None or line < 1:
        return ""
    lines = content.splitlines()
    return lines[line - 1] if line <= len(lines) else ""


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """Every file changed by one pull request, plus who is accountable for it."""

    changes: tuple[FileChange, ...] = field(default_factory=tuple)
    base_ref: str = ""
    head_ref: str = ""
    commit_messages: tuple[str, ...] = field(default_factory=tuple)

    def by_path(self, path: str) -> FileChange | None:
        for change in self.changes:
            if change.path == path:
                return change
        return None

    def matching(self, kinds: frozenset[ChangeKind]) -> tuple[FileChange, ...]:
        return tuple(c for c in self.changes if c.kind in kinds)
