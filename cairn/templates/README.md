# {{NAME}}

A Cairn deployment, scaffolded by `cairn init` on {{VERSION}}.

Cairn answers questions only from the documents in `{{CORPUS_PATH}}`, quotes
them verbatim with a citation, and refuses when it has no source. What makes
that a claim rather than a hope is the audit interlock scaffolded beside it:
two independent harnesses, each pinned to an exact commit, grading a recorded
evidence bundle produced by the engine itself.

**Nothing in this directory is finished.** Every step below is left to a
person, and each is here because no tool can do it for you.

## Before this deployment answers anyone

1. **Write the refusal contact.** `[refusal] contact` in `cairn.toml` is
   blank. `cairn serve` refuses to start until it is set, because a refusal
   that points nowhere is a dead end for the person least able to absorb one.

2. **Review the drafted question set.** `questions.toml` was drafted from your
   corpus: one item per document per language, with `answering_sources` left
   blank and `behavior = "answer"`. `cairn record` refuses it exactly as it
   stands, and that refusal is the design. Only a person who has read the
   question and the document can say which passage answers it, and a question
   set nobody has done that for is a check that is not running.

   Write a real question, a real expected answer and the passage id that
   answers it, and delete the `review = "draft"` marker as you go. Delete the
   items you are not going to write.

3. **Copy `audit_guard.py`** from the Cairn repository at the release this
   directory was scaffolded from ({{VERSION}}). It is deliberately not written
   here: it is the gate logic itself rather than configuration, it belongs
   with the project that maintains it, and a copy scaffolded silently into
   your tree is a copy nobody will update.

4. **Set the floors you disagree with, and say why.** `plumbline/target.toml`
   declares every suite and sets no floor, so each takes the pinned harness's
   own default. Cairn's own target file departs from six of them, and every
   departure carries a `floor_reason`, because a floor moved without a reason
   is indistinguishable from a floor moved to make a red gate green.

5. **Record and grade, then commit the baseline.** `plumbline/baseline.json`
   is a placeholder that fails on purpose. Run the gate, read the run, and
   replace it with a run you are willing to be held to:

   ```console
   $ cairn index
   $ cairn record
   $ ./plumbline-gate.sh
   $ ./gauntlet-gate.sh
   ```

   A floor is a minimum. Without a baseline a score can decay from 0.99 to
   0.36 and stay green the whole way down.

6. **Turn the workflow on.** `.github/workflows/audit.yml` runs both gates on
   every push. It needs network access the first time to fetch the pinned
   harnesses, and it is written to fail closed: a gate that could not run is
   not a gate that passed.

## What this directory does not contain

Your corpus, your questions, your reference answers, your contact, and the
judgement about what score is good enough for the people you serve. Those are
the parts that decide whether this deployment is honest, and none of them can
be scaffolded.
