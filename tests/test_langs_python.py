"""Tests for `ratchet.langs.python.extract`.

Sources are real pytest/unittest files as string literals — the extractor is
only useful if it agrees with what the actual runner would collect, so these
read as ordinary test files rather than synthetic tree-sitter fixtures.
"""

from __future__ import annotations

from ratchet.contracts import AssertionKind, SkipReason, TestSurface
from ratchet.langs.python import extract

PYTEST_STYLE = """\
import pytest


def test_addition():
    assert 1 + 1 == 2


def test_identity():
    obj = make_thing()
    assert obj is obj


def test_membership():
    assert "a" in ["a", "b"]


def test_not_found():
    assert not find("missing")


def test_exists():
    assert compute() is not None


def test_ordering():
    assert score(1) > score(0)


def test_tolerance():
    assert compute_ratio() == pytest.approx(0.5, abs=0.01)


def test_raises():
    with pytest.raises(ValueError):
        parse("not a number")


def helper_not_a_test():
    assert True
"""


UNITTEST_STYLE = """\
import unittest


class MathTests(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(add(2, 2), 4)

    def test_not_equal(self):
        self.assertNotEqual(add(2, 2), 5)

    def test_is_none(self):
        self.assertIsNone(find_missing())

    def test_is_not_none(self):
        self.assertIsNotNone(find_present())

    def test_true(self):
        self.assertTrue(is_ready())

    def test_false(self):
        self.assertFalse(is_broken())

    def test_in(self):
        self.assertIn(3, [1, 2, 3])

    def test_isinstance(self):
        self.assertIsInstance(build(), Widget)

    def test_almost_equal(self):
        self.assertAlmostEqual(compute(), 1.0, delta=0.05)

    def test_raises(self):
        self.assertRaises(KeyError, lookup, "missing")

    def not_a_test_helper(self):
        self.assertEqual(1, 1)
"""


SKIPS_MOCKS_FLAKY = """\
import pytest
from unittest import mock


@pytest.mark.skip(reason="not ready")
def test_disabled():
    assert True


@pytest.mark.skipif(sys.platform == "win32", reason="posix only")
def test_platform_specific():
    assert True


@pytest.mark.xfail
def test_known_broken():
    assert False


@pytest.mark.flaky(reruns=3)
def test_flaky_network():
    assert call_flaky_service()


@mock.patch("billing.gateway.charge")
def test_patched_gateway(mock_charge):
    mock_charge.return_value = True
    assert process_payment()
    mock_charge.assert_called_once()


def test_monkeypatch(monkeypatch):
    monkeypatch.setattr("billing.gateway.charge", lambda *a: True)
    assert process_payment()
"""


SYNTAX_ERROR = """\
def test_broken(:
    assert True
"""


RENAMED_OUT_OF_DISCOVERY = """\
import pytest


def _test_hidden():
    # Renamed from `test_hidden` — pytest no longer collects this, silently.
    assert True
"""


