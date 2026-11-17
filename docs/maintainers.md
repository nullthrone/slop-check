# Maintainer setup

One-time settings the repository owner makes on GitHub so that the gate runs on its own
(see D10 and section 8 of architecture.md). Menu paths follow the GitHub documentation at the time of
writing. Points that the documentation does not state explicitly are marked "not confirmed in the
docs"; check them once after setup with a test pull request.

## 1. General settings

Settings > General, section "Pull Requests":

- Allow squash merging. The automerge workflow merges with squash, and the ruleset below
  requires a linear history. Merge commits can be turned off.
- Select "Allow auto-merge".
- Select "Automatically delete head branches".

Settings > Advanced Security: enable "Private vulnerability reporting" (used by
[SECURITY.md](../SECURITY.md) and the issue chooser).

## 2. Ruleset for main

Settings > Rules > Rulesets > New branch ruleset. Target the default branch and set enforcement
to Active.

- Restrict deletions.
- Block force pushes.
- Require linear history.
- Require a pull request before merging, with 0 required approvals and "Require review from Code
  Owners" selected. Allowed merge method: squash.
- Require status checks to pass, with the checks `ci-gate` and `llm-gate`. `ci-gate` is a job of
  the ci workflow; `llm-gate` is a commit status that llm-eval.yml posts, so leave its source on
  "any source". Leave "Require branches to be up to date" off, otherwise every merge forces the
  other open pull requests to rebase and rerun.
- Bypass list: add the repository admin role, so you can merge your own changes to protected
  paths (GitHub does not let you approve your own pull request) and pull requests on which
  `llm-gate` cannot be posted.

Not confirmed in the docs: that "Require review from Code Owners" is enforced when required
approvals is 0. The rulesets page allows 0 approvals and the code owner option separately; test it
with a pull request that touches `.github/`, which must wait for your review, and one that touches
only `patterns/`, which must merge without it.

## 3. Actions settings

Settings > Actions > General:

- Workflow permissions: read access for the `contents` and `packages` permissions (the restricted
  setting). Every workflow requests the permissions it needs per job.
- "Allow GitHub Actions to create and approve pull requests": leave it off. No workflow creates
  or approves pull requests.
- Approval for running fork pull request workflows from contributors: "Require approval for
  first-time contributors who are new to GitHub".

## 4. Secret and budget

Settings > Secrets and variables > Actions > New repository secret: `OPENROUTER_API_KEY`.
Without it the ci and models workflows still run. llm-eval then passes candidates with a notice
and fails edits to scored LLM-judged patterns; measure skips corpus generation and LLM judging;
conformance is skipped.

The code enforces a monthly cap of 26 USD (about 25 EUR) from `governance/thresholds.yaml` before
every call. As a second line of defense, set a credit limit on the key itself in OpenRouter
(Key limit in the key dialog, monthly reset) to the same amount.

## 5. Labels

The automerge workflow creates `needs-owner` on first use. Create `pattern-proposal` and
`false-positive` for the issue forms, which apply them to new issues.

## 6. Branches data and dist

Workflows create both orphan branches on their first run; nobody pushes to them by hand. After the
settings above, start the bots in this order from the Actions tab (Run workflow):

1. models: writes `models/lock.json` to `data`.
2. measure: fetches the human corpus, generates the AI corpus, measures every pattern, opens the
   issue "Measurement report YYYY-MM" and dispatches release with the tag `catalog-YYYY.MM.DD`.
3. release: runs from that dispatch and fills `dist` plus the first GitHub release. A tag `v*` on
   `main` also creates a release.

The README and the site link to `releases/latest/download/slop-check.zip` and
`releases/latest/download/system-prompt.md`, so these links work once the first release exists.

Merges that auto-merge performs after the workflow token enabled it are reported not to trigger
`push` workflows (not confirmed in the docs; the documentation says only that events caused by
the workflow token start no new runs). release.yml therefore also runs daily and rebuilds `dist`
when `main` or the measurements changed since the last build. Conformance runs monthly in any case;
after a change to `skill/` you can start it by hand.

## 7. How the research routine contributes

The weekly research routine is a contributor like any other. It works on a fork or a branch,
commits under its own agent identity, and opens a pull request with new patterns, sources or
language realizations. The same gates apply: `ci-gate` measures deterministic detectors on the
dev split, `llm-gate` judges `llm` detectors, and content-only pull requests merge on their own.
A research pull request that touches anything outside `patterns/`, `sources/` and the
contributor docs gets the label `needs-owner` and waits for your review.

Give the routine a token of its own (a GitHub App or a fine-grained token limited to this
repository with contents and pull request write access). A pull request opened with a workflow's
own token starts its checks only after a maintainer approves the run.

## 8. Adjusting thresholds

All admission numbers, weights, provisional values and budget caps live in
`governance/thresholds.yaml`. Change them in a pull request; CODEOWNERS makes it wait for your
review, and the pull request description should say why.

- `admission.candidate.pr_gate` applies from the next ci and llm-eval run.
- `admission.core` and `admission.fading` apply from the next measurement on the holdout split.
  Run measure by hand if the change should take effect before the monthly run.
- `weights.from_lift` changes how measured weights follow from the lift (next measurement).
- `initial_core` lists the patterns that start as core and their provisional weights.
  `verdict_provisional` holds the verdict thresholds used until a measurement provides measured
  ones. Both stop mattering for a pattern once a measurement covers it.
- `budget` caps take effect for the next privileged job.

Model choices are not thresholds: `evals/models.yaml` holds selection rules, and the weekly models
workflow resolves them. Change a rule there when a model family should be added or dropped.

## 9. Routine work

- Dependabot opens weekly pull requests for actions and Python dependencies. They touch protected
  paths and wait for your review.
- Pull requests labeled `needs-owner` wait for you. Everything else either merges by itself or
  fails a check that the contributor can see in the run.
- Read the monthly measurement issue. It shows which patterns were promoted or demoted, and
  which ones could not be measured.
