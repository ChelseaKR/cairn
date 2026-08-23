# Cutting a release

**Status: the workflow exists and is exercised on every change; nobody has
cut a release with it yet.** `.github/workflows/release.yml` fires on a
published GitHub Release and does two things — publishes a source
distribution and a wheel to PyPI, and pushes a container image to GHCR —
and both halves are proven continuously, not just described: `ci.yml`'s
`package` job builds the real sdist and wheel and runs the installed
console script against the demo corpus on every pull request, and `ci.yml`'s
`image` job does the same for the container. What has never run for real is
the last step of each — the actual `pypi-publish` upload and the actual
`docker push` — because no GitHub Release has ever been published. This page
is what has to happen, once, before the first one can be.

Nothing here is legal advice or a claim that publishing has happened; it is
the checklist for the day it does.

## One-time: register a PyPI trusted publisher

PyPI trusted publishing lets this workflow authenticate by proving to PyPI,
via GitHub's own OIDC token, that it *is* this repository's `release.yml`
running from a `release` event — no API token generated, stored as a
repository secret, or rotated by hand. Setting it up is a PyPI account
action only the project's owner can take; nothing in this repository can do
it, the same way nothing in this repository can apply the branch-protection
ruleset (`.github/rulesets/README.md`) — both are settings held on someone
else's service.

The package has never been published, so there is no existing PyPI project
to configure. PyPI's answer to that is a **pending publisher**: register the
trust relationship for a project name that does not exist yet, and PyPI
creates the project automatically the first time this workflow's upload
actually succeeds.

1. Sign in at [pypi.org](https://pypi.org) with the account that should own
   the `cairn-assistant` project.
2. Go to
   [pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/).
3. Under "Add a new pending publisher", fill in exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `cairn-assistant` |
   | Owner | `ChelseaKR` |
   | Repository name | `cairn` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   The **Environment name** field matters and is easy to skip: leaving it
   blank registers trust for the workflow file running under *any*
   GitHub Actions environment, where filling it in — matching the `pypi`
   environment `release.yml`'s `pypi` job already declares — means only a
   run under that specific environment can publish. The narrower binding is
   the one worth having.
4. Save it. Nothing else is required on PyPI's side; the next successful
   run of the `pypi` job creates the project and uploads to it in the same
   step.

There is no equivalent one-time step for the container job — it
authenticates with the repository's own `GITHUB_TOKEN`, already scoped by
the `packages: write` permission `release.yml` declares.

## Cutting the release itself

An agent does not push a tag in this repository — see CHANGELOG.md's own
header for why — so this part is the maintainer's, by hand:

1. Bump the version in `cairn/__init__.py`, `pyproject.toml`, and
   `CITATION.cff` together (`tests/test_cli.py`'s
   `TestTheVersionIsRecordedOnce` fails if they disagree), and move
   CHANGELOG.md's `### Unreleased` section to a new dated `## X.Y.Z`
   heading.
2. `git tag -a vX.Y.Z -m "..."` and `git push --tags`.
3. Publish a GitHub Release from that tag. This is the event `release.yml`
   waits for; nothing publishes before this step.
4. Watch the `release` workflow run. If the `pypi` job fails on
   `The release tag names the version this package actually is`, the tag
   and `cairn.__version__` disagree — fix step 1 and cut the release again
   before troubleshooting anything about PyPI itself.

## After the first real push to GHCR

Check the package's visibility at
`github.com/ChelseaKR/cairn/pkgs/container/cairn` (Package settings →
Change visibility). A container pushed with `GITHUB_TOKEN` is not
guaranteed to inherit the repository's own public visibility on every
GitHub configuration, and `docker pull ghcr.io/chelseakr/cairn` for someone
who is not signed in is the honest test of whether it did — the same
"check what took effect, rather than assuming" the ruleset's own README
asks for the branch-protection settings.

## What this page is not

Not a claim that either publish target is live today. `README.md`'s
Standards Conformance table and this page should be read together on that
point: the workflow, the CI jobs that continuously prove it builds what it
claims to, and this checklist all exist now; a `pip install cairn-assistant`
or a `docker pull ghcr.io/chelseakr/cairn` that actually resolves to
something does not, until the steps above have happened once.
