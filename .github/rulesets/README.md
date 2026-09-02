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
repository (id `21223426`, `enforcement: active`) is that same file. Applied
2026-08-22, and reapplied twice more the same day to pick up `main.json`'s
own subsequent changes: once for the CI matrix and `image`/`package` jobs
PR #19 added, once more when `gauntlet` (#31) joined the required contexts.
Reapplying is the same command every time — delete the ruleset that no
longer matches, `gh api --method POST` the current file — because a
`required_status_checks` list is checked as a whole, not merged field by
field. Since it took effect:

- the `audit` job runs on every pull request and writes a verdict, same as
  before;
- a pull request cannot be merged while any of the ten required checks —
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
| `required_status_checks` | The ten CI checks must pass on the head commit before a merge. `strict_required_status_checks_policy` also requires the branch to be up to date with `main`, so a check cannot pass against a stale base. | A required check that stops reporting blocks every merge until the ruleset is edited. That is fail-closed, and it is the right direction, but it is a real cost: renaming a CI job silently breaks merges. `tests/test_rulesets.py` fails when the job names in the workflow and the contexts here drift apart, which is the warning you get before that happens. |
| `pull_request` | Changes reach `main` through a pull request. Required status checks are evaluated on the merge; this is what makes them a gate rather than a decoration. | **Direct pushes to `main` stop working.** This repository's history is a build-in-public record of small direct commits, and applying this ends that style. That is a deliberate trade and it is the maintainer's to make. |
| `deletion`, `non_fast_forward` | `main` cannot be deleted or force-pushed. | None worth the words. A rewritten history is a destroyed audit record. |

`required_approving_review_count` is **0**, because a solo maintainer cannot
approve their own pull request and a rule that cannot be satisfied is a
repository nobody can merge into. It should become `1` on the day there is a
second contributor; that is the only number in this file that is a placeholder
rather than a decision.

### Why the owner can bypass

`bypass_actors` holds **exactly one actor: the repository owner**
(`RepositoryRole` 5, `bypass_mode: "always"`), and that is deliberate and
permanent.

This file used to say the opposite. It argued that the list was "empty, on
purpose", on the grounds that an admin bypass hands the ability to skip the
gate to the person most likely to be in a hurry at 2am. That argument is not
wrong about the risk; it is wrong about which risk is larger, and the larger
one has already happened. **An agent applied a ruleset with no bypass and
locked the owner out of their own repository**, and restoring access took a
sweep across eight rulesets in this portfolio. The standing instruction since
is that the owner must always be able to bypass, in any repository.

So an empty `bypass_actors` list here is not a stricter gate. It is the
lockout, and anything checking this ruleset has to treat it as a failure
rather than as a pass. Three things enforce that, and they are deliberately
not one thing:

- `tests/test_rulesets.py::test_only_the_repository_owner_can_bypass_it`
  asserts this file holds *exactly* that one actor -- so a second bypass,
  granted to a team, a GitHub App or another role, fails, and so does the
  owner's own going missing.
- `ruleset_conformance.py` checks the enforced ruleset and this file
  **independently** against that actor, rather than only comparing the two to
  each other. Comparing them would report conformance on the day both were
  emptied together, which is the incident recurring with a green tick on it.
- `.github/workflows/ruleset-check.yml` runs that comparison weekly and fails
  while any difference stands.

If you are reading this because the empty list looks more secure and you are
about to restore it: reapplying a ruleset file that omits the owner's bypass
is how the lockout happens. Do not.

And if you are reading this because a weekly `ruleset-check` run told you the
owner's bypass is not enforced, **read the ruleset yourself before you touch
anything**:

```sh
gh api repos/ChelseaKR/cairn/rulesets/21223426 --jq '.bypass_actors'
```

That report was wrong once, on 2026-08-31, and it was wrong in the direction
that gets somebody locked out. GitHub omits `bypass_actors` from a ruleset
payload when the caller may not administer the repository, and the workflow's
own token may not; `ruleset_conformance.py` read the missing field as an empty
list and said the bypass had been removed from a ruleset that had carried it,
untouched, for five days. Issue #80 was that, not a drift.

The module now tells a field that is absent from one that is empty: absent is
exit 4, "could not run", with its own message and no tracking issue behind it,
while an empty list that is genuinely there is still the incident and still a
failure. If the command above prints the owner's actor, nothing is wrong with
the repository and nothing needs reapplying.

## The ten contexts, and why they are spelled like that

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

`live` asks the same questions of a running server and fails when the
answers differ from the ones the gate graded. A difference there means the
merge gate is describing something other than what a user meets, which is
not a thing to merge past — but it is also not the gate's own verdict, and
`audit` neither waits on this job nor can be made green by it.

`gauntlet` is a second, independent interlock: a pinned adversarial-suite
harness (`ChelseaKR/gauntlet`, `gauntlet.pin`) grading the same engine
against prompt-injection, refusal and grounding cases `audit`'s own suites
do not cover. Same shape as `live` — required for the same reason, not
because it is the gate `audit` is.
