"""Files `cairn init` writes into a new deployment.

Not importable content: this package exists so the templates ship inside the
wheel. A deployment scaffolded from PyPI has the package and no repository to
copy anything out of, and the audit interlock is the part of this project that
is not a demo.

The two gate scripts here are copies of the ones at this repository's root.
`tests/test_scaffold.py` holds them byte-equal, so the copy cannot drift into
being a second, older gate.
"""
