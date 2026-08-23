"""pytest/unittest -> `TestSurface`.

The public entry point is `extract`. Everything else here exists to answer
one of three questions about a syntax tree: is this thing a test, what does
it check, and will the runner ever actually run it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tree_sitter import Node

from ratchet.contracts import (
    Assertion,
    AssertionKind,
    MockUsage,
    RetryWrapper,
    SkipMarker,
    SkipReason,
    TestCase,
    TestSurface,
)
from ratchet.langs.python._nodes import (
    find_keyword,
    float_literal,
    int_literal,
    last_segment,
    normalize,
    operand_texts,
    positional_args,
    string_literal,
    text,
)
from ratchet.parse import parse_source

# unittest's TestLoader and pytest's default `python_functions`/`python_classes`
# collect on a literal prefix, not a fnmatch-style pattern, so plain `str.startswith`
# reproduces both exactly.
_DISCOVERABLE_FUNCTION_PREFIX = "test_"
_DISCOVERABLE_CLASS_PREFIX = "Test"

# unittest.TestCase subclasses are collected by pytest regardless of class name,
# so a base ending in this name is itself sufficient to make a class a test
# container — the `Test*` name check below is the pytest-only path.
_TESTCASE_BASE_NAME = "TestCase"

_MOCK_ASSERT_NAMES = frozenset({"assert_any_call", "assert_has_calls", "assert_not_called"})

# Ordered so the first structural match wins; unrecognised `assertFoo` names
# fall through to CUSTOM in `_classify_method_assertion` rather than being
# listed here one by one.
_ASSERT_METHOD_KIND: dict[str, tuple[AssertionKind, bool]] = {
    "assertEqual": (AssertionKind.EQUALITY, False),
    "assertNotEqual": (AssertionKind.EQUALITY, True),
    "assertIs": (AssertionKind.IDENTITY, False),
    "assertIsNot": (AssertionKind.IDENTITY, True),
    "assertTrue": (AssertionKind.TRUTHINESS, False),
    "assertFalse": (AssertionKind.TRUTHINESS, True),
    "assertIsNone": (AssertionKind.EXISTENCE, True),
    "assertIsNotNone": (AssertionKind.EXISTENCE, False),
    "assertIn": (AssertionKind.MEMBERSHIP, False),
    "assertNotIn": (AssertionKind.MEMBERSHIP, True),
    "assertGreater": (AssertionKind.COMPARISON, False),
    "assertGreaterEqual": (AssertionKind.COMPARISON, False),
    "assertLess": (AssertionKind.COMPARISON, False),
    "assertLessEqual": (AssertionKind.COMPARISON, False),
    "assertAlmostEqual": (AssertionKind.APPROXIMATE, False),
    "assertNotAlmostEqual": (AssertionKind.APPROXIMATE, True),
    "assertIsInstance": (AssertionKind.TYPE, False),
    "assertNotIsInstance": (AssertionKind.TYPE, True),
    "assertRaises": (AssertionKind.EXCEPTION, False),
    "assertRaisesRegex": (AssertionKind.EXCEPTION, False),
    "assertRaisesRegexp": (AssertionKind.EXCEPTION, False),
    "assertWarns": (AssertionKind.EXCEPTION, False),
    "assertCountEqual": (AssertionKind.EQUALITY, False),
    "assertListEqual": (AssertionKind.EQUALITY, False),
    "assertDictEqual": (AssertionKind.EQUALITY, False),
    "assertSetEqual": (AssertionKind.EQUALITY, False),
    "assertTupleEqual": (AssertionKind.EQUALITY, False),
    "assertMultiLineEqual": (AssertionKind.EQUALITY, False),
    "assertRegex": (AssertionKind.CUSTOM, False),
    "assertNotRegex": (AssertionKind.CUSTOM, True),
}


@dataclass
class _FileContext:
    """Cross-cutting evidence gathered while walking the whole file.

    `framework` cannot be decided per-test — a file can mix a `self.assert*`
    method with a module-level `assert`, and the surface has one `framework`
    field for the whole file — so the walk accumulates signal here and the
    top-level `extract` decides once, at the end.
    """

    saw_bare_assert: bool = False
    saw_pytest_import: bool = False
    saw_unittest_testcase: bool = False
    saw_self_assert: bool = False


@dataclass
class _BodyFindings:
    """Everything pulled out of one test's decorators and body."""

    assertions: list[Assertion] = field(default_factory=list)
    skip_markers: list[SkipMarker] = field(default_factory=list)
    mocks: list[MockUsage] = field(default_factory=list)
    retries: list[RetryWrapper] = field(default_factory=list)
    # Node ids already attributed to an assertion or a mock, so the
    # exercised-symbols pass does not also count `self.assertEqual` or
    # `mocker.patch` as "code the test exercises".
    claimed: set[int] = field(default_factory=set)


