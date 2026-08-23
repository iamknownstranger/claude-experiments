"""Typed errors raised by `ratchet.diff`.

Callers (the CLI, tests) need to tell "this diff could not be understood"
apart from "git itself failed" — the former is almost certainly a parser bug,
the latter is almost certainly a bad ref or a missing repository. Keeping them
as distinct exception types lets each be reported accurately instead of a bare
traceback bubbling out of `subprocess` or a regex mismatch.
"""

from __future__ import annotations


class DiffParseError(ValueError):
    """`parse_unified_diff` was given text it cannot make sense of.

    A `ValueError` subclass so a caller that only wants the broad category
    can still catch it as one, while a caller that cares can catch it by name.
    """


class GitError(RuntimeError):
    """A `git` subprocess invocation made by `changeset_from_git` failed.

    Raised instead of letting a raw `CalledProcessError` escape — that
    exception buries the command and stderr behind `.cmd` / `.stderr`
    attributes, which makes for an unreadable top-level error message.
    """
