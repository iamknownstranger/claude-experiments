"""Tests for the extractor-dispatching `SurfaceProvider`.

The distinctions asserted here are the ones rules depend on and cannot make for
themselves: "no tests here" versus "could not read this" versus "not a test
file at all". Collapsing any two of them either blinds a rule or makes it fire
on a file it never should have looked at.
"""

from __future__ import annotations

from ratchet.contracts import ChangeKind, FileChange, RatchetConfig
from ratchet.surfaces import ExtractorSurfaceProvider

HONEST = """\
def test_credit_is_exact():
    assert invoice.credit == 12.50
"""

BROKEN = "def test_x(:\n    assert"


def change(
    path: str,
    *,
    kind: ChangeKind = ChangeKind.MODIFIED,
    base: str | None = None,
    head: str | None = None,
    binary: bool = False,
) -> FileChange:
    return FileChange(path=path, kind=kind, base_content=base, head_content=head, is_binary=binary)


class TestDispatch:
    def test_python_test_file_is_extracted(self) -> None:
        provider = ExtractorSurfaceProvider()
        surface = provider.surface(
            change("tests/test_billing.py", base=HONEST, head=HONEST), "head"
        )
        assert surface is not None
        assert surface.parse_ok
        assert [t.name for t in surface.tests] == ["test_credit_is_exact"]

    def test_non_test_file_has_no_surface(self) -> None:
        # `src/billing.py` may well contain the word assert; it is still not a
        # test file, and no AST rule should ever be handed one.
        provider = ExtractorSurfaceProvider()
        assert provider.surface(change("src/billing.py", head=HONEST), "head") is None

    def test_binary_file_has_no_surface(self) -> None:
        provider = ExtractorSurfaceProvider()
        assert provider.surface(change("tests/test_x.py", binary=True), "head") is None

    def test_unsupported_language_has_no_surface(self) -> None:
        provider = ExtractorSurfaceProvider(RatchetConfig(test_globs=["**/*_test.go"]))
        assert provider.surface(change("pkg/thing_test.go", head="package x"), "head") is None

    def test_config_test_globs_decide_what_counts(self) -> None:
        provider = ExtractorSurfaceProvider(RatchetConfig(test_globs=["**/checks/*.py"]))
        assert provider.surface(change("tests/test_billing.py", head=HONEST), "head") is None
        assert provider.surface(change("checks/billing.py", head=HONEST), "head") is not None


class TestAbsentSides:
    def test_added_file_has_an_empty_base_not_an_unknown_one(self) -> None:
        # An added test file must read as "there were no tests before", so its
        # tests count as additions rather than vanishing into "unknown".
        provider = ExtractorSurfaceProvider()
        added = change("tests/test_new.py", kind=ChangeKind.ADDED, head=HONEST)
        base = provider.surface(added, "base")
        assert base is not None
        assert base.parse_ok and base.tests == ()

    def test_deleted_file_has_an_empty_head(self) -> None:
        # This is the one that matters most: if a deleted test file returned
        # None for head, VID001 would stay silent on a whole file of deleted
        # tests — the loudest signal the product has.
        provider = ExtractorSurfaceProvider()
        deleted = change("tests/test_old.py", kind=ChangeKind.DELETED, base=HONEST)
        head = provider.surface(deleted, "head")
        assert head is not None
        assert head.parse_ok and head.tests == ()

    def test_missing_content_on_a_modified_file_is_unknown_not_empty(self) -> None:
        # A diff parsed without blobs tells us nothing about the file's tests.
        # Reporting that as empty would invent deletions that never happened.
        provider = ExtractorSurfaceProvider()
        assert provider.surface(change("tests/test_x.py", head=HONEST), "base") is None


class TestParseFailure:
    def test_unparseable_file_is_marked_not_empty(self) -> None:
        provider = ExtractorSurfaceProvider()
        surface = provider.surface(change("tests/test_x.py", head=BROKEN), "head")
        assert surface is not None
        assert not surface.parse_ok
        assert surface.parse_error


class TestCaching:
    def test_repeated_lookups_reuse_one_parse(self) -> None:
        # A dozen AST rules ask for both sides of every file; without this the
        # same file is parsed two dozen times per run.
        provider = ExtractorSurfaceProvider()
        target = change("tests/test_billing.py", base=HONEST, head=HONEST)
        assert provider.surface(target, "head") is provider.surface(target, "head")

    def test_sides_are_cached_separately(self) -> None:
        provider = ExtractorSurfaceProvider()
        target = change("tests/test_billing.py", base=HONEST, head=HONEST)
        assert provider.surface(target, "base") is not provider.surface(target, "head")
