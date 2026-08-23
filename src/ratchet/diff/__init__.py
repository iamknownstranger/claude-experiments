"""Turn git state into the `ChangeSet` contract every rule consumes.

Rules never touch git directly — if a fact about "what changed" is not on the
`FileChange`, it did not happen, as far as the rest of Ratchet is concerned.
This package is therefore the sole place that shells out to git or parses its
diff format; everything downstream works from the frozen dataclasses in
`ratchet.contracts`.
"""

from __future__ import annotations

from ratchet.diff.errors import DiffParseError, GitError
from ratchet.diff.git import changeset_from_git
from ratchet.diff.parser import parse_unified_diff

__all__ = [
    "DiffParseError",
    "GitError",
    "changeset_from_git",
    "parse_unified_diff",
]
