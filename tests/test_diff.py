"""Tests for `ratchet.diff`.

`parse_unified_diff` is tested against real `git diff` output captured from a
throwaway repository (see the fixtures below), not hand-rolled diff text —
git's actual quoting, header-tab, and no-newline conventions are exactly the
kind of thing that is easy to get subtly wrong by guessing. `changeset_from_git`
is tested against real repositories built with `git init` in `tmp_path`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ratchet.contracts import ChangeKind
from ratchet.diff import DiffParseError, GitError, changeset_from_git, parse_unified_diff

# --------------------------------------------------------------------------
# Fixtures: real `git diff --unified=3 --find-renames --no-color` output.
# Raw strings preserve git's literal backslash escapes (the quoted-path
# fixture) byte-for-byte; the two fixtures with a header path containing a
# space are built by concatenation instead, because git appends a bare
# trailing tab to disambiguate the path in that case and `\t` needs to be a
# real escape, not two raw characters.
# --------------------------------------------------------------------------

MULTIHUNK_DIFF = r"""diff --git a/multi.py b/multi.py
index 19339a3..9b8f357 100644
--- a/multi.py
+++ b/multi.py
@@ -1,5 +1,5 @@
 line1
-line2
+CHANGED2
 line3
 line4
 line5
@@ -24,7 +24,7 @@ line23
 line24
 line25
 line26
-line27
-line28
+NEWLINE_A
+NEWLINE_B
 line29
 line30
"""

ADDED_AND_DELETED_DIFF = r"""diff --git a/added.py b/added.py
new file mode 100644
index 0000000..af88c2c
--- /dev/null
+++ b/added.py
@@ -0,0 +1,2 @@
+def added():
+    return 1
diff --git a/multi.py b/multi.py
deleted file mode 100644
index 9b8f357..0000000
--- a/multi.py
+++ /dev/null
@@ -1,30 +0,0 @@
-line1
-CHANGED2
-line3
-line4
-line5
-line6
-line7
-line8
-line9
-line10
-line11
-line12
-line13
-line14
-line15
-line16
-line17
-line18
-line19
-line20
-line21
-line22
-line23
-line24
-line25
-line26
-NEWLINE_A
-NEWLINE_B
-line29
-line30
"""

RENAME_DIFF = r"""diff --git a/rename_src.py b/rename_dst.py
similarity index 87%
rename from rename_src.py
rename to rename_dst.py
index 59c9afc..3a954be 100644
--- a/rename_src.py
+++ b/rename_dst.py
@@ -3,7 +3,7 @@ def alpha():


 def beta():
-    return 2
+    return 20


 def gamma():
