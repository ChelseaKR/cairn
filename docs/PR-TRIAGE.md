# Pull request triage, 2026-08-28

Seven pull requests were open against `main` at `5221556` when this was
written: #71, #70, #69, #66, #65, #63, #62. This file records what each one
actually is, what state it is actually in, and what to do with it.

> **#71 was squash-merged as `8e0e5e0` while this triage was being written**,
> which is the recommendation below arriving before the file did. Everything
> was recomputed against the new `main` and **nothing changed**: the conflict
> counts are identical (#70 and #69 thirteen, #66 ten, #65 eight, #63 seven,
> #62 two), and so are the conflicting files. That is worth stating rather than
> quietly re-running, because a squash merge gives `8e0e5e0` a single parent
> and no shared history with `cf03c41`, so the prediction had to be re-derived
> rather than assumed. The practical difference is that the hazards in "Non-diff
> hazards" are now **live** rather than prospective: `cairn/server.py` conflicts
> against `main` today, and `cairn/tabular.py`, `tests/test_followup.py` and
> `tests/test_ui.py` auto-merge silently against `main` today.

Every merge state below was **computed**, not read off the pull request page.
GitHub's `mergeStateStatus` is a cached answer that is `UNKNOWN` until it is
asked for and stale afterwards, so each head was merged against `origin/main`
locally with `git merge-tree --write-tree --messages`, which reports conflicts
by name and exits non-zero. The legacy three-argument `git merge-tree` was not
used anywhere: it reports differently and has already misread a genuinely
conflicting set as clean once in this portfolio.

## Group counts

| Group | Count | Which |
|---|---|---|
| Merges clean, CI green on the proposed commit | 1 | #71 (since merged as `8e0e5e0`) |
| Cumulative snapshot stack, all conflicting, none tested at head | 5 | #70, #69, #66, #65, #63 |
| Conflicting, CI green, content wholly contained in the stack | 1 | #62 |

Six of the seven conflict with `main`. One of the seven has ever been through
CI in the form it is proposing to merge, and it is not one of the five that
present as ordinary feature branches.

## Per-pull-request

| PR | Base | Real merge state (computed) | CI classification | Recommendation |
|---|---|---|---|---|
| [#71](https://github.com/ChelseaKR/cairn/pull/71) audit: three gates that could not fail | `main` | **CLEAN** — `merge-tree` exit 0, no conflicts | **Genuine, green.** All 13 checks SUCCESS on head `cf03c41`. The prior head `fdb9e23` failed `gauntlet` for real; the head commit fixes it | **Merge first** — done, squashed as `8e0e5e0` |
| [#70](https://github.com/ChelseaKR/cairn/pull/70) fix(followup): the store never held a timestamp | `main` | **CONFLICTING** — 13 files | **Absent.** Zero check runs on head `5f528ba` | **Rebase, then rework, then merge.** The stack tip: delivers all of #69, #66, #65, #63, #62. Its own top commit ships two decorative tests and three false claims — see below |
| [#69](https://github.com/ChelseaKR/cairn/pull/69) refactor: the last five under the limit | `main` | **CONFLICTING** — 13 files | **Absent.** Zero check runs on head `345cb4c` | **Close as superseded by #70** |
| [#66](https://github.com/ChelseaKR/cairn/pull/66) refactor: seven functions under the limit | `main` | **CONFLICTING** — 10 files | **Absent.** Zero check runs on head `8714f39` | **Close as superseded by #70** |
| [#65](https://github.com/ChelseaKR/cairn/pull/65) docs(audit): the multi-turn gap is a defect | `main` | **CONFLICTING** — 8 files | **Absent.** Zero check runs on head `390a714` | **Close as superseded by #70** |
| [#63](https://github.com/ChelseaKR/cairn/pull/63) feat(corpus): French has a document | `main` | **CONFLICTING** — 7 files | **Absent.** Zero check runs on head `1f0874f` | **Close as superseded by #70** |
| [#62](https://github.com/ChelseaKR/cairn/pull/62) test(query): split_intents cannot drop a field | `main` | **CONFLICTING** — 2 files (`README.md`, `WORKLOG.md`) | **Genuine, green.** All 13 checks SUCCESS on head `9378aaf` | **Close as superseded by #70.** Its guard does not deliver its title, and the same guard is byte-identical in #70, so fix it there rather than here |

Every one of the seven targets `main` directly. None is based on another, which
matters for the next section.

## The stack, and why it is not one

Five pull requests share the merge base `9ac093e` and are each a rebased
**superset** of the one before. They are not a stack of dependent changes; they
are five snapshots of one continuous line of work, each opened as if it were
independent.

```
origin/main  5221556
     |
     |  (merge base for all five: 9ac093e)
     |
     +-- #63  1f0874f   5 commits   48 files
     |          `-- split_intents test + French corpus
     |
     +-- #65  390a714   6 commits   49 files   = #63 + multi-turn docs
     |
     +-- #66  8714f39   7 commits   53 files   = #65 + complexity 12 -> 5
     |
     +-- #69  345cb4c   8 commits   53 files   = #66 + complexity 5 -> 0, C90 on
     |
     +-- #70  5f528ba  10 commits   56 files   = #69 + followup fix + roadmap
                `-- THE TIP. Contains all of the above.

     +-- #62  9378aaf   (base f669c9a)  22 files
                `-- its one substantive file, tests/test_query.py, is
                    byte-identical in #70 (blob b986068f)
```

Established by content, not by title:

- **No ancestry.** `git merge-base --is-ancestor` is false for every adjacent
  pair. Each branch was rebased, so the commits are copies with fresh hashes,
  not shared history.
- **Identical patches.** The `split_intents` commit appears in all five plus
  #62 with one patch-id, `7bb02422ae1fb44d86aa4867c4d66e8c00092585`.
- **Strict file-set containment.** Every file touched by #62, #63, #65, #66 and
  #69 is also touched by #70. Nothing is left behind.
- **Byte-identical blobs.** Comparing each earlier head's files against #70's:
  #69 differs in 4 files, #66 in 10, #65 in 10, #63 in 12, #62 in 10 — and in
  every case the differing files are only the four narrative documents each
  snapshot legitimately extends (`CHANGELOG.md`, `README.md`, `WORKLOG.md`,
  `docs/roadmap.md`) plus files a *later* pull request changed again. Every
  source file, test file and corpus file is identical in #70. `site/index.html`
  and the whole `plumbline/bundle/` are one blob each across all five.

**Merging #70 delivers the other four, and #62, in full.** Because this
repository squash-merges, the four will **not** auto-close. They will sit open
showing diffs that no longer add anything, which is exactly the shape that has
already caused confusion twice in this portfolio today. Close them by hand.

The two refactor pull requests are worth separating from the general case:
#66 takes the over-complexity count from twelve to five and #69 takes it from
five to zero and switches `C90` on in `pyproject.toml`'s `select`. Those are
genuinely successive stages of one job rather than the same work twice, but
#69 contains #66 whole, so only #69's content needs to land — and it lands
inside #70.

## Merge state, in detail

| PR | Conflicting files |
|---|---|
| #71 | none |
| #70 | `CHANGELOG.md`, `CONTRIBUTING.md`, `DESIGN.md`, `README.md`, `WORKLOG.md`, `cairn/server.py`, `cairn/session.py`, `docs/demo.md`, `docs/roadmap.md` (add/add), `plumbline/bundle/checksums.json`, `pyproject.toml`, `site/index.html`, `tests/test_code_quality.py` (add/add) |
| #69 | the same 13 |
| #66 | 10, dropping `CONTRIBUTING.md`, `cairn/session.py`, `cairn/server.py` and adding `tests/test_code_quality.py` |
| #65 | 8 |
| #63 | 7 |
| #62 | `README.md`, `WORKLOG.md` |

The conflicts have a single cause, and it is not a content disagreement. `main`
squash-merged #60 and #61 as `f669c9a` and `5221556`; all six branches still
carry their own unsquashed copies of that same work (`b9ff949`, `4919b0c`, and
in five of them `9a94a1d`). Git is being asked to merge the same changes twice.
A rebase onto `5221556` drops the duplicates and most of this disappears.

**The conflict set does not shrink if #71 lands first.** Merging #70 against a
tree that already contains #71 produces the same 13 conflicts.

## Ruleset bypass

**No open pull request removes the repository-admin bypass, and one records
it.** This was checked by grepping every head's full diff for
`bypass` / `ruleset` / `RepositoryRole` / `actor_id`, and by listing each
branch's changes under `.github/`.

- **#71 adds it, deliberately.** `.github/rulesets/main.json` on `main` carries
  `"bypass_actors": []`. #71 changes that to record the standing actor:

  ```json
  "bypass_actors": [
    {
      "actor_id": 5,
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ]
  ```

  This is the committed file catching up with the enforced one. It is the
  intended state and it should not be read as a defect or "fixed" back to an
  empty list. #71 also replaces the weekly `ruleset-check` job's active-ruleset
  *count* with a real comparison against the committed file, in
  `ruleset_conformance.py`, and makes the job fail rather than only file an
  issue. With the bypass recorded, that comparison passes; with it removed from
  the file, the job would start failing every week against a repository that is
  configured the way its owner wants it.

- **#70, #69, #66, #65, #63 and #62 touch nothing under `.github/` at all.**
  Their only match on those words is one unchanged prose row in `README.md`
  describing CI, which happens to sit inside the README conflict region. There
  is no ruleset change hiding in any of them.

One thing to carry forward: that README row still describes `ruleset-check.yml`
as re-checking "that an active ruleset still exists", which is what #71 stops
being true. See the hazards below — the row is inside a file that conflicts in
all five stack pull requests.

## Dominant defect class: gates that cannot fail

- **#71's own subject.** It removes three gate shapes and fixes the two defects
  they were hiding, in `cairn/server.py` (a JSON body that parses but is not an
  object killing the handler thread) and `cairn/tabular.py` (an ambiguity rule
  the docstring promised and the code never implemented, propped up by a
  `bindings` list nothing read). Both fixes are present in the diff and #71's
  full check set is green on the exact commit proposed.

- **#71's last commit is itself an instance of the class.** `cf03c41`,
  "the gate needs a real PATH, which only running it could show", fixes a gate
  that passed until it was actually executed — the previous head `fdb9e23`
  failed the `gauntlet` job for real. A gate that only fails when run is the
  same defect wearing the opposite costume.

- **The evidence bundle's hash chain is blind to files never written.**
  `bundle_checksums()` in `cairn/record.py` builds its digest map by walking
  `bundle_dir.iterdir()`, so it hashes whatever happens to be on disk. A bundle
  file that was never written is simply absent from `checksums.json`, and
  `bundle_sha256` — derived from the entries that *are* listed — stays
  internally consistent. Nothing compares the file list against
  `manifest.json`'s declared `files`. This is pre-existing on `main`, not
  introduced by any open pull request, but #63's bundle changes run through it.
  Every committed bundle was verified to match its own committed contents
  (`main` and #71 hash to `9d86048c…`; #63, #65, #66, #69 and #70 all hash to
  `124f7e4a…`), so nothing is currently wrong — the check just could not tell
  us if it were.

- **#62's guard names two fields it never checks, and #70 carries the same
  guard.** `tests/test_query.py`'s new class compares `dataclasses.fields()`
  against two dicts, `TRACE_MERGE` and `CANDIDATE_MERGE`, so a field added and
  not recorded does fail. But `CANDIDATE_MERGE` names `lexical` and `dense` with
  a treatment and asserts neither. Dropping `lexical=candidate.lexical` or
  `dense=candidate.dense` from the merge in `cairn/query.py:119-120` leaves the
  **entire 807-test suite green**, proved by mutation. `dense` is the textbook
  case of a bound with data too far apart to exercise it: the fixture calls
  `split_intents(..., dense_weight=0.0)`, where the correct value of `dense`
  equals the dataclass default, and no test anywhere calls `split_intents` with
  a non-zero `dense_weight`, so the hybrid split path is entirely untested.
  Removing the candidate cap, or dropping a candidate outright, is also
  invisible. This test is byte-identical in #70, so the gap ships with the tip.

- **Two of that guard's three union fields have an unreachable failure
  branch.** The loop holds `query_terms`, `unmatched` and `ignored` to "union
  across parts". In the fixture, `unmatched` is `['worki']` for part 0 and `[]`
  for part 1, and `ignored` is `['the']` for both — so for those two, the union
  and "just pick part 0" are the same answer. Reintroducing the exact #46 bug
  (`unmatched=traces[0].unmatched`, `ignored=traces[0].ignored`) leaves the
  suite green. Only `query_terms` has parts disjoint enough to distinguish
  them. The commit recognised this hazard and built a fixture guard for
  `matched` only.

- **A new field can still be added silently; only an unrecorded one cannot.**
  Adding a field to `RetrievalTrace` and leaving `TRACE_MERGE` alone fails the
  test by name. Adding the field **and** one dict key, with the merge still
  never touching it, passes all 807 tests. The guarantee delivered is "a new
  field cannot be added without a decision being recorded", not the title's
  "cannot silently drop a merged field". `lexical` and `dense` are the living
  proof: both recorded, neither asserted.

- **#70's headline fix is zero lines of code, and its new tests do not fail
  against the code it says it fixes.** The claim is true —
  `cairn/followup.py`'s docstring said the store held "a contact and a
  timestamp" and `record()` has never written one. But the fix changes only
  that docstring and the key order of two examples in `docs/followup.md`.
  Restoring the pre-fix `cairn/followup.py` under the new tests leaves all 33
  green: **zero of the three new tests fail against the unfixed module.** They
  hold the documentation half and nothing else.

- **`test_nothing_about_when_or_from_where_is_kept` cannot be the signal it
  claims to be.** It uses `assertNotIn` against exact key names, which on a
  dict is exact membership, not substring. Mutation results: adding
  `received_at` does not fire it; `client_ip` does not; `session_id` does not.
  Only the literal key `timestamp` fires it, and by then the field-set equality
  above it has already failed on the same record. Its failure branch is
  unreachable as an independent signal.

- **#70's own proof-of-work claim is wrong, and this was measured.** The commit
  message, `WORKLOG.md` and `docs/roadmap.md` all say adding a `received_at` to
  `record()` "fails three tests and names the field". It fails **four**, one of
  them the pre-existing `test_recording_writes_one_json_line`, and the test
  written to name the field is not among them. The friction the roadmap
  describes as newly added already existed: full dict equality in
  `test_recording_writes_one_json_line` has always failed on any added key.

- **`test_the_published_line_is_the_line_that_is_written` does not test
  bytes.** Its docstring says `Not "the fields match" but "the bytes match"`.
  It `json.loads` the written line and re-serialises it with the test's own
  `sort_keys=True` before comparing. Changing `record()` to
  `sort_keys=False` leaves all 33 tests green. Key order is the very defect
  this pull request exists to fix, and the guard is blind to it on the code
  side.

- **A red check fixed inside its own branch, still showing red.** #63, #65 and
  #66's most recent runs are failures, all of them `core, windows` and all of
  them the ruff path-separator defect that `9a94a1d` fixes. That commit is in
  all five branches *and* on `main` via #61's squash. The red is stale twice
  over. Nobody should read those three as broken.

- **No pull request is failing for a reason that belongs to `main`.** This was
  checked rather than assumed, because a red `main` would reclassify every
  inherited failure. `origin/main` at `5221556` is green on all three
  workflows — `ci`, `security` and `pages`. The category is empty here.

## Non-diff hazards

These are invisible in a diff and would not be caught by merging one pull
request at a time and watching it go green.

1. **Two tested numbers live in a file that conflicts five ways.**
   `README.md` publishes both the dataset id and the test count, and
   `tests/test_docs.py` holds both to reality:
   `test_every_dataset_id_shown_is_the_committed_bundle_s` requires every
   `dataset <hex>` in `README.md` and `docs/demo.md` to prefix the committed
   `bundle_sha256`, and `test_the_published_test_count_is_the_count` discovers
   the suite and compares the count.

   | Branch | dataset id in prose | published test count |
   |---|---|---|
   | `main` | `9d86048ced72` | 802 |
   | #62 | `9d86048ced72` | 807 |
   | #63 | `124f7e4a41ba` | 811 |
   | #65 / #66 | `124f7e4a41ba` | 816 |
   | #69 | `124f7e4a41ba` | 814 |
   | #70 | `124f7e4a41ba` | 817 |
   | #71 | `9d86048ced72` | 851 |

   `README.md` and `docs/demo.md` both conflict in the stack. A resolution that
   keeps `main`'s line while taking the stack's bundle turns `main` red on the
   dataset test, and **no combination of the two sides gives a correct test
   count** — #71 and #70 together are neither 851 nor 817. The count has to be
   recomputed from the merged tree and written by hand. This is the concrete
   version of "two pull requests appending to the same file each merge clean and
   together break the build".

2. **Three files auto-merge silently where both #71 and the stack changed
   them.** Merging #70 into a tree that already has #71 conflicts on 13 files
   and quietly combines three more that neither side ever tested together:
   `cairn/tabular.py`, `tests/test_followup.py`, `tests/test_ui.py`. Git
   produces a result nobody wrote. `cairn/tabular.py` is the one that matters:
   #71 fixes the ambiguity rule there and #69 extracts an `_earliest_comparator`
   helper from the same function for the complexity limit. The auto-merge was
   built and run — it parses, it keeps both changes, and it passes #71's
   `tests/test_tabular.py` inside the stack's tree. So this specific merge is
   sound, but it was sound by luck rather than by anyone checking, and the other
   two files were not verified.

3. **#71 fixes two files the stack leaves unfixed, and the stack still
   describes them as open issues.** `cairn/server.py` gains
   `if not isinstance(parsed, dict):` in #71; the stack tip does not have it.
   `cairn/tabular.py` likewise. Meanwhile #70's `docs/roadmap.md` lists both as
   open issues #67 and #68. `cairn/server.py` conflicts, so a resolver has to
   choose — and choosing the stack's side reverts a fix while leaving prose that
   says the fix was never made, so nothing in the documents would look wrong.
   `cairn/tabular.py` does not even conflict; it merges by itself.

4. **Changelog placement is clean.** Checked and found *not* to be a problem.
   Every stack pull request adds only under `### Unreleased` at line 21, above
   `## 0.3.0 — 2026-08-23`, and the first `##` heading remains `0.3.0` in every
   head, which is what `tests/test_cli.py` requires. The five do all edit the
   same `Unreleased` region, which is why `CHANGELOG.md` conflicts — and because
   they are cumulative snapshots, a resolution that concatenates both sides
   produces five copies of the same entries.

5. **Generated output is current, and was regenerated to prove it.**
   `site/index.html` is committed rather than built at deploy time.
   `python3 site_build.py --check` at #70's head reports `site/index.html is
   current`, so the committed page is what the committed evidence renders to.
   The bundle checksums were independently recomputed from the committed blobs
   for all seven heads and every one matches. No hand-resolved generated file is
   currently disagreeing with its source — but `site/index.html`,
   `plumbline/bundle/checksums.json` and the dataset id in prose are all in the
   conflict set, so this has to be re-checked after any resolution rather than
   assumed.

## Safe order of operations

1. **Merge #71.** ~~It is clean against `main` and green on the exact commit.~~
   **Done** — squashed as `8e0e5e0` while this was being written. It was the
   only pull request whose proposed commit had been tested, and it carries the
   ruleset recording that stops the weekly job from failing. Steps 2 to 7 are
   unaffected; every conflict count below was re-derived against the new `main`
   and is unchanged.

2. **Close #63, #65, #66 and #69 as superseded by #70**, before touching #70,
   so nobody resolves five conflicting copies of one change. Close #62 the same
   way, or merge it first if a small green change is wanted — its two conflicts
   are `README.md` and `WORKLOG.md` only, and its one substantive file is
   already byte-identical in #70. Do not do both.

3. **Rebase #70 onto `main`** (after #71 lands). Do not merge and hand-resolve.
   Most of the 13 conflicts are the duplicated squash-merged commits `b9ff949`,
   `4919b0c` and `9a94a1d`, which a rebase drops outright. While resolving:
   - keep #71's `cairn/server.py` — the `isinstance(parsed, dict)` guard must
     survive;
   - check the auto-merged `cairn/tabular.py`, `tests/test_followup.py` and
     `tests/test_ui.py` rather than trusting the clean merge;
   - reconcile `docs/roadmap.md`, which still calls #67 and #68 open after #71
     closes them.

4. **Regenerate, do not hand-resolve.** After the rebase, and before pushing:
   - `python3 -m cairn index && python3 -m cairn record` to rebuild the
     evidence bundle, then take `plumbline/bundle/checksums.json` from the
     regeneration rather than from either conflict side;
   - `python3 site_build.py` to rewrite `site/index.html`, then confirm with
     `python3 site_build.py --check`;
   - update the `dataset <hex>` string in `README.md` and `docs/demo.md` to the
     new `bundle_sha256` prefix.

5. **Reposition nothing in the changelog, but merge the `Unreleased` entries by
   hand.** Take the union of the entries, not both sides concatenated, and leave
   the first `##` heading as `0.3.0`.

6. **Recompute the published test count last.** It is neither 817 nor 851 after
   the merge. Run the suite, count, and write the number into `README.md`.
   `tests/test_docs.py` will fail until it is right, which is the point.

7. **Re-run CI on the rebased #70 and require it green before merge.** Nothing
   in this pull request has ever been through CI in the form being proposed.

8. **Rework what #70 claims, before or immediately after it lands.** Green CI
   will not catch any of this, because every item is a guard that passes in both
   the fixed and the unfixed state:
   - assert `lexical` and `dense` in the candidate-level test, and add a
     `dense_weight > 0` case so the hybrid split path is exercised at all;
   - assert the candidate pool's contents and its cap;
   - add a fixture where `unmatched` and `ignored` actually differ between
     parts, so the union assertion can distinguish a union from a pick;
   - make `test_nothing_about_when_or_from_where_is_kept` substring-based, or
     delete it — as written it misses `received_at`, `client_ip` and
     `session_id`;
   - compare the **raw written line** against the published example in
     `test_the_published_line_is_the_line_that_is_written`, since key order is
     the defect being fixed and the current re-serialisation normalises it away;
   - correct "fails three tests and names the field" in the commit message,
     `WORKLOG.md` and `docs/roadmap.md` — it fails four, and not that one;
   - correct the premise "every field on `RetrievalTrace` and `Candidate`
     carries a default", which is false for six of them;
   - reconsider flipping `docs/roadmap.md` Phase 5 and Phase 8 to
     **Status: built** until the above is true.

## What was verified here, and what was taken on trust

**Verified directly, by running it:**

- Every merge state, by `git merge-tree --write-tree --messages` of each head
  against `origin/main` at `5221556`, and again against a scratch commit of
  `main` + #71. Conflicting files listed by name.
- The stack relationship: `merge-base --is-ancestor` for every adjacent pair,
  `git patch-id --stable` on the six copies of the `split_intents` commit,
  per-file blob comparison of every earlier head against #70, and file-set
  containment. Blob ids were re-derived with `git ls-tree` after a quoting bug
  made one `git rev-parse` pass return commit objects; the second method agreed
  with the first, and the conclusion is unchanged.
- CI state: `gh pr view --json statusCheckRollup`, `gh run list` per branch, and
  `gh api .../commits/<sha>/check-runs` per head sha. The five "absent"
  classifications rest on `total_count: 0` for those exact commits, confirmed by
  `gh pr checks 70` reporting "no checks reported on the branch". `ci.yml`'s
  trigger block has no path filter, so nothing about the workflow explains it.
- The historical failures: job step counts (11 and 12, not 0) and durations
  (about a minute, not 3 to 5 seconds) rule out budget starvation. The failing
  job in each case is `core, windows`.
- Bundle integrity: `checksums.json` recomputed from committed blobs for all
  seven heads.
- `python3 site_build.py --check` at #70's head.
- The full offline suite at #70's head: 817 tests, OK, 2 skipped, matching the
  README's published count on that branch.
- The `cairn/tabular.py` auto-merge: extracted from the merge result, parsed,
  and run against #71's `tests/test_tabular.py` in the stack's tree. 27 tests,
  OK.
- The ruleset finding: the diff of `.github/rulesets/main.json` in #71, and the
  absence of any `.github/` change in the other six.
- Every mutation result in "Dominant defect class": each was produced by editing
  `cairn/query.py`, `cairn/followup.py` or the dataclasses in
  `cairn/retrieve.py` in a scratch worktree at the relevant head, running the
  full suite, then reverting and re-confirming green. Baselines: 807 tests OK at
  #62's head, 817 tests OK at #70's head, 33 tests OK for the follow-up class.
  `load()` accepting an unknown key was proved with a hand-written store file,
  not by reading the code.
- That `origin/main` is green, so no inherited-failure category applies. Every
  comparison in this file is against `origin/main` at `5221556` after
  `git fetch origin`, never against the local checkout: the working tree is on
  `audit/gates-that-cannot-fail` at `cf03c41`, which is #71's head and **not**
  merged, so reading the local tip as `main` would have made unmerged work look
  landed.

**Taken on trust, or not established:**

- **#71's substantive claims about the three gates and the two defects were not
  independently re-derived.** #71's full check set is green on `cf03c41`, its
  two fixes are visible in the diff, and the `cairn/tabular.py` fix was executed
  here as part of the auto-merge check. But this triage did not mutate each
  fixed subject to prove that every new test in #71 goes red when its subject
  regresses — which is the only thing that would establish the pull request's
  own title. Read #71's three-gates claim as plausible and green, not as
  audited. Anyone relying on it should do the mutation pass.
- **#70's and #62's claims WERE proved by mutation, and both came back
  partly false.** This was the one thing in an earlier draft of this file
  recorded as taken on trust, on the strength of #70's worklog saying the
  author had proved it by adding a `received_at` to `record()` and watching
  "three tests fail and name the field". Measured, it fails four tests and the
  test written to name the field is not one of them. The full mutation results
  are in "Dominant defect class" above; every one of them was produced by
  editing the subject in a scratch worktree, running the suite, reverting, and
  re-confirming green. Taking the author's own proof on trust would have put a
  false statement in this file, which is the whole argument for not doing it.
- **The five "absent" CI results have an observed effect and an unconfirmed
  cause.** No run exists for those commits. Why the `pull_request` event
  produced no run when the branches were updated at about 03:43 — while #62,
  pushed at 03:43:38, did get one — was not established.
- **The full merged tree was never built or tested.** The 13 conflicts were not
  resolved. The `cairn/tabular.py` auto-merge was tested in isolation; the
  `tests/test_followup.py` and `tests/test_ui.py` auto-merges were not. An
  earlier attempt to test the combination by applying three merged files onto
  `main` + #71 produced two failures that were an artifact of the partial
  construction — the stack's tests against #71's sources, missing the stack's
  `fr` language support — and are not evidence of a real defect.
- **Nothing was run against the network.** The `plumbline` merge gate,
  `plumbline-live.sh` and `live_check.py` resolve an external auditor and were
  not executed. Their in-suite guards reported "COULD NOT RUN", correctly, and
  were counted as neither passes nor failures.
