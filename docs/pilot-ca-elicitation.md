# Question elicitation for the real-corpus pilot

The pilot (`docs/pilot-ca.md`) needs questions nobody wrote for Cairn, in
the words a person would actually use. This is the script for collecting
them. It is deliberately short: twenty minutes per person, no instructions
about how to phrase anything, and the person never sees a page from the
corpus — the moment they do, their vocabulary becomes the page's.

## Who to ask

Eight to twelve people. Not domain experts, not people who work in benefits
administration, not people who have read this repository. A mix of
Californians (so county questions can be labelled) and non-Californians
(so the federal-only set has real phrasings too). Ask each where they live,
to the county.

## What to send

Send this, and nothing else — no link to any agency site, no example
questions, no program names beyond the ones below.

---

> I'm collecting questions for a research project on how well a government
> help tool answers real people's questions. I'm not testing you — there
> are no wrong questions, and the less polished the better.
>
> For each of the topics below, write **three questions** you or someone
> you know might actually ask. Write them the way you'd type them into a
> search box or ask a friend, not the way a form would word them. If you
> don't know the official name of something, that's fine — use whatever
> you'd call it.
>
> 1. Help paying for food
> 2. Health coverage if you're low-income, or Medicare if you're over 65
> 3. Cash help for families, or unemployment / disability pay
> 4. Taxes — filing, refunds, credits
> 5. Driver's license, ID, car registration
> 6. Immigration — green cards, citizenship, fees
> 7. Help with rent, utilities, or phone/internet bills
> 8. Voting, court fees, or getting official records
>
> Two more, about anything at all a government office might help with.
>
> Which county do you live in? (State is fine if not California.)

---

That is 26 questions per person; ten people is 260, which after removing
duplicates and out-of-scope items lands near the ~150 the pilot needs.

## What to do with the answers

1. Record each question **verbatim**. Do not fix spelling, punctuation, or
   program names. "Do I qualify for foodstamps" is the data.
2. Tag each with `source = "elicited"` and the person's county (or state).
3. Label it — `behavior`, `answering_sources`, `expected`, `jurisdiction`,
   `location_dependent` — by reading the corpus, **before** any corpus is
   asked anything. See `docs/pilot-ca.md`, "The question set".
4. A question the corpus cannot answer is a `refuse` item, not a discarded
   one. "Can I get food stamps if I'm undocumented" is a real question
   whether or not a page answers it, and the pilot measures refusals too.
5. Duplicates across people are kept once, with a note of how many people
   asked it — a question five people asked is worth more than one.

## What not to do

- Do not paraphrase. A paraphrased question is a question you wrote.
- Do not show anyone the corpus, the demo, or an agency page first.
- Do not prompt with "CalFresh", "SNAP", "Medi-Cal" or any official name.
  Topic 1 says "help paying for food" on purpose.
- Do not collect anything but the questions and the county. No names in
  the committed question set; the person is `p-07`, and the mapping from
  `p-07` to a person stays with whoever collected it.
