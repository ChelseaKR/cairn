# Authoring a corpus: the FAQ-pair convention

This is guidance for whoever writes or edits the markdown documents Cairn
answers from — not a code feature, and not enforced by anything. It is a
convention `cairn lint` (see `cairn/lint.py`) can eventually check for, but
today it is only written down, because the reasoning behind it matters more
than the checklist.

## The problem it addresses

DESIGN.md documents a real, closed-out failure ("The colloquial-recall
failure, worked as a ranking problem and closed"): the question "who can get
the discount bus pass" refuses, correctly, because the passage that answers
it — the eligibility paragraph — shares exactly one word with the question:
"who", the weakest word in it. It does not contain "discount", "bus" (the
corpus says "buses"), "get", or "pass". Twenty-one ranking configurations
were built and measured against the whole probe set trying to fix this by
reweighting scores, and every one was reverted, because the diagnosis was
wrong: this is not a ranking problem. **The corpus does not say this in the
words the question uses.** No amount of reweighting how existing words are
scored can rank a word that is not there.

Cairn's own conclusion, stated plainly in DESIGN.md, names three ways to
close a gap like this and rejects two of them outright:

1. *Match words that are not there* — embeddings or translation. Refused:
   it ends offline determinism or emits unsourced text.
2. *Classify the question's intent* — guess that a "who can…" question wants
   an eligibility section. Refused: it needs per-language interrogative
   lists and a per-language notion of what an eligibility heading looks
   like, which is exactly the dictionary dependency the tokenizer exists to
   avoid.
3. **Put the missing words in the passage.**

The third is real information an agency has and a reader does not: an
agency knows what its own program is called informally, what questions
people actually ask about it, and in what words. The question is how to add
that without repeating the mistake the corpus already made once.

## Why not aliases (the mistake, already made and reverted)

The obvious version of option 3 is a `aliases:` front-matter field — "this
document is also known as: discount bus pass, reduced fare card" — scored
into every passage of the document like the title. It was built, measured at
five weights on the demo corpus, and reverted. The reason is the one worth
carrying forward: **an alias lifts every passage of its document by the same
amount.** For the transit document, the four candidate passages' scores
moved from a spread of 0.02 to a spread of 0.02–0.04 clustered around
0.33–0.36 — close enough to arbitrary that which passage got quoted stopped
being a ranking and became close to a coin toss. The measured result was
*more* answers and *more of them from the wrong paragraph* — a visible
refusal turned into an invisible wrong answer, which is the one trade this
project exists to refuse.

The mechanism is document-level: the lift does not distinguish *which*
passage of the document the missing words actually belong to.

## The convention: write the question into the passage that answers it

Where a passage exists specifically to answer a predictable, plainly-phrased
question, write that question as the passage's own text — a real sentence a
person would ask, not a keyword list:

```markdown
**Who can get the discount bus pass?**

Harbor County residents age 65 or older, or with a qualifying disability,
can apply for the discount transit pass at any county service center.
```

This is **not** an alias, and the difference is the one DESIGN.md's
measurement turned on:

- It is **passage-level**, not document-level. It adds lexical signal to the
  one passage it genuinely answers, and to no other passage of the
  document — so it cannot compress the document's passages toward each
  other the way a document-wide alias did.
- It is **real content**, not metadata scored in and never shown. It is
  quoted back in an answer like any other sentence, because it is one — a
  reader sees exactly the words that made the passage retrievable, phrased
  the way they might have asked it.
- It is **authored per-passage by someone who has read the corpus**, the
  same authority DESIGN.md already trusts for `answering_sources` in
  `plumbline/questions.toml` — a machine cannot decide which paragraph a
  colloquial question is "really" asking about; a person who wrote or knows
  the document can.

## What this does not fix

Writing a question into a passage only helps a question phrased closely
enough to what was written — it is still lexical matching underneath,
governed by the same tokenizer and threshold as everything else. It will
not rescue a question that shares no vocabulary at all with the written
form, and it is not a substitute for `cairn lint`'s reachability check
(`cairn/lint.py`) or the term-evidence columns `ask --explain` already
prints, which tell you *which* words a passage is missing rather than
inviting you to guess.

## What to avoid

The failure mode aliases were rejected for can come back wearing this
convention's clothes: a written "question" that is really a keyword bag —
"discount bus pass reduced fare transit assistance card" — is a
document-level alias with extra steps, not a passage-level one, and it
degrades the same way. The test is whether a plain reader would recognize
the added sentence as a real question a real person would ask, in their own
words. If it reads like a list of search terms, it is doing the thing this
convention exists to avoid.

## Plain-language readability

A passage is quoted verbatim, so the reading level of an answer is the reading
level of the passage. `cairn lint --readability` measures it:

```console
$ python3 -m cairn lint --readability
```

Per passage it prints a grade level and the mean sentence length; per language
it prints how many passages were graded, by which formula, and the mean and
highest grade. Two formulas are built in, both named and both computed here
rather than asserted:

- **English**: Flesch-Kincaid grade level (Kincaid, Fishburne, Rogers and
  Chissom, 1975).
- **Spanish**: Crawford grade level (Crawford, 1985).

Every other language reports `n/a (no formula in force for <lang>)`. That is
deliberate and it is the same rule the rest of this project follows: a formula
fitted on English text produces, over Arabic, a number with the right shape and
no referent. An unsupported language is reported, never silently scored. An
operator who judges a formula close enough for their language says so in
`[lint.readability]`, and the grade is then labelled with the formula it came
from; naming a formula this build cannot compute is refused when the
configuration is built, not discovered later as a language that reports `n/a`
forever.

Set `[lint] max_grade` to be warned about passages above a target level. It is
a warning and never an error: `lint` still exits 0, `index` is untouched, and a
passage with no formula in force earns no warning whatever the ceiling is,
because "not measured" is not "measured and over".

The same measurement appears in explain mode, beside the score that chose the
passage:

```console
$ python3 -m cairn ask "How much is the monthly grocery allowance for one person?" --explain
   1  0.518  ACCEPT  grocery-allowance-en#2  [en] Fresh Start Grocery Allowance
          ## How much you get A one-person household receives $212 per month...
          matched 8/8: allow, for, groce, how, month, much, one, perso
          readability grade 8.2 (flesch_kincaid_grade); 26 word(s), 3 sentence(s), mean sentence length 8.7
```

`lint` answers "is this corpus readable"; the explain line answers "was the
passage this answer quoted readable", which is the question an operator
diagnosing a specific bad answer actually has. It measures the passage, not
the truncated excerpt printed above it, so the number does not move when the
excerpt width does. `--json` carries the same figures per candidate under
`readability`, where an absent grade is `null` and never `0`: zero is a
reading level a passage could plausibly have, so publishing it for one that
was never measured would be exactly the confusion this whole section avoids.
An operator override in `[lint.readability]` applies here too, and the
formula that produced the number is named alongside it.

What the number is worth, stated so it is not over-read:

- Syllable counting is a deterministic, dictionary-free heuristic. Spanish is
  counted by vowel groups, which suits a nearly phonemic orthography and is
  wrong at hiatus (`río` counts as one syllable). English uses vowel groups
  with a silent-final-`e` rule, which is wrong on a long tail of words.
- A grade is a fact about the source text, not a judgement of the answer. The
  fix for a passage that reads at grade 14 is a plain-language page from the
  agency that publishes it, which is the same kind of fix DESIGN.md prescribes
  for `ck-015`. It is not an edit to the corpus copy, which must keep matching
  its source.

## Where this could become tooling later

`cairn lint` already flags a passage with no scoring terms at all
(`cairn/lint.py`) and a passage no single term of which would clear the
retrieval threshold alone. A future, more speculative check in the same
spirit — flagging a passage whose *title* shares nothing with any of its
own sentences, as a hint that the passage may be answering a question its
own words never ask — was considered while writing this guidance and left
undone: it would need measurement against the probe set the same way every
ranking-adjacent idea in this project does, and a heuristic that fires on
prose which merely does not restate its own topic sentence is a plausible
way to generate false positives on perfectly good corpus content. Recorded
here rather than built speculatively.