"""

BINARY_DIFFER_DIFF = r"""diff --git a/image.png b/image.png
index 6735744..d360e0c 100644
Binary files a/image.png and b/image.png differ
"""

GIT_BINARY_PATCH_DIFF = r"""diff --git a/image.png b/image.png
index 6735744d9c5bfa205ec44c128ac9007f124c6686..d360e0cdd66ed94205b794c9f50489349679cf66 100644
GIT binary patch
literal 13
UcmeAS@N?(olHy`uWMcjg028PJuK)l5

literal 12
TcmeAS@N?(olHy`uWMT#Y5cvVH

"""

NO_NEWLINE_DIFF = r"""diff --git a/noeof.py b/noeof.py
index e9e63a4..834c701 100644
--- a/noeof.py
+++ b/noeof.py
@@ -1,3 +1,3 @@
 first line
-second line
+CHANGED second line
 no trailing newline
\ No newline at end of file
"""

SPACED_PATH_DIFF = (
    "diff --git a/with space.py b/with space.py\n"
    "index 422c2b7..be2846b 100644\n"
    "--- a/with space.py\t\n"
    "+++ b/with space.py\t\n"
    "@@ -1,2 +1,2 @@\n"
    " a\n"
    "-b\n"
    "+CHANGED\n"
)

RENAME_SPACED_PATH_DIFF = (
    "diff --git a/with space.py b/renamed with space.py\n"
    "similarity index 62%\n"
    "rename from with space.py\n"
    "rename to renamed with space.py\n"
    "index be2846b..793dbe6 100644\n"
    "--- a/with space.py\t\n"
    "+++ b/renamed with space.py\t\n"
    "@@ -1,2 +1,3 @@\n"
    " a\n"
    " CHANGED\n"
    "+extra\n"
)

QUOTED_PATH_DIFF = r"""diff --git "a/with\"quote.py" "b/with\"quote.py"
index 422c2b7..be2846b 100644
--- "a/with\"quote.py"
+++ "b/with\"quote.py"
@@ -1,2 +1,2 @@
 a
-b
+CHANGED
"""


class TestParseUnifiedDiff:
    def test_empty_input_is_an_empty_changeset(self) -> None:
        assert parse_unified_diff("") == parse_unified_diff("   \n\n")
        assert parse_unified_diff("").changes == ()

    def test_multi_hunk_line_numbers_are_exact(self) -> None:
        # This is the regression most likely to bite: a finding that cites
        # the wrong line teaches reviewers to distrust the whole tool.
        (change,) = parse_unified_diff(MULTIHUNK_DIFF).changes
        assert change.path == "multi.py"
        assert change.kind is ChangeKind.MODIFIED
        assert len(change.hunks) == 2

        first, second = change.hunks
        assert (first.base_start, first.base_lines) == (1, 5)
        assert (first.head_start, first.head_lines) == (1, 5)
        assert first.removed == ((2, "line2"),)
        assert first.added == ((2, "CHANGED2"),)

        assert (second.base_start, second.base_lines) == (24, 7)
        assert (second.head_start, second.head_lines) == (24, 7)
        assert second.removed == ((27, "line27"), (28, "line28"))
        assert second.added == ((27, "NEWLINE_A"), (28, "NEWLINE_B"))

        # Flattened across hunks, in file order.
        assert change.removed_lines == ((2, "line2"), (27, "line27"), (28, "line28"))
        assert change.added_lines == ((2, "CHANGED2"), (27, "NEWLINE_A"), (28, "NEWLINE_B"))

    def test_added_and_deleted_files_in_one_diff(self) -> None:
        added, deleted = parse_unified_diff(ADDED_AND_DELETED_DIFF).changes

        assert added.path == "added.py"
        assert added.kind is ChangeKind.ADDED
        assert added.base_path is None
        (hunk,) = added.hunks
        assert (hunk.base_start, hunk.base_lines) == (0, 0)
        assert (hunk.head_start, hunk.head_lines) == (1, 2)
        assert hunk.removed == ()
        assert hunk.added == ((1, "def added():"), (2, "    return 1"))

        assert deleted.path == "multi.py"
        assert deleted.kind is ChangeKind.DELETED
        (hunk,) = deleted.hunks
        assert (hunk.base_start, hunk.base_lines) == (1, 30)
        assert (hunk.head_start, hunk.head_lines) == (0, 0)
        assert hunk.added == ()
        assert len(hunk.removed) == 30
        assert hunk.removed[0] == (1, "line1")
        assert hunk.removed[-1] == (30, "line30")

    def test_rename_sets_base_path_and_kind(self) -> None:
        (change,) = parse_unified_diff(RENAME_DIFF).changes
        assert change.kind is ChangeKind.RENAMED
        assert change.base_path == "rename_src.py"
        assert change.path == "rename_dst.py"
        (hunk,) = change.hunks
        # A same-line edit: the old and new text share one line number.
        assert hunk.removed == ((6, "    return 2"),)
        assert hunk.added == ((6, "    return 20"),)

    def test_binary_files_differ_sets_flag_with_no_hunks(self) -> None:
        (change,) = parse_unified_diff(BINARY_DIFFER_DIFF).changes
        assert change.path == "image.png"
        assert change.kind is ChangeKind.MODIFIED
        assert change.is_binary
        assert change.hunks == ()

    def test_git_binary_patch_sets_flag_and_resolves_path_from_header(self) -> None:
        # No `---`/`+++`/`Binary files` line exists in this form — the path
        # can only come from the `diff --git` header.
        (change,) = parse_unified_diff(GIT_BINARY_PATCH_DIFF).changes
        assert change.path == "image.png"
        assert change.kind is ChangeKind.MODIFIED
        assert change.is_binary
        assert change.hunks == ()

    def test_no_newline_marker_is_not_a_content_line(self) -> None:
        (change,) = parse_unified_diff(NO_NEWLINE_DIFF).changes
        (hunk,) = change.hunks
        assert hunk.removed == ((2, "second line"),)
        assert hunk.added == ((2, "CHANGED second line"),)
        # If the marker had been swallowed as content, the hunk's declared
        # counts (3/3) would not have matched and parsing would have raised.
        assert change.added_text == "CHANGED second line"

    def test_path_with_space_strips_gits_disambiguating_tab(self) -> None:
        (change,) = parse_unified_diff(SPACED_PATH_DIFF).changes
        assert change.path == "with space.py"
        assert change.kind is ChangeKind.MODIFIED
        (hunk,) = change.hunks
        assert hunk.removed == ((2, "b"),)
        assert hunk.added == ((2, "CHANGED"),)

    def test_rename_with_spaced_paths(self) -> None:
        (change,) = parse_unified_diff(RENAME_SPACED_PATH_DIFF).changes
        assert change.kind is ChangeKind.RENAMED
        assert change.base_path == "with space.py"
        assert change.path == "renamed with space.py"

    def test_quoted_path_with_embedded_quote_is_unescaped(self) -> None:
        (change,) = parse_unified_diff(QUOTED_PATH_DIFF).changes
        assert change.path == 'with"quote.py'
        assert change.kind is ChangeKind.MODIFIED
        (hunk,) = change.hunks
        assert hunk.removed == ((2, "b"),)
        assert hunk.added == ((2, "CHANGED"),)

    def test_omitted_hunk_count_defaults_to_one(self) -> None:
        text = (
            "diff --git a/x.py b/x.py\n"
            "index aaa..bbb 100644\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        (change,) = parse_unified_diff(text).changes
        (hunk,) = change.hunks
        assert (hunk.base_start, hunk.base_lines) == (1, 1)
        assert (hunk.head_start, hunk.head_lines) == (1, 1)
        assert hunk.removed == ((1, "old"),)
        assert hunk.added == ((1, "new"),)

    def test_multiple_files_preserve_diff_order(self) -> None:
        changes = parse_unified_diff(ADDED_AND_DELETED_DIFF).changes
        assert [c.path for c in changes] == ["added.py", "multi.py"]

    def test_non_diff_text_raises(self) -> None:
        with pytest.raises(DiffParseError, match="diff --git"):
            parse_unified_diff("this is not a diff\njust some text\n")

    def test_hunk_shorter_than_declared_counts_raises(self) -> None:
        text = (
            "diff --git a/x.py b/x.py\n"
            "index aaa..bbb 100644\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            " b\n"
        )
        with pytest.raises(DiffParseError, match="declared line counts"):
            parse_unified_diff(text)

    def test_malformed_hunk_header_raises(self) -> None:
        text = (
            "diff --git a/x.py b/x.py\n"
            "index aaa..bbb 100644\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ garbage @@\n"
            " a\n"
        )
        with pytest.raises(DiffParseError, match="malformed hunk header"):
            parse_unified_diff(text)

    def test_content_line_without_a_hunk_header_raises(self) -> None:
        text = (
            "diff --git a/x.py b/x.py\n"
            "index aaa..bbb 100644\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "+stray line, no @@ header preceded it\n"
        )
        with pytest.raises(DiffParseError, match="outside of any hunk"):
            parse_unified_diff(text)

    def test_incomplete_rename_header_raises(self) -> None:
        text = "diff --git a/x.py b/y.py\nrename from x.py\n"
        with pytest.raises(DiffParseError, match="rename header"):
            parse_unified_diff(text)


# --------------------------------------------------------------------------
# changeset_from_git — exercised against real throwaway repositories.
# --------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class TestChangesetFromGit:
    def test_modified_file_gets_both_sides_content_and_refs(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "a.py").write_text("one\ntwo\nthree\n")
        base = _commit(repo, "base")
        (repo / "a.py").write_text("one\nTWO\nthree\n")
        head = _commit(repo, "head")

        changeset = changeset_from_git(base, head, repo_root=repo)

        assert changeset.base_ref == base
        assert changeset.head_ref == head
        (change,) = changeset.changes
        assert change.kind is ChangeKind.MODIFIED
        assert change.base_content == "one\ntwo\nthree\n"
        assert change.head_content == "one\nTWO\nthree\n"
        (hunk,) = change.hunks
        assert hunk.removed == ((2, "two"),)
        assert hunk.added == ((2, "TWO"),)

    def test_added_file_has_no_base_content(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "seed.py").write_text("seed\n")
        base = _commit(repo, "base")
        (repo / "new.py").write_text("brand new\n")
        head = _commit(repo, "head")

        changeset = changeset_from_git(base, head, repo_root=repo)

        (change,) = changeset.changes
        assert change.kind is ChangeKind.ADDED
        assert change.base_content is None
        assert change.head_content == "brand new\n"

    def test_deleted_file_has_no_head_content(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "gone.py").write_text("will be removed\n")
        base = _commit(repo, "base")
        (repo / "gone.py").unlink()
        head = _commit(repo, "head")

        changeset = changeset_from_git(base, head, repo_root=repo)

        (change,) = changeset.changes
        assert change.kind is ChangeKind.DELETED
        assert change.head_content is None
        assert change.base_content == "will be removed\n"

    def test_binary_file_never_gets_content_fetched(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "img.bin").write_bytes(b"\x00\x01\x02")
        base = _commit(repo, "base")
        (repo / "img.bin").write_bytes(b"\x00\x01\xff")
        head = _commit(repo, "head")

        changeset = changeset_from_git(base, head, repo_root=repo)

        (change,) = changeset.changes
        assert change.is_binary
        assert change.base_content is None
        assert change.head_content is None

    def test_commit_messages_are_collected_between_base_and_head(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "a.py").write_text("one\n")
        base = _commit(repo, "base commit")
        (repo / "a.py").write_text("two\n")
        _commit(repo, "first change\n\nRatchet-Justification: VID001 — reason")
        (repo / "a.py").write_text("three\n")
        head = _commit(repo, "second change")

        changeset = changeset_from_git(base, head, repo_root=repo)

        assert len(changeset.commit_messages) == 2
        joined = "\n".join(changeset.commit_messages)
        assert "Ratchet-Justification: VID001" in joined
        assert "second change" in joined

    def test_bad_ref_raises_git_error_not_a_raw_subprocess_error(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (repo / "a.py").write_text("one\n")
        base = _commit(repo, "base")

        with pytest.raises(GitError):
            changeset_from_git(base, "not-a-real-ref", repo_root=repo)

    def test_diff_is_run_with_color_pager_and_ext_diff_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        (repo / "a.py").write_text("one\n")
        base = _commit(repo, "base")
        (repo / "a.py").write_text("two\n")
        head = _commit(repo, "head")

        seen_diff_args: list[str] = []
        real_run = subprocess.run

        def spy(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            if "diff" in cmd:
                seen_diff_args.extend(cmd)
            return real_run(cmd, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(subprocess, "run", spy)

        changeset_from_git(base, head, repo_root=repo)

        assert "--no-pager" in seen_diff_args
        assert "--no-color" in seen_diff_args
        assert "--no-ext-diff" in seen_diff_args
        assert "--find-renames" in seen_diff_args
