# cairn-demo

**Synthetic evidence, recorded from a running system.** The questions were
written by hand; every response was produced by `cairn record` calling the
engine, and every source passage is from the bundled synthetic demo corpus —
an invented county, invented programs, invented amounts. It demonstrates that
the instrument and the target work together. It measures nothing about any
real benefit program.

- 30 items (5 ar, 15 en, 9 es, 1 fr).
- 23 expected answers, 7 expected refusals, 6 of
  them adversarial probes.
- 15 items are not in English. 13 of them are
  translations of an English item and carry `"review": "unreviewed"`, which
  every run says out loud; the remaining 2 were
  authored directly in their own language. No non-English string in this
  bundle — translated or authored — has been reviewed by a subject-matter
  expert, and claiming otherwise in an audit record would be the exact
  dishonesty that field exists to prevent.

## How to regenerate

```sh
python3 -m cairn index
python3 -m cairn record
```

Re-recording an unchanged corpus and configuration produces byte-identical
files. A diff here is a change in behavior, and the bundle hash moving is the
trace that says so.

## What is in it

| File | What it is |
| --- | --- |
| `items.jsonl` | The authored questions — including which passage answers |
| | each one — plus every passage retrieval accepted for it |
| `responses.jsonl` | What the engine replied, with the sources it cited |
| | marked inline |
| `sources.jsonl` | Every passage in the corpus, so a citation to something |
| | that does not exist is detectable |
| `interface.html` | A snapshot of the served page, with its colour pairs |
| | declared so they can be checked rather than believed |
| `checksums.json` | SHA-256 per file, and for the bundle |

Source ids here are Cairn passage ids with the `#` before the ordinal written
as a `.`, because the bundle format's inline citation grammar has no `#` in
it. `grocery-allowance-en.2` is `grocery-allowance-en#2`; nothing else about
the identifier changes, so an audit finding maps straight back to a passage.
