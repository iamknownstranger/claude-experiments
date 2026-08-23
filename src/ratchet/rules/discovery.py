"""Rule discovery — import every rule module so it can self-register.

`RuleBase.__init_subclass__` registers a rule the moment its module is
imported, but nothing imports rule modules on its own. The obvious fix — a
list of imports in `rules/__init__.py` — is exactly the file several agents
would edit on the same day to add a rule, guaranteeing merge conflicts. This
walks the package instead, so adding a rule module is enough on its own.
"""

from __future__ import annotations

import importlib
import pkgutil

import ratchet.rules
from ratchet.contracts import RuleBase, registered_rules


def discover_rules() -> tuple[type[RuleBase], ...]:
    """Import every module in `ratchet.rules`, then return the registry.

    Skips this module itself (importing it can't register anything) and any
    `_`-prefixed module, so private helpers shared between rule files don't
    need to look like rules.
    """
    for module_info in pkgutil.iter_modules(
        ratchet.rules.__path__, prefix=f"{ratchet.rules.__name__}."
    ):
        leaf = module_info.name.rsplit(".", 1)[-1]
        if leaf == "discovery" or leaf.startswith("_"):
            continue
        importlib.import_module(module_info.name)
    return registered_rules()
