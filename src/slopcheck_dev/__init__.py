"""Development and CI tooling for slop-check (docs/architecture.md sections 3, 5, 6 and 7).

Modules:

    patterns      load pattern, source and governance YAML files
    validate      schema and rule checks (``slopcheck-dev validate``)
    regex_safety  static and runtime checks for detector regexes
    fixtures      example checks against the engine (``slopcheck-dev check-fixtures``)
    status        effective status and weight derivation (section 6.4)
    build         catalog compilation and skill packaging (``slopcheck-dev build``)
    gate          pull request admission rules (``slopcheck-dev gate``)
    cli           the ``slopcheck-dev`` entry point
    evals         corpora, measurement, conformance, budget and model resolution

Unlike ``slopcheck``, this package may use the dev dependencies (PyYAML, jsonschema).
"""

__version__ = "0.1.0"
