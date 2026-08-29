# Demo corpus — SYNTHETIC content

Everything in this directory is **synthetic demonstration content**. The agency
("Harbor County Community Assistance"), every program, every dollar amount,
income limit, deadline, and phone number is invented for the purpose of
demonstrating Cairn. None of it describes any real benefit program, and none of
it should be relied on for anything.

Every document in this corpus carries `synthetic: true` in its front matter,
and ingestion reports the synthetic count so the label survives into tooling
output, not just this README.

## Languages

English (`en`), Spanish (`es`), Arabic (`ar`, written right to left), and
French (`fr`).

The coverage is deliberately **uneven**, and unevenly uneven. The Harbor
GoPass exists only in English. French exists only for the grocery allowance:
one document, added so the multilingual audit suite has same-language French
evidence to score at all (`docs/I18N.md`), and deliberately not extended to
the other three programs, because a corpus where every language has every
document would stop demonstrating the thing this corpus is for. A real agency's translated material always lags its English material,
and an assistant that pretends otherwise is hiding the gap rather than
handling it. Asking about the GoPass in Spanish or Arabic exercises the
cross-language path — the answer says, in the language you asked in, that the
only source available is in another language, and then quotes that source
exactly as published rather than translating a policy amount.
