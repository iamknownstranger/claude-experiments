"""Parse `git diff` unified output into the frozen `ChangeSet` contract.

This is a pure function of text: no I/O, no git, no filesystem. Everything it
knows about "what changed" has to come from the diff bytes themselves, which
is what makes it testable from string literals and safe to fuzz. The tricky
part is not recognising a hunk — it is keeping both sides' line numbers
correct through multi-hunk files, renames, and the various ways git elides
information (omitted counts, `/dev/null`, quoted paths). A finding built on a
wrong line number is worse than no finding, so every counter here is advanced
explicitly rather than reconstructed after the fact.
"""

from __future__ import annotations

import re

from ratchet.contracts import ChangeKind, ChangeSet, FileChange, Hunk
from ratchet.diff.errors import DiffParseError

# `@@ -base_start[,base_lines] +head_start[,head_lines] @@ optional context`
# The count is omitted by git when it is exactly 1 — `@@ -1 +1 @@` — so both
# counts are optional groups, not just the whole suffix.
_HUNK_RE = re.compile(
    r"^@@ -(?P<base_start>\d+)(?:,(?P<base_lines>\d+))?"
    r" \+(?P<head_start>\d+)(?:,(?P<head_lines>\d+))? @@"
)

# The common case: an unrenamed file's `diff --git` line repeats the same
# path on both sides. A backreference lets this match correctly even when the
# path itself contains spaces, which plain splitting on " " cannot do.
_DIFF_GIT_SAME_RE = re.compile(r"^diff --git a/(?P<path>.+) b/(?P=path)$")
# git quotes a path (C-style, backslash + octal escapes) when it contains a
# quote, a backslash, or other bytes core.quotePath treats as unusual.
_DIFF_GIT_QUOTED_RE = re.compile(
    r'^diff --git (?P<old>"(?:[^"\\]|\\.)*") (?P<new>"(?:[^"\\]|\\.)*")$'
)
# Last-resort split for a renamed, unquoted path containing a space: genuinely
# ambiguous, so this just takes the first " b/" as the boundary rather than
# refusing to parse. Only reached when no --- / +++ / rename line supplied a
# path either (a `GIT binary patch` section with a renamed, spaced path).
_DIFF_GIT_FALLBACK_RE = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$")

_BINARY_RE = re.compile(r"^Binary files (?P<old>.+?) and (?P<new>.+) differ$")


def parse_unified_diff(text: str) -> ChangeSet:
    """Parse `git diff` unified output into a `ChangeSet`.

    Raises `DiffParseError` on anything that looks like a truncated or
    corrupted diff rather than guessing — a half-parsed `ChangeSet` silently
    missing a hunk is far more dangerous than a loud failure, because every
    rule downstream trusts that "not on the FileChange" means "did not
    happen".
    """
    # `.splitlines()` treats a lone "\r\n" as one break and leaves no stray
    # "\r" in the resulting lines, which is all the CRLF-normalization a
    # Windows-produced diff needs at this layer.
    lines = text.splitlines()
    changes: list[FileChange] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        if not line.startswith("diff --git "):
            raise DiffParseError(f"expected a 'diff --git' header, found: {line!r}")
        change, i = _parse_file_section(lines, i, n)
        changes.append(change)
    return ChangeSet(changes=tuple(changes))