class TestPytestStyle:
    def _extract(self) -> TestSurface:
        return extract("tests/test_math.py", PYTEST_STYLE)

    def test_parses_ok(self) -> None:
        assert self._extract().parse_ok is True

    def test_framework_is_pytest(self) -> None:
        assert self._extract().framework == "pytest"

    def test_collects_only_test_prefixed_functions(self) -> None:
        ids = {t.id for t in self._extract().tests}
        assert "tests/test_math.py::test_addition" in ids
        assert not any("helper_not_a_test" in test_id for test_id in ids)

    def test_all_discoverable(self) -> None:
        assert all(t.is_discoverable for t in self._extract().tests)

    def test_id_has_no_class_segment_at_module_level(self) -> None:
        by_id = self._extract().by_id
        test = by_id["tests/test_math.py::test_addition"]
        assert test.qualname == "test_addition"

    def test_exact_line_numbers(self) -> None:
        by_id = self._extract().by_id
        test = by_id["tests/test_math.py::test_addition"]
        # def test_addition(): is line 4, its closing assert is line 5.
        assert test.line_start == 4
        assert test.line_end == 5

    def test_equality_assertion(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_addition"].assertions
        assert assertion.kind is AssertionKind.EQUALITY
        assert assertion.negated is False
        assert assertion.line == 5
        assert assertion.operands == ("1 + 1", "2")

    def test_identity_assertion(self) -> None:
        by_id = self._extract().by_id
        assertions = by_id["tests/test_math.py::test_identity"].assertions
        (assertion,) = [a for a in assertions if a.kind is AssertionKind.IDENTITY]
        assert assertion.negated is False

    def test_membership_assertion(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_membership"].assertions
        assert assertion.kind is AssertionKind.MEMBERSHIP
        assert assertion.negated is False

    def test_truthiness_negated_via_not(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_not_found"].assertions
        assert assertion.kind is AssertionKind.TRUTHINESS
        assert assertion.negated is True

    def test_existence_assertion(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_exists"].assertions
        assert assertion.kind is AssertionKind.EXISTENCE
        assert assertion.negated is False

    def test_comparison_assertion(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_ordering"].assertions
        assert assertion.kind is AssertionKind.COMPARISON

    def test_approx_tolerance_parsed(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_tolerance"].assertions
        assert assertion.kind is AssertionKind.APPROXIMATE
        assert assertion.tolerance == 0.01

    def test_pytest_raises_is_exception_kind(self) -> None:
        by_id = self._extract().by_id
        (assertion,) = by_id["tests/test_math.py::test_raises"].assertions
        assert assertion.kind is AssertionKind.EXCEPTION
        assert assertion.callee == "raises"

    def test_exercised_symbols_exclude_assertions(self) -> None:
        by_id = self._extract().by_id
        test = by_id["tests/test_math.py::test_identity"]
        assert "make_thing" in test.exercised_symbols


class TestUnittestStyle:
    def _extract(self) -> TestSurface:
        return extract("tests/test_math_unittest.py", UNITTEST_STYLE)

    def test_parses_ok(self) -> None:
        assert self._extract().parse_ok is True

    def test_framework_is_unittest(self) -> None:
        assert self._extract().framework == "unittest"

    def test_ids_include_class_name(self) -> None:
        by_id = self._extract().by_id
        assert "tests/test_math_unittest.py::MathTests::test_equal" in by_id
        test = by_id["tests/test_math_unittest.py::MathTests::test_equal"]
        assert test.qualname == "MathTests.test_equal"

    def test_non_test_method_excluded(self) -> None:
        ids = set(self._extract().by_id)
        assert not any("not_a_test_helper" in test_id for test_id in ids)

    def test_equal_and_not_equal(self) -> None:
        by_id = self._extract().by_id
        eq = by_id["tests/test_math_unittest.py::MathTests::test_equal"].assertions[0]
        assert eq.kind is AssertionKind.EQUALITY
        assert eq.negated is False
        ne = by_id["tests/test_math_unittest.py::MathTests::test_not_equal"].assertions[0]
        assert ne.kind is AssertionKind.EQUALITY
        assert ne.negated is True

    def test_is_none_and_is_not_none(self) -> None:
        by_id = self._extract().by_id
        is_none = by_id["tests/test_math_unittest.py::MathTests::test_is_none"].assertions[0]
        assert is_none.kind is AssertionKind.EXISTENCE
        assert is_none.negated is True
        is_not_none = by_id["tests/test_math_unittest.py::MathTests::test_is_not_none"].assertions[
            0
        ]
        assert is_not_none.kind is AssertionKind.EXISTENCE
        assert is_not_none.negated is False

    def test_true_and_false(self) -> None:
        by_id = self._extract().by_id
        true_a = by_id["tests/test_math_unittest.py::MathTests::test_true"].assertions[0]
        assert true_a.kind is AssertionKind.TRUTHINESS
        assert true_a.negated is False
        false_a = by_id["tests/test_math_unittest.py::MathTests::test_false"].assertions[0]
        assert false_a.kind is AssertionKind.TRUTHINESS
        assert false_a.negated is True

    def test_in(self) -> None:
        by_id = self._extract().by_id
        assertion = by_id["tests/test_math_unittest.py::MathTests::test_in"].assertions[0]
        assert assertion.kind is AssertionKind.MEMBERSHIP

    def test_isinstance(self) -> None:
        by_id = self._extract().by_id
        assertion = by_id["tests/test_math_unittest.py::MathTests::test_isinstance"].assertions[0]
        assert assertion.kind is AssertionKind.TYPE

    def test_almost_equal_with_delta(self) -> None:
        by_id = self._extract().by_id
        assertion = by_id["tests/test_math_unittest.py::MathTests::test_almost_equal"].assertions[0]
        assert assertion.kind is AssertionKind.APPROXIMATE
        assert assertion.tolerance == 0.05

    def test_assert_raises(self) -> None:
        by_id = self._extract().by_id
        assertion = by_id["tests/test_math_unittest.py::MathTests::test_raises"].assertions[0]
        assert assertion.kind is AssertionKind.EXCEPTION


class TestSkipsMocksAndFlaky:
    def _extract(self) -> TestSurface:
        return extract("tests/test_flags.py", SKIPS_MOCKS_FLAKY)

    def test_skip_marker(self) -> None:
        by_id = self._extract().by_id
        test = by_id["tests/test_flags.py::test_disabled"]
        (marker,) = test.skip_markers
        assert marker.reason is SkipReason.SKIP
        assert test.is_skipped is True

    def test_skipif_marker_captures_condition(self) -> None:
        by_id = self._extract().by_id
        (marker,) = by_id["tests/test_flags.py::test_platform_specific"].skip_markers
        assert marker.reason is SkipReason.SKIP_IF
        assert marker.expression == 'sys.platform == "win32"'

    def test_xfail_marker(self) -> None:
        by_id = self._extract().by_id
        (marker,) = by_id["tests/test_flags.py::test_known_broken"].skip_markers
        assert marker.reason is SkipReason.EXPECTED_FAILURE

    def test_flaky_retry(self) -> None:
        by_id = self._extract().by_id
        (retry,) = by_id["tests/test_flags.py::test_flaky_network"].retries
        assert retry.callee == "flaky"
        assert retry.max_attempts == 3

    def test_decorator_mock_patch_target(self) -> None:
        by_id = self._extract().by_id
        (mock_usage,) = by_id["tests/test_flags.py::test_patched_gateway"].mocks
        assert mock_usage.target == "billing.gateway.charge"

    def test_decorator_patch_call_counts_as_call_assertion(self) -> None:
        by_id = self._extract().by_id
        test = by_id["tests/test_flags.py::test_patched_gateway"]
        call_assertions = [a for a in test.assertions if a.kind is AssertionKind.CALL]
        assert len(call_assertions) == 1
        assert call_assertions[0].callee == "assert_called_once"

    def test_monkeypatch_target(self) -> None:
        by_id = self._extract().by_id
        (mock_usage,) = by_id["tests/test_flags.py::test_monkeypatch"].mocks
        assert mock_usage.target == "billing.gateway.charge"


class TestSyntaxError:
    def test_unparsed_on_syntax_error(self) -> None:
        surface = extract("tests/test_broken.py", SYNTAX_ERROR)
        assert surface.parse_ok is False
        assert surface.parse_error is not None
        assert surface.tests == ()

    def test_never_raises(self) -> None:
        # A handful of inputs that are not valid Python at all, or are
        # pathological in ways a naive extractor might choke on.
        for bad_source in ["", "   ", "\x00\x01", "def(", "class:\n\tpass\n" * 500]:
            surface = extract("tests/test_weird.py", bad_source)
            assert isinstance(surface, TestSurface)


class TestRenamedOutOfDiscovery:
    def test_renamed_test_is_captured_but_not_discoverable(self) -> None:
        surface = extract("tests/test_hidden.py", RENAMED_OUT_OF_DISCOVERY)
        assert surface.parse_ok is True
        (test,) = surface.tests
        assert test.name == "_test_hidden"
        assert test.is_discoverable is False
        assert test.will_run is False

    def test_id_reflects_actual_name(self) -> None:
        surface = extract("tests/test_hidden.py", RENAMED_OUT_OF_DISCOVERY)
        (test,) = surface.tests
        assert test.id == "tests/test_hidden.py::_test_hidden"


class TestEmptyAndTrivialFiles:
    def test_empty_file(self) -> None:
        surface = extract("tests/test_empty.py", "")
        assert surface.parse_ok is True
        assert surface.tests == ()

    def test_no_tests_in_file(self) -> None:
        surface = extract("tests/test_no_tests.py", "def helper():\n    return 1\n")
        assert surface.parse_ok is True
        assert surface.tests == ()


class TestNonTestClassIsIgnored:
    def test_helper_class_with_test_prefixed_method_is_not_collected(self) -> None:
        # `Helpers` matches neither pytest's `Test*` nor a `unittest.TestCase`
        # base, so pytest never collects `Helpers.test_thing` and neither
        # should the extractor.
        source = "class Helpers:\n    def test_thing(self):\n        assert True\n"
        surface = extract("tests/test_helpers.py", source)
        assert surface.tests == ()
