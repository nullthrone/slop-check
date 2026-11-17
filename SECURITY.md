# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open the repository's Security tab, go to
Advisories and choose "Report a vulnerability", or use
[this form](https://github.com/nullthrone/slop-check/security/advisories/new) directly. Please do
not open a public issue for a vulnerability. Describe the affected file or workflow, the impact
and the steps to reproduce.

## Scope

- Workflows in `.github/workflows/`: anything that lets pull request code or pull request data
  reach a privileged job (secrets, write tokens, the `data` or `dist` branch), merge without the
  required checks, or spend the evaluation budget beyond its caps.
- The engine in `src/slopcheck/` and the bundled `scripts/` of the skill package: code execution
  from crafted input or catalog files, regular expressions that hang on adversarial text, any
  network access in skill mode.
- The skill instructions in `skill/`: prompt injection through audited texts or pattern data
  that makes a host model ignore the user, leak data or claim that a text was written by an AI.
- Evaluation code in `src/slopcheck_dev/`: handling of pull request files and corpus data,
  leaks of the API key into logs, caches or artifacts.

Out of scope: false positives and false negatives of patterns (use the issue forms) and
findings in third-party services such as OpenRouter or GitHub itself.

## Supported versions

Only the latest release and the current `main` branch receive fixes.
