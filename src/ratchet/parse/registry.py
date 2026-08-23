"""Tree-sitter grammar loading, shared by every language extractor.

Kept deliberately language-agnostic: this module knows how to get from a
canonical language name (or a file extension) to a parsed tree, and nothing
about what any particular grammar's nodes mean. That semantic knowledge lives
in `ratchet.langs.*`, so a Python extractor and a TypeScript extractor can be
built by different people against this one shared floor without either
touching the other's code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import cache

import tree_sitter_javascript as _tsjavascript
import tree_sitter_python as _tspython
import tree_sitter_typescript as _tstypescript
from tree_sitter import Language, Node, Parser, Query, QueryCursor, Tree

# Extension -> canonical language name. `detect_language` walks this, and
# every extractor keys its own grammar lookups off these same names, so this
# map is the single place a new file suffix gets taught to the tool.
_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".tsx": "tsx",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

# Grammar constructors, keyed by the same canonical names used above. Each
# returns the `PyCapsule` a `tree_sitter.Language` wraps; the grammar packages
# ship no type stubs (see the mypy override in pyproject.toml), which is why
# this dict's value type below is spelled out explicitly rather than inferred.
_GRAMMARS: dict[str, Callable[[], object]] = {
    "python": _tspython.language,
    "typescript": _tstypescript.language_typescript,
    "tsx": _tstypescript.language_tsx,
    "javascript": _tsjavascript.language,
}


def detect_language(path: str) -> str | None:
    """Map a file path to a canonical language name by its extension.

    Returns None for anything ratchet has no grammar for, so callers can skip
    unknown files instead of guessing at a language.
    """
    # Longest suffix first so a hypothetical multi-part extension can't be
    # shadowed by a shorter one earlier in iteration order.
    for suffix in sorted(_EXTENSIONS, key=len, reverse=True):
        if path.endswith(suffix):
            return _EXTENSIONS[suffix]
    return None


@cache
def _get_language(language: str) -> Language:
    try:
        factory = _GRAMMARS[language]
    except KeyError as exc:
        raise ValueError(f"no tree-sitter grammar registered for {language!r}") from exc
    return Language(factory())


@cache
def get_parser(language: str) -> Parser:
    """A `Parser` for `language`, built once per process and reused.

    Every rule in a single check run wants a parser for the same handful of
    languages, and constructing one is not free, so callers share the cached
    instance rather than each building their own.
    """
    return Parser(_get_language(language))


def parse_source(language: str, source: str) -> Tree:
    """Parse `source` with the grammar for `language`."""
    return get_parser(language).parse(source.encode("utf-8"))


@cache
def _compile_query(language: str, query_source: str) -> Query:
    # Query source strings are static per call site (a query template a rule
    # or extractor wrote once), so caching by their text avoids recompiling
    # the same pattern on every file in a run.
    return Query(_get_language(language), query_source)


def iter_captures(language: str, tree: Tree, query_source: str) -> Iterator[tuple[str, Node]]:
    """Run a tree-sitter query against `tree` and yield `(capture_name, node)` pairs.

    Both language extractors group and filter captures differently — by
    pattern, by name, by containing test — so this stays a flat iterator
    rather than baking in any particular grouping of its own.
    """
    cursor = QueryCursor(_compile_query(language, query_source))
    captures = cursor.captures(tree.root_node)
    for name, nodes in captures.items():
        for node in nodes:
            yield name, node
