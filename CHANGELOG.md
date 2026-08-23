# CHANGELOG


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
