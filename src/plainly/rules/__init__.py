"""All rules register themselves on import."""

from plainly.rules import clarity, padding, structure, tells  # noqa: F401  (registration)
from plainly.rules.base import REGISTRY, Example, Rule

__all__ = ["REGISTRY", "Example", "Rule"]