def extract(path: str, source: str) -> TestSurface:
    """Extract the `TestSurface` of one Python file.

    Never raises: a file this cannot parse is not evidence the tests are
    gone, so any failure — a syntax error, an unexpected tree shape — comes
    back as `TestSurface.unparsed` for the rules layer to treat as unknown.
    """
    try:
        tree = parse_source("python", source)
        root = tree.root_node
        if root.has_error:
            return TestSurface.unparsed(path, "python source has a syntax error", language="python")

        ctx = _FileContext()
        tests: list[TestCase] = []

        for child in root.named_children:
            if child.type in ("import_statement", "import_from_statement"):
                if "pytest" in text(child):
                    ctx.saw_pytest_import = True
                continue
            decorators, inner = _unwrap_decorated(child)
            if inner is None:
                continue
            if inner.type == "function_definition":
                case = _extract_function(inner, decorators, path, None, ctx)
                if case is not None:
                    tests.append(case)
            elif inner.type == "class_definition":
                tests.extend(_extract_class(inner, path, ctx))

        return TestSurface(
            path=path,
            language="python",
            framework=_decide_framework(ctx),
            tests=tuple(tests),
            parse_ok=True,
        )
    except Exception as exc:
        return TestSurface.unparsed(path, f"{type(exc).__name__}: {exc}", language="python")


def _decide_framework(ctx: _FileContext) -> str:
    # A bare `assert` or a pytest import is unambiguous. Absent either, fall
    # back to unittest-style evidence, and default to pytest (the more
    # permissive runner, and the one that also collects unittest suites)
    # when a file has neither signal — an empty test file, say.
    if ctx.saw_bare_assert or ctx.saw_pytest_import:
        return "pytest"
    if ctx.saw_unittest_testcase or ctx.saw_self_assert:
        return "unittest"
    return "pytest"


def _unwrap_decorated(node: Node) -> tuple[list[Node], Node | None]:
    """Peel a `decorated_definition` down to its decorators and inner def."""
    if node.type == "decorated_definition":
        decorators = [child for child in node.children if child.type == "decorator"]
        return decorators, node.child_by_field_name("definition")
    return [], node


def _looks_like_test_name(name: str) -> bool:
    """A name pytest *might* have collected, before or after an edit.

    Broader than `_is_discoverable_name` on purpose: a test renamed from
    `test_foo` to `_test_foo` must still show up in the surface — with
    `is_discoverable=False` — or the rename is invisible to VID001 rather
    than being its textbook case. Stripping leading underscores catches
    exactly that rename without also catching unrelated helpers.
    """
    return name.lstrip("_").startswith("test")


def _is_discoverable_name(name: str) -> bool:
    return name.startswith(_DISCOVERABLE_FUNCTION_PREFIX)


def _is_test_class_name(name: str) -> bool:
    return name.startswith(_DISCOVERABLE_CLASS_PREFIX)


def _has_testcase_base(superclasses: Node | None) -> bool:
    if superclasses is None:
        return False
    for base in superclasses.named_children:
        if base.type == "keyword_argument":  # e.g. `metaclass=...`, not a base class
            continue
        if last_segment(base) == _TESTCASE_BASE_NAME:
            return True
    return False


def _extract_class(class_node: Node, path: str, ctx: _FileContext) -> list[TestCase]:
    name_node = class_node.child_by_field_name("name")
    if name_node is None:
        return []
    class_name = text(name_node)
    has_testcase_base = _has_testcase_base(class_node.child_by_field_name("superclasses"))
    if has_testcase_base:
        ctx.saw_unittest_testcase = True
    # Only these two shapes are ever collected as a test class by pytest or
    # unittest; a helper class that happens to define a `test_*` method is
    # not one of them, and descending into it would invent a test that no
    # runner will ever run.
    if not (_is_test_class_name(class_name) or has_testcase_base):
        return []

    body = class_node.child_by_field_name("body")
    if body is None:
        return []

    tests: list[TestCase] = []
    for child in body.named_children:
        decorators, inner = _unwrap_decorated(child)
        if inner is not None and inner.type == "function_definition":
            case = _extract_function(inner, decorators, path, class_name, ctx)
            if case is not None:
                tests.append(case)
    return tests


