"""Evaluation system: corpora, measurement, skill conformance, budget and model resolution.

See docs/architecture.md section 6. Modules:

- ``models``: self-updating resolution of ``evals/models.yaml`` selectors against OpenRouter
- ``openrouter``: chat client with cache, retries, usage accounting and budget checks
- ``budget``: spend ledger and hard caps
- ``corpus``: human corpus (pinned public datasets) and AI corpus generation
- ``judge``: LLM judges for ``kind: llm`` patterns
- ``measure``: per-pattern metrics and ``measurements.json``
- ``conformance``: runs the built skill on several model families
- ``cli``: ``register(subparsers)`` for ``slopcheck-dev``
"""

from ._common import split_of

__all__ = ["split_of"]
