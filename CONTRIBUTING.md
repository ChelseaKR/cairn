# Contributing to Cairn

Cairn is a reference implementation of one behaviour: answer only from the
corpus you were given, quote it rather than paraphrase it, and refuse plainly
when nothing clears the threshold. A change that makes the code nicer but the
behaviour less checkable is not an improvement here.

## The two gates, and which one is which

**`make verify` is the local gate.** It is offline, it needs no auditor, and it
is what you run before opening a pull request:

```sh
make install   # uv sync --locked --extra dev
make verify    # lockfile check, lint, types, tests under coverage
```

**`./plumbline-gate.sh` is the merge gate.** It resolves an external auditor
pinned to an exact commit and grades the committed evidence bundle against
floors this repository does not get to move on its own. It is a separate job
for a reason, spelled out in the header of `.github/workflows/ci.yml`: the
local gate must be runnable with nothing but a checkout, and the merge gate
must fail rather than skip when it cannot reach the harness.

`make verify` passing does not mean the merge gate will pass. If your change
alters what the engine answers, the recorded evidence has to be re-recorded
(`python3 -m cairn index && python3 -m cairn record`) and the diff reviewed
like any other.

## The demo path must keep working with no install at all

```sh
python3 -m cairn index
python3 -m cairn ask "How much is the monthly grocery allowance for one person?"
```

That is the first thing the README claims, and `make demo` runs it. The
runtime has no third-party dependencies and is not going to acquire any: the
whole point is that someone can clone this and see it work, offline, without a
virtual environment. A change that adds a runtime dependency needs an argument
strong enough to give that up, made in an ADR.

## Documentation is tested, so treat it as code

`tests/test_docs.py` executes every `console` block in `docs/demo.md` and holds
its output byte for byte, and executes the README's blocks under a looser rule
that still forbids showing a word the command never printed. If you change what
a command prints, the pages change in the same commit.

## Types and complexity, honestly

`mypy` runs in its default mode, not `--strict`, because strict reports 28
findings on this tree today. The complexity limit is configured at 10 and the
`C90` rule is deliberately not switched on, because four functions are over it.
Both gaps are written in the README's conformance table rather than hidden.
Closing either is welcome; silencing either with a blanket ignore is not.

## Decisions get recorded

Anything that changes an argument made in `DESIGN.md` gets an ADR in
`docs/adr/`, numbered and dated. Accepted records are superseded, never
rewritten. See [ADR 0000](docs/adr/0000-record-architecture-decisions.md).

## Reporting a security problem

Not here. See [SECURITY.md](SECURITY.md) for the private channel.
