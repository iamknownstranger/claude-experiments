"""Load a `ChangeSet` from a real git repository.

The only I/O boundary in `ratchet.diff`: everything here shells out to `git`
via `subprocess` and hands the result to `parse_unified_diff`, which does all
the actual interpretation. Keeping the split this way means the parser stays
a pure function testable from string literals, and this module stays a thin,
easily-mocked shim around three git subcommands.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

from ratchet.contracts import ChangeKind, ChangeSet, FileChange
from ratchet.diff.errors import GitError
from ratchet.diff.parser import parse_unified_diff

# Every flag here removes one way a contributor's global git config could
# change the bytes we get back — a pager, a color theme, or a configured
# external diff tool would each corrupt the unified-diff format we parse.
_DIFF_ARGS = ("--no-color", "--no-ext-diff", "--unified=3", "--find-renames")


def changeset_from_git(base: str, head: str, *, repo_root: Path | None = None) -> ChangeSet:
    """Diff `base..head` in a real git repository and load a full `ChangeSet`.

    File content is fetched via `git show <ref>:<path>` rather than by
    reading the working tree, so this is safe to call against a ref that is
    not checked out (a PR's merge base, for instance) and never picks up
    uncommitted local edits.
    """
    cwd = repo_root or Path.cwd()
    diff_text = _run(cwd, ["diff", *_DIFF_ARGS, base, head])
    parsed = parse_unified_diff(diff_text)

    changes = tuple(_with_content(cwd, base, head, change) for change in parsed.changes)
    return ChangeSet(
        changes=changes,
        base_ref=base,
        head_ref=head,
        commit_messages=_commit_messages(cwd, base, head),
    )


def _with_content(cwd: Path, base: str, head: str, change: FileChange) -> FileChange:
    if change.is_binary:
        return change
    base_content = (
        _show(cwd, base, change.base_path or change.path)
        if change.kind is not ChangeKind.ADDED
        else None
    )
    head_content = _show(cwd, head, change.path) if change.kind is not ChangeKind.DELETED else None
    return replace(change, base_content=base_content, head_content=head_content)


def _show(cwd: Path, ref: str, path: str) -> str | None:
    try:
        return _run(cwd, ["show", f"{ref}:{path}"])
    except GitError:
        # The classification above (added/modified/deleted) comes from the
        # diff header; if git disagrees — the path did not actually exist on
        # this side — the hunks remain the source of truth and content is
        # simply unavailable, rather than failing the whole changeset.
        return None


def _commit_messages(cwd: Path, base: str, head: str) -> tuple[str, ...]:
    # %B is the raw subject+body with no guaranteed delimiter, and commit
    # messages routinely contain blank lines, so the entries are NUL-
    # delimited explicitly rather than split on git's own formatting.
    raw = _run(cwd, ["log", "--format=%B%x00", f"{base}..{head}"])
    return tuple(message.strip() for message in raw.split("\x00") if message.strip())


def _run(cwd: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "--no-pager", *args],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise GitError(f"failed to launch git {' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {stderr}")
    return _decode(result.stdout)


def _decode(raw: bytes) -> str:
    # A Windows checkout can hand back CRLF-terminated blobs and diff output;
    # collapsing that here means a line-ending-only change never masquerades
    # as a full-file rewrite to anything downstream of this module.
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
