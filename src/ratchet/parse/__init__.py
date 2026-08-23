"""Tree-sitter infrastructure shared by every `ratchet.langs.*` extractor.

This package owns grammar loading and query execution; it has no opinion
about what any grammar's node types mean. See `ratchet.parse.registry` for
the implementation.
"""

from __future__ import annotations

from ratchet.parse.registry import (
    detect_language,
    get_parser,
    iter_captures,
    parse_source,
)

__all__ = [
    "detect_language",
    "get_parser",
    "iter_captures",
    "parse_source",
]
