# A real refusal-to-human handoff

`cairn serve` has always pointed a refusal at a static contact string —
`refusal.contact`/`refusal.contact_by_language` in `cairn.toml`, printed
straight into the refusal text. That is still the default, and it still
works with no configuration beyond a real phone number or address. It asks
the asker to do all the remaining work themselves: read the number, decide
to call, explain their question from scratch to whoever picks up.

`--followup-store` is the opt-in upgrade past that: a "Request a follow-up"
action on a refusal, only, that captures the asker's own contact
information — and, if they separately choose to, the question they asked —
so staff can actually reach back out.

## Turning it on

```console
$ cairn serve --followup-store followups.jsonl
```

A refusal now carries a closed disclosure, "Request a follow-up", with a
short form: a contact field (email or phone, free text, required) and a
checkbox, unchecked by default, to include the question that was asked. A
grounded answer never shows this — it already names sources the asker can
act on themselves, and the whole point of the form is a channel for when
nothing answered.

Submitting the form is the only thing that reaches this feature at all:
nothing here fires automatically, on a timer, or on a pattern of refusals.
One person filling in the form and clicking "Request follow-up" is one
entry in the store; nothing else about their session, their other
questions, or anyone else's questions is touched.

## What gets stored, and what doesn't

Every submission writes one line to the file named after `--followup-store`:

```json
{"lang": "en", "contact": "someone@example.gov", "question": null}
```

`question` is `null` unless the asker checked "Include the question I
asked" **on that specific submission** — never by default, never inferred,
never carried over from a different session. Checking the box:

```json
{"lang": "en", "contact": "someone@example.gov", "question": "why was my application denied"}
```

There is no third state. A submission either names the question or it does
not; there is no way to submit "some of the question" or to opt in after
the fact — the checkbox is checked at the moment of submission or it is
not, and the store only ever reflects that one moment.

## Reading the queue

```console
$ cairn followups followups.jsonl
2 follow-up request(s), oldest first:

[1] en  someone@example.gov
      question: (not shared)
[2] en  someone@example.gov
      question: why was my application denied

Once a request is handled, remove its line from the store file — this is a
queue, not a permanent log: rerunning `cairn followups` always shows what
is still outstanding.
```

The store is a plain JSONL file — an operator can also read it directly,
pipe it into a ticketing system, or write a small script against it.
There is no "handled" flag Cairn tracks for you: once staff have followed
up on a request, remove its line (by hand, or with a script) so the next
`cairn followups` run shows only what is still open. This is the same
"simplest correct thing" the rest of Cairn's operator tooling favors —
a file staff can read, edit, and trust, rather than a database with its
own state machine to keep in sync.

## What this is not

- **Not automatic outreach.** Nothing in Cairn ever contacts anyone. The
  store is a queue for staff to work from; every follow-up call, email, or
  letter is a human decision and a human action, outside this project
  entirely.
- **Not a replacement for `refusal.contact`.** The static contact string
  still appears in every refusal's text regardless of whether
  `--followup-store` is set — an asker who would rather call a number
  themselves right now still can. The form is an additional channel, not
  a replacement one.
- **Not encrypted, not access-controlled by this feature.** The store file
  holds real contact information — treat it like any other file with
  personal data: file permissions, backup policy, and retention are an
  operator's responsibility, the same as for any other file `cairn serve`
  is told to write. Pair `--followup-store` with the deployment guidance in
  `docs/deployment.md` if this server is reachable beyond one machine.
- **Not aggregate-only, unlike `--refusal-stats`.** `docs/refusal-analytics.md`
  covers a strictly aggregate, PII-free counter for finding corpus gaps.
  This feature is the opposite kind of thing on purpose — it exists
  specifically to capture a real person's contact information, because a
  handoff has to name someone to hand off to. Turn on `--refusal-stats`
  for the "what's missing in the corpus" question and `--followup-store`
  for "let this specific person be reached" — they answer different
  questions and neither substitutes for the other.
