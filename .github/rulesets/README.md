# The one thing this repository could not do for itself

**Status: applied 2026-08-22. The `audit` job blocks a merge.**

Everything else in this repository is enforced by something in this
repository. This was the one exception. Whether a check can block a merge is
a repository *setting*, held on GitHub's side, changeable only by someone
with admin rights on `ChelseaKR/cairn`. No file could grant itself that
power, and a repository that implied otherwise would have been making
exactly the claim this project exists to disprove — a check that could have
blocked a merge, did not, and looked like it had.

`main.json` is the ruleset that was written out in full, committed and
reviewable, before anyone applied it — and the ruleset now active on the
repository (id `21218790`, `enforcement: active`) is that same file, applied
by the command below and reapplied once more the same session to pick up
`main.json`'s own subsequent changes (the CI matrix and `image`/`package`
jobs PR #19 added). Since it took effect:

- the `audit` job runs on every pull request and writes a verdict, same as
  before;
- a pull request cannot be merged while any of the nine required checks —
  `audit` among them — is red, or while `main` has moved out from under it
  (`strict_required_status_checks_policy`);
- direct pushes to `main` no longer work; every change from PR #22 onward
  has gone through a pull request.

The honest test was not that the API call below returned 201. Two separate
things were checked, not assumed:

- **The positive case.** Real pull request #22 needed all nine required
  checks green before it could merge, and did.
- **The negative case**, because a rule nobody has watched fail is a rule
  nobody has verified — a throwaway pull request (#23) with one required
  check (`core`) deliberately broken by an unimportable module. GitHub's own
  `mergeStateStatus` read `BLOCKED` while that check was red, and an actual
  `gh pr merge` attempt was refused outright: *"Pull request #23 is not
  mergeable: the base branch policy prohibits the merge."* Closed without
  merging, branch deleted, immediately after.

If this repository ever needs the ruleset reapplied — a misclick, a repo
transfer, `ruleset-check.yml`'s weekly check finding it silently gone —
here is how it was done the first time.

## Applying it

Either route produces the same ruleset. Both need admin on the repository.

**In the browser.** Settings → Rules → Rulesets → New ruleset → *Import a
ruleset*, and upload `main.json`. Read the summary page before saving; it
lists the same rules in the same order.

**From the command line.**

```sh
gh api --method POST repos/ChelseaKR/cairn/rulesets \
  --input .github/rulesets/main.json
```

Check what took effect, rather than assuming:

```sh
gh api repos/ChelseaKR/cairn/rulesets --jq '.[] | "\(.id)  \(.name)  \(.enforcement)"'
gh api repos/ChelseaKR/cairn/rulesets/RULESET_ID --jq '.rules'
```

The honest test is not that the API returned 201. It is that a pull request
with a failing `audit` job cannot be merged. Open one and try.

## What it does, rule by rule, and what each one costs

| Rule | Effect | Cost |
|---|---|---|
| `required_status_checks` | The nine CI checks must pass on the head commit before a merge. `strict_required_status_checks_policy` also requires the branch to be up to date with `main`, so a check cannot pass against a stale base. | A required check that stops reporting blocks every merge until the ruleset is edited. That is fail-closed, and it is the right direction, but it is a real cost: renaming a CI job silently breaks merges. `tests/test_rulesets.py` fails when the job names in the workflow and the contexts here drift apart, which is the warning you get before that happens. |
| `pull_request` | Changes reach `main` through a pull request. Required status checks are evaluated on the merge; this is what makes them a gate rather than a decoration. | **Direct pushes to `main` stop working.** This repository's history is a build-in-public record of small direct commits, and applying this ends that style. That is a deliberate trade and it is the maintainer's to make. |
| `deletion`, `non_fast_forward` | `main` cannot be deleted or force-pushed. | None worth the words. A rewritten history is a destroyed audit record. |

`required_approving_review_count` is **0**, because a solo maintainer cannot
approve their own pull request and a rule that cannot be satisfied is a
repository nobody can merge into. It should become `1` on the day there is a
second contributor; that is the only number in this file that is a placeholder
rather than a decision.

`bypass_actors` is **empty, on purpose**. An admin bypass hands the ability to
skip the gate to the one person most likely to be in a hurry at 2am, and a gate
with a bypass list is a gate that reports to people who are not using it.

## The nine contexts, and why they are spelled like that

A required status check is matched by the **name of the check run**, which for
GitHub Actions is the job's `name:` — with the matrix values appended in
parentheses for a matrix job, even when the job sets a name of its own. Those
strings were read off a real run rather than guessed:

```sh
gh api repos/ChelseaKR/cairn/commits/main/check-runs --jq '.check_runs[].name'
```

They contain em dashes, because the job names do. Copy them exactly; a context
that matches no check is a rule that never fires, and a rule that never fires
looks exactly like a rule that passes.

`live` is the newest of them, and it is required for the same reason the
others are, not because it is the gate. The gate is `audit`: offline,
deterministic, grading the committed evidence. `live` asks the same questions
of a running server and fails when the answers differ from the ones the gate
graded. A difference there means the merge gate is describing something other
than what a user meets, which is not a thing to merge past — but it is also
not the gate's own verdict, and `audit` neither waits on this job nor can be
made green by it.