def _extract_function(
    fn_node: Node,
    decorators: list[Node],
    path: str,
    class_name: str | None,
    ctx: _FileContext,
) -> TestCase | None:
    name_node = fn_node.child_by_field_name("name")
    if name_node is None:
        return None
    fn_name = text(name_node)
    if not _looks_like_test_name(fn_name):
        return None

    # A container that failed the test-class check never reaches here (see
    # `_extract_class`), so the only thing left to check is the function's
    # own name against pytest/unittest's literal collection prefix.
    is_discoverable = _is_discoverable_name(fn_name)

    qualname = f"{class_name}.{fn_name}" if class_name else fn_name
    test_id = f"{path}::{class_name}::{fn_name}" if class_name else f"{path}::{fn_name}"

    # Decorators are included in `line_start` so a finding's evidence points
    # at `@pytest.mark.skip` too, not just the `def` line below it.
    start_node = decorators[0] if decorators else fn_node
    line_start = start_node.start_point.row + 1
    line_end = fn_node.end_point.row + 1

    findings = _BodyFindings()
    for decorator in decorators:
        _process_decorator(decorator, findings, ctx)

    body = fn_node.child_by_field_name("body")
    if body is not None:
        _walk_body(body, findings, ctx)

    exercised = (
        _collect_exercised_symbols(body, findings.claimed) if body is not None else frozenset()
    )

    return TestCase(
        id=test_id,
        name=fn_name,
        qualname=qualname,
        line_start=line_start,
        line_end=line_end,
        is_discoverable=is_discoverable,
        assertions=tuple(findings.assertions),
        skip_markers=tuple(findings.skip_markers),
        mocks=tuple(findings.mocks),
        retries=tuple(findings.retries),
        exercised_symbols=exercised,
    )


def _walk_body(node: Node, findings: _BodyFindings, ctx: _FileContext) -> None:
    for child in node.children:
        if child.type in ("function_definition", "class_definition"):
            # A nested def is its own scope; its asserts and calls are not
            # this test's, whether or not the nested function ever runs.
            continue
        if child.type == "assert_statement":
            findings.assertions.append(_build_bare_assert(child))
            ctx.saw_bare_assert = True
        elif child.type == "call":
            if _handle_call(child, findings, ctx):
                findings.claimed.add(child.id)
        _walk_body(child, findings, ctx)


def _build_bare_assert(node: Node) -> Assertion:
    condition = node.named_children[0] if node.named_children else node
    kind, negated, operands, tolerance = _classify_condition(condition)
    return Assertion(
        kind=kind,
        callee="assert",
        line=node.start_point.row + 1,
        operands=operands,
        tolerance=tolerance,
        negated=negated,
    )


def _classify_condition(node: Node) -> tuple[AssertionKind, bool, tuple[str, ...], float | None]:
    if node.type == "not_operator":
        inner = node.named_children[0] if node.named_children else node
        kind, negated, operands, tolerance = _classify_condition(inner)
        return kind, not negated, operands, tolerance
    if node.type == "comparison_operator":
        return _classify_comparison(node)
    if node.type == "call":
        function_node = node.child_by_field_name("function")
        if function_node is not None and last_segment(function_node) == "isinstance":
            args = positional_args(node.child_by_field_name("arguments"))
            return AssertionKind.TYPE, False, operand_texts(args), None
    # Anything else — a bare name, an attribute lookup, a call whose result
    # is just truthy-checked — is a truthiness assertion by definition: the
    # whole expression is its own single operand.
    return AssertionKind.TRUTHINESS, False, (normalize(node),), None


