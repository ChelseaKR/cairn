# Standards: mechanical lane

> **This is the body of a pull request that merged on 2026-08-18, kept as a
> record of that change.** It is not a description of the repository today and
> nothing reads it. Its two numbers were true when it was written and are not
> now: `mypy --strict` reported 28 findings then, reports zero today and runs
> in `make verify`; four functions were over the complexity limit then and 12
> are now. `README.md`'s Standards Conformance row is the current statement,
> and `tests/test_code_quality.py` is what holds it.

The largest of these branches, because this repository had no Makefile, no
lockfile, no security workflow, and no `SECURITY.md`, `CONTRIBUTING.md`,
`CODEOWNERS`, or ADR log. Twenty-one automated checks were failing; nineteen of
them now pass, and the two that do not are named at the bottom rather than
worked around.

Nothing here changes what Cairn answers, how it retrieves, or how it is graded.

## Actions are pinned

Thirteen `uses:` in `ci.yml` referenced a moving major tag. Each is now pinned
to a full commit SHA with a version comment, matching what `pages.yml` already
did.

The SHAs are the exact commits those major tags resolve to today
(`actions/checkout` v4.4.0, `setup-python` v5.6.0, `setup-node` v4.4.0, `cache`
v4.3.0, `upload-artifact` v4.6.2), so nothing about what runs has changed. What
has changed is that a moved tag can no longer change it. `.github/dependabot.yml`
is added in the same breath, because a pin with nothing raising it is a frozen
dependency rather than a careful one.

## A local gate, in a Makefile

`make verify` runs the lockfile check, ruff, mypy, and the suite under coverage
with an 85 percent branch floor. Measured coverage is 89 percent, so the floor
sits below what the tree does, with room for a refactor and not for a
regression.

It is deliberately **not** a wrapper around `./plumbline-gate.sh`. The merge
gate stays a separate, fail-closed job that resolves an external auditor over
the network, and folding it into `make verify` would invite "verify passed" to
be read as "the gate passed". The Makefile header and `CONTRIBUTING.md` both
say which is which.

`uv.lock` and `.python-version` come with it, so the development toolchain is a
reviewable resolution rather than whatever pip picked that morning. The runtime
is still standard library only and still has nothing to lock, and `make demo`
runs the no-install path the README opens with, so that claim keeps being
exercised.

## Security scanning, in its own workflow

`.github/workflows/security.yml` adds gitleaks over the full history, Semgrep,
and `pip-audit` over the development toolchain. All three run on push, on pull
request, and weekly. None can be skipped into a green check, and none has a
`continue-on-error`, for the reason `ci.yml` already argues at length about its
audit job.

They are kept out of `ci.yml` on purpose: the `core` job's argument is that it
needs nothing from outside this repository, and a scanner that has to be
fetched would undercut it.

## Documents

`SECURITY.md` names three vulnerability classes specific to what this project
claims, rather than reciting a generic list: an answer no source supports, a
refusal that leaks what the corpus contains, and any path that makes the merge
gate report green without grading. `CONTRIBUTING.md` explains the two gates and
which one is which. `docs/adr/0000-record-architecture-decisions.md` starts the
log and says explicitly that it is not being backfilled, because records dated
today for decisions made months ago are the same dishonesty in a different
file. `.github/CODEOWNERS` and `.pre-commit-config.yaml` are one-liners.

## The CHANGELOG heading, and why it is an `h3`

`tests/test_cli.py` requires the first `##` heading in `CHANGELOG.md` to be the
current version, because a changelog whose newest version section describes a
release that does not exist is worse than one that is behind. An `## Unreleased`
heading breaks that test.

So unreleased work sits under `### Unreleased`, one level down, and the file's
preamble now says why and says that it becomes a version section when the
version is bumped. That keeps the repository's own test and records the work,
rather than picking one.

## Two gaps this branch declares instead of hiding

Both are in the README's new conformance table and in the configuration comment
at the point where each is set:

* **mypy runs in its default mode, not `--strict`.** Strict reports 28 findings
  on this tree. Fixing them is a typing pass, not a settings change.
* **The complexity limit of 10 is configured, and the `C90` rule is not
  switched on.** Four functions are over it: `audit_guard.py`'s
  `suite_defaults` at 12, `regression_findings` at 11 and `render_terminal` at
  11, and `cairn/server.py`'s `build_handler` at 26. Turning the rule on is a
  refactor. The alternative was four silent per-file ignores, which is the
  manoeuvre the rest of this repository exists to make impossible.

## Not in this branch

* **`requires-python` stays at `>=3.11`.** Raising it to 3.12 would drop a
  version `ci.yml` currently tests in its matrix. That is a support decision.
* **No hardened release workflow.** Tagging remains a manual act by the
  maintainer, as `CHANGELOG.md` describes.
* **No `docs/I18N.md`.** Three languages ship, one of them right to left. What
  is committed to beyond those three is a scope decision, so the README row
  records the absence rather than inventing an answer.
* **`ci.yml` does not call the Makefile targets.** Its `core` job still runs
  `pip install -e ".[dev]"`, `ruff check .`, and the unittest discovery
  directly. Rewiring it to `make verify` would remove a real drift risk, but it
  would also introduce `uv` into a job whose whole argument is minimal
  dependencies, and it is not something this change could exercise. Left as
  follow-up.

## Verification

`make verify` exits 0: 358 tests, one skip, 89 percent branch coverage against
the 85 percent floor, ruff clean, mypy clean. The site staleness check and the
docs tests, which execute every command block in `README.md` and
`docs/demo.md`, both pass with the new README section in place.
