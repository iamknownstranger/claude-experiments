"""`.ratchet.yml` — the policy a repository sets for itself.

Two principles shape this schema:

1. **Defaults must be conservative.** A gate that fires on ordinary refactors
   gets switched off within a week, and a switched-off gate catches nothing.
2. **Every escape hatch is attributable.** Losses of verification strength can
   be accepted, but only by a named human in a commit trailer — never silently
   by config. Ratchet's job is to make the decision visible, not to forbid it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ratchet.contracts.findings import Severity

DEFAULT_TEST_GLOBS: tuple[str, ...] = (
    "**/test_*.py",
    "**/*_test.py",
    "**/tests/**/*.py",
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.test.js",
    "**/*.test.jsx",
    "**/*.spec.ts",
    "**/*.spec.tsx",
    "**/*.spec.js",
    "**/*.spec.jsx",
    "**/__tests__/**/*.ts",
    "**/__tests__/**/*.js",
)

DEFAULT_JUSTIFICATION_TRAILER = "Ratchet-Justification"


class RuleSetting(BaseModel):
    """Per-rule overrides. Omitted fields fall back to the rule's own defaults."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    severity: Severity | None = None
    penalty: int | None = Field(default=None, ge=0)

    @field_validator("penalty")
    @classmethod
    def _sane_penalty(cls, value: int | None) -> int | None:
        if value is not None and value > 100:
            raise ValueError("penalty cannot exceed the 100-point trust budget")
        return value


class OracleSettings(BaseModel):
    """Engine 2 — held-out acceptance tests generated from the spec.

    Off by default: it costs API calls and needs a linked issue, so it is opt-in
    per repository rather than something that surprises a first-time user.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: str = "claude-opus-5"
    max_tests: int = Field(default=8, ge=1, le=50)
    effort: str = "high"


class RatchetConfig(BaseModel):
    """The whole of `.ratchet.yml`."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    test_globs: list[str] = Field(default_factory=lambda: list(DEFAULT_TEST_GLOBS))
    ignore_globs: list[str] = Field(default_factory=list)

    fail_under: int = Field(default=70, ge=0, le=100)
    """Trust score below which `ratchet check` exits non-zero."""

    rules: dict[str, RuleSetting] = Field(default_factory=dict)

    allow_justification: bool = True
    justification_trailer: str = DEFAULT_JUSTIFICATION_TRAILER

    oracle: OracleSettings = Field(default_factory=OracleSettings)

    @field_validator("version")
    @classmethod
    def _known_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError(f"unsupported .ratchet.yml version {value}; expected 1")
        return value

    def setting_for(self, rule_id: str) -> RuleSetting:
        return self.rules.get(rule_id, RuleSetting())

    def is_enabled(self, rule_id: str) -> bool:
        return self.setting_for(rule_id).enabled

    def severity_for(self, rule_id: str, default: Severity) -> Severity:
        return self.setting_for(rule_id).severity or default

    def penalty_for(self, rule_id: str, default: int) -> int:
        override = self.setting_for(rule_id).penalty
        return default if override is None else override

    @classmethod
    def default(cls) -> RatchetConfig:
        return cls()