def _classify_comparison(node: Node) -> tuple[AssertionKind, bool, tuple[str, ...], float | None]:
    operator_text = None
    operand_nodes: list[Node] = []
    for i in range(node.child_count):
        child = node.child(i)
        if child is None:
            continue
        if node.field_name_for_child(i) == "operators":
            if operator_text is None:  # first operator decides kind for chained comparisons
                operator_text = text(child)
        else:
            operand_nodes.append(child)
    operator_text = operator_text or "=="
    operands = operand_texts(operand_nodes)

    if operator_text in ("is", "is not"):
        # `is (not) None` proves existence, not identity with an arbitrary
        # object — that distinction is `assertIsNone` vs `assertIs` in
        # unittest, and VID005 needs it to catch a swap between the two.
        if any(child.type == "none" for child in operand_nodes):
            return AssertionKind.EXISTENCE, operator_text == "is", operands, None
        return AssertionKind.IDENTITY, operator_text == "is not", operands, None
    if operator_text in ("in", "not in"):
        return AssertionKind.MEMBERSHIP, operator_text == "not in", operands, None
    if operator_text in ("==", "!="):
        approx_call = _find_approx_call(operand_nodes)
        if approx_call is not None:
            tolerance = _approx_tolerance(approx_call)
            return AssertionKind.APPROXIMATE, operator_text == "!=", operands, tolerance
        return AssertionKind.EQUALITY, operator_text == "!=", operands, None
    return AssertionKind.COMPARISON, False, operands, None


def _find_approx_call(operand_nodes: list[Node]) -> Node | None:
    for node in operand_nodes:
        if node.type != "call":
            continue
        function_node = node.child_by_field_name("function")
        if function_node is not None and last_segment(function_node) == "approx":
            return node
    return None


def _approx_tolerance(approx_call: Node) -> float | None:
    arguments = approx_call.child_by_field_name("arguments")
    value = find_keyword(arguments, "abs")
    if value is None:
        value = find_keyword(arguments, "rel")
    return float_literal(value)


def _classify_method_assertion(name: str) -> tuple[AssertionKind, bool] | None:
    known = _ASSERT_METHOD_KIND.get(name)
    if known is not None:
        return known
    if name.startswith("assert_called") or name in _MOCK_ASSERT_NAMES:
        return AssertionKind.CALL, False
    if name == "fail":
        return AssertionKind.CUSTOM, False
    if name.startswith("assert"):
        return AssertionKind.CUSTOM, False
    return None


def _handle_call(node: Node, findings: _BodyFindings, ctx: _FileContext) -> bool:
    """Classify one `call` node in a test body. Returns whether it was claimed.

    A claimed call is an assertion, a skip, or a mock — evidence the surface
    records structurally rather than leaving in `exercised_symbols`.
    """
    function_node = node.child_by_field_name("function")
    if function_node is None:
        return False
    callee_name = last_segment(function_node)
    callee_path = normalize(function_node)
    arguments = node.child_by_field_name("arguments")
    positional = positional_args(arguments)
    line = node.start_point.row + 1

    if callee_name == "raises" and "pytest" in callee_path:
        ctx.saw_pytest_import = True
        findings.assertions.append(
            Assertion(
                kind=AssertionKind.EXCEPTION,
                callee="raises",
                line=line,
                operands=operand_texts(positional),
            )
        )
        return True

    method_kind = _classify_method_assertion(callee_name)
    if method_kind is not None:
        kind, negated = method_kind
        tolerance = (
            float_literal(find_keyword(arguments, "delta"))
            if kind is AssertionKind.APPROXIMATE
            else None
        )
        ctx.saw_self_assert = True
        findings.assertions.append(
            Assertion(
                kind=kind,
                callee=callee_name,
                line=line,
                operands=operand_texts(positional),
                tolerance=tolerance,
                negated=negated,
            )
        )
        return True

    if callee_name == "skip" and "pytest" in callee_path:
        ctx.saw_pytest_import = True
        findings.skip_markers.append(SkipMarker(reason=SkipReason.SKIP, line=line))
        return True

    if callee_name == "patch" or (callee_name in ("object", "dict") and "patch" in callee_path):
        findings.mocks.append(
            MockUsage(target=_mock_target(positional), line=line, callee=callee_path)
        )
        return True

    if callee_name == "setattr" and "monkeypatch" in callee_path:
        findings.mocks.append(
            MockUsage(target=_monkeypatch_target(positional), line=line, callee=callee_path)
        )
        return True

    return False


def _mock_target(args: list[Node]) -> str:
    if not args:
        return ""
    literal = string_literal(args[0])
    if literal is not None:
        return literal
    # `patch.object(Foo, "bar")` names its target across two arguments; a
    # plain `patch("module.func")` (handled above) never reaches here.
    if len(args) >= 2:
        second = string_literal(args[1])
        if second is not None:
            return f"{normalize(args[0])}.{second}"
    return normalize(args[0])


