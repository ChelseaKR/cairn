# Cutting a release

**Status: done once, for `v0.2.0`, 2026-08-22.** `.github/workflows/release.yml`
fires on a published GitHub Release and does two things — publishes a source
distribution and a wheel to PyPI, and pushes a container image to GHCR. Both
halves had been proven continuously before that, not just described:
`ci.yml`'s `package` job builds the real sdist and wheel and runs the
installed console script against the demo corpus on every pull request, and
`ci.yml`'s `image` job does the same for the container. What neither of
those ever exercised is the last step of each — the actual `pypi-publish`
upload and the actual `docker push` — because until `v0.2.0`, no GitHub
Release had ever been published.

**The first real run found a bug this repository's own continuous proof
could not see.** The `container` job succeeded; the `pypi` job failed with
`docker: Error response from daemon: manifest unknown`. The action pin —
`pypa/gh-action-pypi-publish@a892a5a61159132606e93a2fa6f4358831b04d26 #
v1.14.2` — was the SHA of the `v1.14.2` **tag object**, not the commit it
points to; an annotated tag's ref resolves one dereference short of the
commit GitHub actually built an image for. Every check before the real
release passed regardless, because none of them invoke this specific
action — only a published Release does. Fixed in
[PR #22](https://github.com/ChelseaKR/cairn/pull/22) (the corrected SHA,
plus a comment naming the verification command so the next pin bump doesn't
repeat it), then re-run against the existing `v0.2.0` release via
`workflow_dispatch` — no new tag needed, since nothing about the release
itself, only the workflow that publishes it, had been wrong. Confirmed live
by asking PyPI directly (`https://pypi.org/pypi/cairn-assistant/json`), not
by trusting the green check alone.

This page remains the checklist for the next one. Nothing here is legal
advice.

## One-time: register a PyPI trusted publisher

PyPI trusted publishing lets this workflow authenticate by proving to PyPI,
via GitHub's own OIDC token, that it *is* this repository's `release.yml`
running from a `release` event — no API token generated, stored as a
repository secret, or rotated by hand. Setting it up is a PyPI account
action only the project's owner can take; nothing in this repository can do
it, the same way nothing in this repository can apply the branch-protection
ruleset (`.github/rulesets/README.md`) — both are settings held on someone
else's service.

Before `v0.2.0`, the package had never been published, so there was no
existing PyPI project to configure. PyPI's answer to that is a **pending
publisher**: register the trust relationship for a project name that does
not exist yet, and PyPI creates the project automatically the first time
this workflow's upload actually succeeds — which is exactly what happened;
`cairn-assistant` now exists on PyPI because of that first real run, not
before it.

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

A container pushed with `GITHUB_TOKEN` is not guaranteed to inherit the
repository's own public visibility on every GitHub configuration, so this
was checked rather than assumed: a token requested from `ghcr.io/token`
with no credentials of any kind, scoped only to `repository:chelseakr/cairn:pull`,
fetched the `v0.2.0` manifest and got `HTTP 200`. Nobody signed in gets it —
the package's visibility setting is at
`github.com/ChelseaKR/cairn/pkgs/container/cairn` (Package settings → Change
visibility) if that ever needs re-checking after a permissions change.

## What this page is not

No longer a claim that no publish has happened — it had not, through
`v0.1.0`, and now has, as of `v0.2.0` (2026-08-22), confirmed against both
registries directly rather than trusted from a green workflow check. What
this page still is not: a guarantee that the *next* release goes as
smoothly. The first run found one real bug in `release.yml` that nothing
before it could see (above) — the kind of thing that stays true of any
"exercised in CI but never for real" path until it has actually run for
real once.
