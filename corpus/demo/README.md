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

English (`en`), Spanish (`es`), and Arabic (`ar`, written right to left).

The coverage is deliberately **uneven**: the Harbor GoPass exists only in
English. A real agency's translated material always lags its English material,
and an assistant that pretends otherwise is hiding the gap rather than
handling it. Asking about the GoPass in Spanish or Arabic exercises the
cross-language path — the answer says, in the language you asked in, that the
only source available is in another language, and then quotes that source
exactly as published rather than translating a policy amount.
