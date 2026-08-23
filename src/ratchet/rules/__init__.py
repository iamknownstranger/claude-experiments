"""Deterministic VID* rules.

Each module defines one `RuleBase` subclass and self-registers on import.
There is no import list here on purpose — see `discovery.discover_rules`,
which walks this package instead — so two rules added on the same day never
conflict on this file.
"""