def _parse_file_section(lines: list[str], i: int, n: int) -> tuple[FileChange, int]:
    header_line = lines[i]
    old_hint, new_hint = _parse_diff_git_header(header_line)
    i += 1

    old_path: str | None = None
    new_path: str | None = None
    rename_from: str | None = None
    rename_to: str | None = None
    is_new_file = False
    is_deleted_file = False
    is_binary = False
    hunks: list[Hunk] = []

    while i < n and not lines[i].startswith("diff --git "):
        line = lines[i]

        if line.startswith(
            ("old mode ", "new mode ", "similarity index", "dissimilarity index", "index ")
        ):
            i += 1
        elif line.startswith("new file mode"):
            is_new_file = True
            i += 1
        elif line.startswith("deleted file mode"):
            is_deleted_file = True
            i += 1
        elif line.startswith("rename from "):
            rename_from = _unquote_path(line[len("rename from ") :])
            i += 1
        elif line.startswith("rename to "):
            rename_to = _unquote_path(line[len("rename to ") :])
            i += 1
        elif line.startswith("Binary files "):
            is_binary = True
            match = _BINARY_RE.match(line)
            if match is None:
                raise DiffParseError(f"malformed binary-file header: {line!r}")
            if match.group("old") != "/dev/null":
                old_path = _parse_ab_token(match.group("old"))
            if match.group("new") != "/dev/null":
                new_path = _parse_ab_token(match.group("new"))
            i += 1
        elif line == "GIT binary patch":
            is_binary = True
            i += 1
            # The base85-encoded literal/delta blocks that follow are opaque
            # to us — there is nothing line-oriented about them to parse —
            # so skip everything up to the next file section.
            while i < n and not lines[i].startswith("diff --git "):
                i += 1
        elif line.startswith("--- "):
            token = line[4:]
            old_path = None if token == "/dev/null" else _parse_ab_token(_strip_header_tab(token))
            i += 1
        elif line.startswith("+++ "):
            token = line[4:]
            new_path = None if token == "/dev/null" else _parse_ab_token(_strip_header_tab(token))
            i += 1
        elif _HUNK_RE.match(line):
            hunk, i = _parse_hunk(lines, i, n)
            hunks.append(hunk)
        elif line.startswith("@@"):
            raise DiffParseError(f"malformed hunk header: {line!r}")
        elif line.startswith((" ", "+", "-", "\\")):
            # A content line that never followed a recognised hunk header —
            # either the header was mangled or a hunk's declared counts ran
            # short, consuming too few lines in `_parse_hunk`. Either way
            # this is not a diff we can trust the line numbers of.
            raise DiffParseError(f"hunk content line outside of any hunk: {line!r}")
        else:
            # Forward-compatible: an extended-header line this parser does
            # not yet know about (git adds these occasionally). Only path and
            # hunk lines are load-bearing for the contracts we produce.
            i += 1

    change = _build_change(
        header_line=header_line,
        old_hint=old_hint,
        new_hint=new_hint,
        old_path=old_path,
        new_path=new_path,
        rename_from=rename_from,
        rename_to=rename_to,
        is_new_file=is_new_file,
        is_deleted_file=is_deleted_file,
        is_binary=is_binary,
        hunks=tuple(hunks),
    )
    return change, i


def _build_change(
    *,
    header_line: str,
    old_hint: str | None,
    new_hint: str | None,
    old_path: str | None,
    new_path: str | None,
    rename_from: str | None,
    rename_to: str | None,
    is_new_file: bool,
    is_deleted_file: bool,
    is_binary: bool,
    hunks: tuple[Hunk, ...],
) -> FileChange:
    if rename_from is not None or rename_to is not None:
        if rename_from is None or rename_to is None:
            raise DiffParseError(f"rename header missing 'from' or 'to' path: {header_line!r}")
        return FileChange(
            path=rename_to,
            kind=ChangeKind.RENAMED,
            base_path=rename_from,
            hunks=hunks,
            is_binary=is_binary,
        )

    # A pure `GIT binary patch` section (no --- / +++ / Binary-files line)
    # only has the `diff --git` header to name the file.
    if old_path is None and new_path is None:
        old_path, new_path = old_hint, new_hint

    if is_new_file or old_path is None:
        if new_path is None:
            raise DiffParseError(f"added file section has no path: {header_line!r}")
        return FileChange(path=new_path, kind=ChangeKind.ADDED, hunks=hunks, is_binary=is_binary)

    if is_deleted_file or new_path is None:
        return FileChange(path=old_path, kind=ChangeKind.DELETED, hunks=hunks, is_binary=is_binary)

    return FileChange(path=new_path, kind=ChangeKind.MODIFIED, hunks=hunks, is_binary=is_binary)


