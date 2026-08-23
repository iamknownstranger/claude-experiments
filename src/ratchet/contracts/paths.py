"""Glob matching for test-path classification.

`fnmatch` is not usable here: its `*` crosses directory separators, so
`**/test_*.py` and `*/test_*.py` would mean the same thing and `src/*.py` would
match `src/a/b.py`. Since deciding "is this a test file" gates every AST rule,
the matcher is written out properly rather than approximated.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ratchet.contracts.config import RatchetConfig

_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|\[[^\]]*\]")


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    """Translate a git-style glob into an anchored regex."""
    out: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(pattern):
        out.append(re.escape(pattern[pos : match.start()]))
        token = match.group()
        if token == "**/":
            # Zero or more leading directories, so `**/x.py` also matches `x.py`.
            out.append(r"(?:[^/]+/)*")
        elif token == "**":
            out.append(r".*")
        elif token == "*":
            out.append(r"[^/]*")
        elif token == "?":
            out.append(r"[^/]")
        else:
            out.append(f"[{token[1:-1]}]")
        pos = match.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile(f"^{''.join(out)}$")


def matches_glob(path: str, pattern: str) -> bool:
    """True when `path` matches a git-style glob, `**` included."""
    return _compile(pattern).match(_normalize(path)) is not None


def matches_any(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(matches_glob(path, pattern) for pattern in patterns)


def is_test_path(path: str, config: RatchetConfig) -> bool:
    """Classify a path as a test file under the repository's policy.

    Ignore patterns win over test patterns, so a repo can carve out fixtures and
    generated tests it does not want the ratchet applied to.
    """
    normalized = _normalize(path)
    if matches_any(normalized, config.ignore_globs):
        return False
    return matches_any(normalized, config.test_globs)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")
