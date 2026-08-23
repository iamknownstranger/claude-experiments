"""Tests for `ratchet.parse`: grammar loading, caching, and language detection."""

from __future__ import annotations

import pytest
from tree_sitter import Parser, Tree

from ratchet.parse import detect_language, get_parser, iter_captures, parse_source


class TestDetectLanguage:
    @pytest.mark.parametrize(
        ("path", "language"),
        [
            ("src/ratchet/langs/python/extractor.py", "python"),
            ("stubs/module.pyi", "python"),
            ("src/component.tsx", "tsx"),
            ("src/component.ts", "typescript"),
            ("src/index.js", "javascript"),
            ("src/index.jsx", "javascript"),
            ("src/index.mjs", "javascript"),
            ("src/index.cjs", "javascript"),
            ("nested/dir/test_thing.py", "python"),
        ],
    )
    def test_known_extensions(self, path: str, language: str) -> None:
        assert detect_language(path) == language

    @pytest.mark.parametrize("path", ["README.md", "Makefile", "data.json", "no_extension"])
    def test_unknown_extension_returns_none(self, path: str) -> None:
        assert detect_language(path) is None

    def test_tsx_is_not_shadowed_by_ts(self) -> None:
        # A naive `path.endswith(".ts")` check would also match `.tsx` files,
        # since "component.tsx".endswith(".ts") is False but the reverse
        # ordering bug (checking ".ts" before ".tsx") is exactly what this
        # guards against.
        assert detect_language("component.tsx") == "tsx"
        assert detect_language("component.ts") == "typescript"


class TestGetParser:
    def test_returns_a_parser(self) -> None:
        parser = get_parser("python")
        assert isinstance(parser, Parser)

    def test_cached_across_calls(self) -> None:
        assert get_parser("python") is get_parser("python")

    def test_distinct_languages_get_distinct_parsers(self) -> None:
        assert get_parser("python") is not get_parser("javascript")

    def test_unknown_language_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="python-cobol"):
            get_parser("python-cobol")


class TestParseSource:
    def test_parses_python(self) -> None:
        tree = parse_source("python", "def test_foo():\n    assert 1 == 1\n")
        assert isinstance(tree, Tree)
        assert tree.root_node.type == "module"
        assert not tree.root_node.has_error

    def test_parses_typescript(self) -> None:
        tree = parse_source("typescript", "function testFoo(): void { expect(1).toBe(1); }\n")
        assert isinstance(tree, Tree)
        assert not tree.root_node.has_error

    def test_parses_javascript(self) -> None:
        tree = parse_source("javascript", "test('foo', () => { expect(1).toBe(1); });\n")
        assert isinstance(tree, Tree)
        assert not tree.root_node.has_error

    def test_syntax_error_is_visible_on_the_tree(self) -> None:
        # `parse_source` never raises on bad syntax — tree-sitter is
        # error-tolerant by design — so callers detect a bad parse via
        # `root_node.has_error`, not via an exception.
        tree = parse_source("python", "def test_foo(:\n    pass\n")
        assert tree.root_node.has_error


class TestIterCaptures:
    def test_yields_capture_name_and_node(self) -> None:
        tree = parse_source("python", "def test_foo():\n    pass\n\ndef test_bar():\n    pass\n")
        query = "(function_definition name: (identifier) @name)"
        captures = list(iter_captures("python", tree, query))
        names = sorted(node.text.decode() for _, node in captures if node.text is not None)
        assert names == ["test_bar", "test_foo"]
        assert all(name == "name" for name, _ in captures)

    def test_no_matches_yields_nothing(self) -> None:
        tree = parse_source("python", "x = 1\n")
        query = "(function_definition name: (identifier) @name)"
        assert list(iter_captures("python", tree, query)) == []
