"""The real `SurfaceProvider`: changed file in, parsed `TestSurface` out.

This is the seam between `ratchet.langs.*` and `ratchet.rules.*`. Rules ask for
a surface and never learn which extractor produced it, which is what lets a new
language be added without touching a single rule.

Language packages are resolved by import path rather than registered in a table
here, for the same reason rules are discovered by walking their package: a
shared registry file is the one file every language author would edit, and so
the one file they would all conflict on.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache

from ratchet.contracts import (
    ChangeKind,
    FileChange,
    RatchetConfig,
    Side,
    TestSurface,
    is_test_path,
)
from ratchet.parse import detect_language

# Canonical language names from `detect_language` mapped to the `ratchet.langs`
# subpackage that handles them. jest and vitest parse the same way across all
# three JS-family dialects, so they share one extractor.
_LANGUAGE_PACKAGES: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "tsx": "typescript",
    "javascript": "typescript",
}

Extractor = Callable[[str, str], TestSurface]


@cache
def _load_extractor(language: str) -> Extractor | None:
    """Resolve a language's `extract`, or None if ratchet cannot handle it yet.

    A missing package is a normal state, not an error: the TypeScript extractor
    lands after the Python one, and until it does, `.ts` files simply have no
    surface. Returning None keeps that indistinguishable from "not a language we
    support" so no rule has to special-case a half-built install.
    """
    package = _LANGUAGE_PACKAGES.get(language)
    if package is None:
        return None
    try:
        module = importlib.import_module(f"ratchet.langs.{package}")
    except ImportError:
        return None
    extract = getattr(module, "extract", None)
    return extract if callable(extract) else None


@dataclass
class ExtractorSurfaceProvider:
    """Parses test files on demand, once per (path, side).

    Every AST rule asks for both sides of every changed test file, so without
    memoisation a dozen rules would re-parse the same file two dozen times. The
    cache is per-instance and per-run, which is the natural lifetime: one
    `ratchet check` invocation.
    """

    config: RatchetConfig = field(default_factory=RatchetConfig.default)
    _cache: dict[tuple[str, Side], TestSurface | None] = field(default_factory=dict, repr=False)

    def surface(self, change: FileChange, side: Side) -> TestSurface | None:
        key = (change.path, side)
        if key not in self._cache:
            self._cache[key] = self._extract(change, side)
        return self._cache[key]

    def _extract(self, change: FileChange, side: Side) -> TestSurface | None:
        if change.is_binary or not is_test_path(change.path, self.config):
            return None

        language = detect_language(change.path)
        if language is None:
            return None

        extract = _load_extractor(language)
        if extract is None:
            return None

        content = change.base_content if side == "base" else change.head_content
        if content is None:
            # One side genuinely has no file. For an added file the base is
            # empty; for a deleted one the head is. That is a real fact about
            # the change, not a parse failure — returning the empty surface is
            # what makes a deleted test file read as removed tests rather than
            # as unknown. Anything else would silently un-detect the loudest
            # signal the product has.
            if _side_is_absent(change, side):
                return TestSurface.empty(change.path, language=language)
            # Content was simply not loaded (a diff parsed without blobs).
            # Unknown, not empty.
            return None

        return extract(change.path, content)


def _side_is_absent(change: FileChange, side: Side) -> bool:
    """True when the file legitimately does not exist on that side."""
    if side == "base":
        return change.kind is ChangeKind.ADDED
    return change.kind is ChangeKind.DELETED