def _monkeypatch_target(args: list[Node]) -> str:
    """The symbol `monkeypatch.setattr(...)` replaces.

    `setattr` has two call shapes: `setattr("dotted.path", value)`, where the
    first argument already spells out the full target, and
    `setattr(obj, "name", value)`, where the target is the object and
    attribute name joined. A string-literal first argument is the signal for
    which shape this call is.
    """
    if not args:
        return ""
    first_literal = string_literal(args[0])
    if first_literal is not None:
        return first_literal
    if len(args) >= 2:
        second = string_literal(args[1])
        attribute = second if second is not None else normalize(args[1])
        return f"{normalize(args[0])}.{attribute}"
    return normalize(args[0])


def _process_decorator(decorator: Node, findings: _BodyFindings, ctx: _FileContext) -> None:
    expression = decorator.named_children[0] if decorator.named_children else None
    if expression is None:
        return
    if expression.type == "call":
        function_node = expression.child_by_field_name("function")
        arguments = expression.child_by_field_name("arguments")
    else:
        function_node = expression
        arguments = None
    if function_node is None:
        return

    path = normalize(function_node)
    name = last_segment(function_node)
    positional = positional_args(arguments)
    line = decorator.start_point.row + 1

    if "mark" in path:
        if name == "skip":
            ctx.saw_pytest_import = True
            findings.skip_markers.append(SkipMarker(reason=SkipReason.SKIP, line=line))
        elif name == "skipif":
            ctx.saw_pytest_import = True
            condition = normalize(positional[0]) if positional else None
            findings.skip_markers.append(
                SkipMarker(reason=SkipReason.SKIP_IF, line=line, expression=condition)
            )
        elif name == "xfail":
            ctx.saw_pytest_import = True
            findings.skip_markers.append(SkipMarker(reason=SkipReason.EXPECTED_FAILURE, line=line))
        elif name == "flaky":
            ctx.saw_pytest_import = True
            attempts = int_literal(find_keyword(arguments, "reruns"))
            findings.retries.append(RetryWrapper(callee="flaky", line=line, max_attempts=attempts))
        elif name == "repeat":
            ctx.saw_pytest_import = True
            attempts = int_literal(positional[0]) if positional else None
            findings.retries.append(RetryWrapper(callee="repeat", line=line, max_attempts=attempts))
        return

    if name == "expectedFailure":
        findings.skip_markers.append(SkipMarker(reason=SkipReason.EXPECTED_FAILURE, line=line))
        return
    if name == "skip" and "unittest" in path:
        findings.skip_markers.append(SkipMarker(reason=SkipReason.SKIP, line=line))
        return
    if name == "skipIf" and "unittest" in path:
        condition = normalize(positional[0]) if positional else None
        findings.skip_markers.append(
            SkipMarker(reason=SkipReason.SKIP_IF, line=line, expression=condition)
        )
        return
    if name == "flaky":
        # The standalone `flaky` package: `@flaky(max_runs=N, min_passes=M)`,
        # keyword or positional.
        attempts = int_literal(find_keyword(arguments, "max_runs"))
        if attempts is None and positional:
            attempts = int_literal(positional[0])
        findings.retries.append(RetryWrapper(callee="flaky", line=line, max_attempts=attempts))
        return
    if name == "patch" or (name in ("object", "dict") and "patch" in path):
        findings.mocks.append(MockUsage(target=_mock_target(positional), line=line, callee=path))
        return


_DUNDER_PREFIX = "__"
_DUNDER_SUFFIX = "__"


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith(_DUNDER_PREFIX) and name.endswith(_DUNDER_SUFFIX)


def _collect_exercised_symbols(node: Node, claimed: set[int]) -> frozenset[str]:
    found: set[str] = set()

    def walk(inner: Node) -> None:
        for child in inner.children:
            if child.type in ("function_definition", "class_definition"):
                continue
            if child.type == "call" and child.id not in claimed:
                function_node = child.child_by_field_name("function")
                if function_node is not None:
                    name = last_segment(function_node)
                    if name and not _is_dunder(name):
                        found.add(name)
            walk(child)

    walk(node)
    return frozenset(found)
