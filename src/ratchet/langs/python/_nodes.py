"""Small tree-sitter node helpers shared across the Python extractor.

Split out from `extractor.py` because these are pure syntax-tree utilities —
text extraction, argument lookup — with no knowledge of what a test is. That
keeps the file that *does* know what a test is (`extractor.py`) readable.
"""

from __future__ import annotations

from tree_sitter import Node


def text(node: Node) -> str:
    """Decode a node's source text.

    `Node.text` is `bytes | None` — it is only `None` for nodes tree-sitter
    could not slice (which does not happen for nodes obtained by walking a
    successfully parsed tree), so the empty-string fallback is unreachable in
    practice but keeps this total under mypy --strict.
    """
    return (node.text or b"").decode("utf-8", errors="replace")


def normalize(node: Node) -> str:
    """Normalized source text: collapsed whitespace, no leading/trailing gaps.

    Used for everything that feeds `Assertion.signature()` — operands and
    callees — so that reformatting a test (wrapping a long call across lines,
    say) does not read as a changed assertion.
    """
    return " ".join(text(node).split())


def last_segment(node: Node) -> str:
    """The rightmost name in a call target: `pytest.mark.skip` -> `skip`.

    This is what distinguishes *which* assertion or marker was used,
    independent of the receiver spelling (`self` vs `cls` vs an instance
    variable, `pytest` vs a renamed import).
    """
    if node.type == "attribute":
        attribute = node.child_by_field_name("attribute")
        return text(attribute) if attribute is not None else text(node)
    return text(node)


def positional_args(arguments: Node | None) -> list[Node]:
    """Every argument in a call's `argument_list` that is not `name=value`."""
    if arguments is None:
        return []
    return [child for child in arguments.named_children if child.type != "keyword_argument"]


def find_keyword(arguments: Node | None, name: str) -> Node | None:
    """The value node of `name=...` in a call's `argument_list`, if present."""
    if arguments is None:
        return None
    for child in arguments.named_children:
        if child.type != "keyword_argument":
            continue
        name_node = child.child_by_field_name("name")
        if name_node is not None and text(name_node) == name:
            return child.child_by_field_name("value")
    return None


def float_literal(node: Node | None) -> float | None:
    """Parse a node as a float literal, or None when it isn't one.

    Used for tolerances (`delta=`, `abs=`, `rel=`): VID004 compares these
    numerically, so a value that is not a literal (a variable, an expression)
    must come back as None rather than a wrong guess.
    """
    if node is None:
        return None
    try:
        return float(text(node))
    except ValueError:
        return None


def int_literal(node: Node | None) -> int | None:
    """Parse a node as an int literal, or None when it isn't one."""
    if node is None:
        return None
    try:
        return int(text(node))
    except ValueError:
        return None


def string_literal(node: Node) -> str | None:
    """The value of a plain string literal, or None for anything else.

    Deliberately refuses f-strings (`interpolation` children): the whole
    point of extracting a mock target or skip condition as a string is that
    it names something fixed, and an interpolated value is not that.
    """
    if node.type != "string":
        return None
    if any(child.type == "interpolation" for child in node.children):
        return None
    return "".join(text(child) for child in node.children if child.type == "string_content")


def operand_texts(nodes: list[Node]) -> tuple[str, ...]:
    return tuple(normalize(node) for node in nodes)