def _parse_hunk(lines: list[str], i: int, n: int) -> tuple[Hunk, int]:
    match = _HUNK_RE.match(lines[i])
    if match is None:  # pragma: no cover - callers only reach here on a confirmed match
        raise DiffParseError(f"malformed hunk header: {lines[i]!r}")
    base_start = int(match.group("base_start"))
    base_lines = int(match.group("base_lines") or 1)
    head_start = int(match.group("head_start"))
    head_lines = int(match.group("head_lines") or 1)
    i += 1

    base_lineno = base_start
    head_lineno = head_start
    base_seen = 0
    head_seen = 0
    added: list[tuple[int, str]] = []
    removed: list[tuple[int, str]] = []

    while i < n and (base_seen < base_lines or head_seen < head_lines):
        line = lines[i]
        if line.startswith("\\"):
            # "\ No newline at end of file" annotates the previous content
            # line — it is not a line of content itself and must not shift
            # either counter.
            i += 1
            continue
        if line == "":
            # git always prefixes even a blank context line with a space, but
            # some diffs get passed through whitespace-trimming tools before
            # reaching us, so a bare blank line is tolerated as empty context
            # rather than treated as a parse error.
            marker, content = " ", ""
        elif line[0] in " +-":
            marker, content = line[0], line[1:]
        else:
            raise DiffParseError(f"malformed hunk line: {line!r}")

        if marker == " ":
            base_lineno += 1
            base_seen += 1
            head_lineno += 1
            head_seen += 1
        elif marker == "+":
            added.append((head_lineno, content))
            head_lineno += 1
            head_seen += 1
        else:
            removed.append((base_lineno, content))
            base_lineno += 1
            base_seen += 1
        i += 1

    if base_seen != base_lines or head_seen != head_lines:
        raise DiffParseError(
            f"hunk at -{base_start},{base_lines} +{head_start},{head_lines} "
            "ended before its declared line counts were satisfied"
        )

    # A trailing "\ No newline at end of file" for the hunk's very last line
    # arrives only after both counts are already met, so it is not consumed
    # by the loop above; absorb it here so it is not mistaken for an orphaned
    # content line by the caller.
    while i < n and lines[i].startswith("\\"):
        i += 1

    hunk = Hunk(
        base_start=base_start,
        base_lines=base_lines,
        head_start=head_start,
        head_lines=head_lines,
        added=tuple(added),
        removed=tuple(removed),
    )
    return hunk, i


def _parse_diff_git_header(line: str) -> tuple[str | None, str | None]:
    """Best-effort `(old_path, new_path)` from a `diff --git` line.

    Only used as a fallback when nothing more specific (`---`/`+++`, a rename
    header, or a `Binary files` line) supplied a path — namely a `GIT binary
    patch` section, which has no other path-bearing line.
    """
    match = _DIFF_GIT_SAME_RE.match(line)
    if match is not None:
        path = match.group("path")
        return path, path
    match = _DIFF_GIT_QUOTED_RE.match(line)
    if match is not None:
        return _parse_ab_token(match.group("old")), _parse_ab_token(match.group("new"))
    match = _DIFF_GIT_FALLBACK_RE.match(line)
    if match is not None:
        return match.group("old"), match.group("new")
    return None, None


def _strip_header_tab(token: str) -> str:
    # git appends a bare trailing tab to an unquoted `---`/`+++` path when the
    # path itself contains a space, to keep the (historically timestamp-
    # bearing) end of the line unambiguous. Quoted paths and paths with no
    # space never get one, so this is safe to apply unconditionally.
    return token[:-1] if token.endswith("\t") else token


def _parse_ab_token(token: str) -> str:
    """Unquote a path token and strip its `a/`/`b/`-style diff prefix."""
    return _strip_prefix(_unquote_path(token))


def _strip_prefix(token: str) -> str:
    # Default is `a/` / `b/`, but `diff.mnemonicPrefix` can produce `i/`,
    # `w/`, `c/`, `o/` instead — the letter varies, the single-char-plus-slash
    # shape does not.
    return token[2:] if len(token) >= 2 and token[1] == "/" else token


def _unquote_path(raw: str) -> str:
    """Undo git's C-style path quoting (`"a/with\\"quote.py"`).

    git quotes a path when it contains a quote, a backslash, or a byte
    `core.quotePath` treats as unusual, escaping it with backslash and octal
    (`\\nnn`) sequences. Octal escapes are individual bytes of a UTF-8
    encoding, so they are accumulated as bytes and decoded once at the end
    rather than turned into characters one escape at a time.
    """
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return raw
    body = raw[1:-1]
    out = bytearray()
    i = 0
    simple_escapes = {
        '"': '"',
        "\\": "\\",
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "v": "\v",
    }
    while i < len(body):
        char = body[i]
        if char == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in simple_escapes:
                out.extend(simple_escapes[nxt].encode())
                i += 2
                continue
            if nxt in "01234567":
                j = i + 1
                digits = ""
                while j < len(body) and len(digits) < 3 and body[j] in "01234567":
                    digits += body[j]
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            out.extend(nxt.encode())
            i += 2
            continue
        out.extend(char.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")
