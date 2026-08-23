# CHANGELOG


## v0.2.0 (2026-08-23)

### Continuous Integration

- Gate PyPI publishing behind an explicit opt-in
  ([`a326239`](https://github.com/iamknownstranger/claude-experiments/commit/a32623971155e4c53541a256a6f8d656190fd686))

The environment gate did not hold the job back — GitHub creates a referenced environment on demand,
  so the job ran and failed `invalid-publisher` against a PyPI project that does not exist yet.

The release job itself is working: v0.1.0 is tagged and released. Only the publish step needs
  configuration, so it now waits on a repository variable rather than staying red on every merge. A
  permanently red job trains everyone to ignore red, which is the habit this project exists to
  prevent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01RGsXThBrCenzRJGz6DGckd

### Documentation

- **contracts**: Document FileChange field semantics
  ([`986da46`](https://github.com/iamknownstranger/claude-experiments/commit/986da4637b41c5ac630a2a44335e7086cf3f8356))

WP1 had to infer from the parser spec that `base_path` is the pre-rename path set only for renames,
  and that the content fields are None for binary and one-sided changes. Three more work packages
  will read this contract; the next reader should not have to infer it too.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01RGsXThBrCenzRJGz6DGckd

### Features

- **diff**: Parse unified diffs and load changesets from git
  ([#2](https://github.com/iamknownstranger/claude-experiments/pull/2),
  [`0cf83db`](https://github.com/iamknownstranger/claude-experiments/commit/0cf83db21dd33e33b23bac209a565ecbea01ab99))

Rules never touch git — if it is not on the FileChange, it did not happen. This package is the sole
  source of truth for what changed.

Handles renames, binary files, /dev/null sides, omitted hunk counts, missing trailing newlines, and
  git's trailing-tab disambiguation on paths containing spaces. Both base and head line numbers are
  tracked explicitly rather than reconstructed, because a finding that cites the wrong line teaches
  reviewers to distrust the whole tool.

- **langs**: Extract TestSurface from pytest and unittest files
  ([#3](https://github.com/iamknownstranger/claude-experiments/pull/3),
  [`c26109a`](https://github.com/iamknownstranger/claude-experiments/commit/c26109a3880ec87202551c40a42072e843a26d7d))

Maps every assert form to a ranked AssertionKind, and captures skips, mocks, retry wrappers and
  discoverability.

A test renamed from test_foo to _test_foo stays in the surface with is_discoverable=False rather
  than vanishing from it — a silent test deletion has to remain visible for VID001 to catch it.

Parse failures return TestSurface.unparsed rather than an empty surface, so a syntax error is never
  read downstream as "the tests are gone".

- **rules**: Detect lowered CI thresholds and excluded tests
  ([#1](https://github.com/iamknownstranger/claude-experiments/pull/1),
  [`16ce7be`](https://github.com/iamknownstranger/claude-experiments/commit/16ce7befc1e4d9771a3b34914d671008432de414))

VID009 catches the gate being weakened instead of the code being made to pass it — coverage floors
  dropped, continue-on-error added, --no-verify, strict flipped off, test timeouts doubled, retry
  wrappers around test steps.

VID010 catches tests that still exist but stopped running, via --ignore, norecursedirs,
  testPathIgnorePatterns, coverage omit, or .gitignore.

Both fire only on unambiguous evidence: a numeric threshold needs exactly one removed and one added
  match to pair, and list-valued settings are diffed as sets over whole-file content so reformatting
  cannot misfire. Rules also self-register through package discovery rather than a shared import
  list, which would otherwise be the file every rule author edits on the same day.


## v0.1.0 (2026-08-23)

### Continuous Integration

- Pin uv to a version that can read the lockfile
  ([`606bbf1`](https://github.com/iamknownstranger/claude-experiments/commit/606bbf16f93eb58a40a13a2b4ce1183b1c080cc9))

Every job died at `uv sync` before running a single check: uv.lock is at revision 3, which uv 0.5.11
  cannot parse. Pinning CI below the uv that wrote the lockfile makes the pin actively harmful
  rather than reproducible.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01RGsXThBrCenzRJGz6DGckd

- Stop tracking subagent worktrees
  ([`d1a4523`](https://github.com/iamknownstranger/claude-experiments/commit/d1a45231b1f016d26fea72dfad94c1226cb06bb9))

`git add -A` swept the parallel agents' worktrees in as embedded git repos. They are working state,
  not repository content.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01RGsXThBrCenzRJGz6DGckd

### Features

- **contracts**: Scaffold Ratchet with frozen contracts and CI/CD
  ([`7d5bd65`](https://github.com/iamknownstranger/claude-experiments/commit/7d5bd65d676b79e0dee769e470caa63fb8092e61))

Ratchet is a merge gate for agent-authored PRs. It does not look for bugs — it asks whether the
  green build was earned, by comparing the verification strength of a test suite before and after a
  change.

This lands the foundation every later work package depends on:

- `contracts/` — TestSurface with ranked assertion kinds, Finding/Evidence, FileChange/Hunk,
  RatchetConfig, TrustScore, and the RuleBase contract. Rules self-register by subclassing, so
  parallel rule authors never share a registry file to conflict over. - A proper glob matcher:
  fnmatch's `*` crosses directory separators, which would make `src/*.py` match `src/a/b.py` and
  silently misclassify test files. - CI: ruff, mypy --strict, pytest on 3.11–3.13, plus a corpus
  precision gate and a self-check job that stay inactive until their inputs exist. - Release:
  semantic-release on every merge, GitHub Release always, PyPI via OIDC trusted publishing once the
  environment is configured. - CODEOWNERS over contracts, tests, workflows and the corpus — since
  agents merge their own PRs here, a test suite editable by the actor it constrains is not a
  constraint.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01RGsXThBrCenzRJGz6DGckd
