"""Did the server say what the committed evidence says it said?

The merge gate grades `plumbline/bundle`, a recording. A recording is bytes on
disk; the thing it is a recording *of* is code that changes. They agreed the
day the bundle was written, and until this file existed nothing checked that
they still do. Every score in every audit report this repository has ever
published describes the recording. Whether it also describes the interface a
person meets was an assumption.

`./plumbline-live.sh` makes the harness ask the same questions over HTTP and
seal what came back. This then checks three things about that recording, and
each one is a different way the claim could be false:

**It came from a socket.** The manifest has to declare a live recording, made
by the HTTP adapter, against the endpoint the live config names. Otherwise
"we graded the running server" is a sentence with nothing behind it — the
file would be indistinguishable from a copy of the offline bundle.

**It was the same questions.** The recording's manifest carries the hash of
the question set it was recorded against; that has to be the committed
bundle's hash. Two answer sets to two different question sets can be compared
only in the sense that any two lists can.

**Every answer matches, byte for byte.** Not "scores similarly": the same
engine, the same corpus, the same question, over a socket instead of a
function call. Anything less than identical is a difference between what is
graded and what is served, and the point of running this at all is to find
out that such a difference exists — not to decide later whether it mattered.

Then a fourth, which the harness structurally cannot do: the accessibility
suite grades an interface snapshot, and a live recording copies that snapshot
across from the question set rather than fetching it. So this fetches the
served page and rebuilds the snapshot from it with the same function
`cairn record` uses. If the audited snapshot is not the page being served,
the accessibility score is about a file.

Exit codes match the rest of this repository's tooling: 0 agreement, 1 a
difference, 4 the check could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from cairn.record import interface_snapshot

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "plumbline" / "live.toml"
DEFAULT_RECORDED = ROOT / "plumbline" / "bundle"

EXIT_OK = 0
EXIT_DIFFERENT = 1
EXIT_CANNOT_RUN = 4

# Long enough that a slow machine is not a failure, short enough that a server
# which never came up is not a hang.
FETCH_TIMEOUT_SECONDS = 10


class CannotRun(Exception):
    """The check could not be made. Never reported as agreement."""


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CannotRun(f"no file at {path}") from exc
    except ValueError as exc:
        raise CannotRun(f"{path}: not readable as JSON ({exc})") from exc


def _read_responses(bundle: Path) -> dict[str, str]:
    path = bundle / "responses.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise CannotRun(f"no responses at {path}") from exc
    out: dict[str, str] = {}
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise CannotRun(f"{path}:{lineno}: {exc}") from exc
        out[row["id"]] = row["response"]
    if not out:
        raise CannotRun(f"{path}: no responses")
    return out


def load_config(path: Path) -> dict:
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise CannotRun(f"no live target config at {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CannotRun(f"{path}: {exc}") from exc


def live_bundle_path(config: dict, config_path: Path) -> Path:
    dataset = (config.get("dataset") or {}).get("path")
    if not dataset:
        raise CannotRun(f"{config_path}: [dataset].path is not set")
    return (config_path.parent / dataset).resolve()


def endpoint_of(config: dict, config_path: Path) -> str:
    endpoint = (config.get("adapter") or {}).get("endpoint")
    if not endpoint:
        raise CannotRun(f"{config_path}: [adapter].endpoint is not set")
    return endpoint


# --- the four checks -------------------------------------------------------


def check_provenance(manifest: dict, endpoint: str) -> list[str]:
    """The recording says, in its own manifest, that it came off the wire."""
    findings = []
    recording = manifest.get("recording")
    if not recording:
        return [
            "the recorded bundle's manifest declares no `recording` block, so "
            "nothing in it says these answers came from a running server. That "
            "is what an offline bundle looks like; this check refuses to call "
            "it a live one."
        ]
    if recording.get("mode") != "live":
        findings.append(
            f"recording.mode is {recording.get('mode')!r}, not 'live'"
        )
    adapter = recording.get("adapter") or {}
    if adapter.get("kind") != "http_json":
        findings.append(
            f"recorded by the {adapter.get('kind')!r} adapter, not over HTTP"
        )
    if adapter.get("endpoint") != endpoint:
        findings.append(
            f"recorded against {adapter.get('endpoint')!r}, but the live "
            f"config names {endpoint!r}"
        )
    return findings


def check_same_questions(manifest: dict, recorded_checksums: dict) -> list[str]:
    asked = ((manifest.get("recording") or {}).get("questions") or {}).get("sha256")
    committed = recorded_checksums.get("bundle_sha256")
    if not asked:
        return ["the recording does not say which question set it was made from"]
    if asked != committed:
        return [
            f"the live run was recorded against question set {asked[:12]}, but "
            f"the committed bundle is {str(committed)[:12]}. Two answer sets to "
            f"two different question sets are not comparable."
        ]
    return []


def compare_responses(recorded: dict[str, str], live: dict[str, str]) -> list[str]:
    findings = []
    missing = sorted(set(recorded) - set(live))
    extra = sorted(set(live) - set(recorded))
    if missing:
        findings.append(f"the server answered nothing for: {', '.join(missing)}")
    if extra:
        findings.append(f"the live run holds items the bundle does not: {', '.join(extra)}")
    for item_id in sorted(set(recorded) & set(live)):
        if recorded[item_id] != live[item_id]:
            findings.append(
                f"{item_id}: the served answer differs from the graded one\n"
                f"    graded: {_excerpt(recorded[item_id])}\n"
                f"    served: {_excerpt(live[item_id])}"
            )
    return findings


def check_interface(endpoint: str, recorded_bundle: Path) -> list[str]:
    """The audited interface snapshot against the page actually served."""
    parts = urlparse(endpoint)
    page_url = f"{parts.scheme}://{parts.netloc}/"
    try:
        with urllib.request.urlopen(page_url, timeout=FETCH_TIMEOUT_SECONDS) as response:
            served = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise CannotRun(f"cannot fetch the served page at {page_url}: {exc}") from exc

    snapshot_path = recorded_bundle / "interface.html"
    try:
        audited = snapshot_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CannotRun(f"no interface snapshot at {snapshot_path}") from exc

    if interface_snapshot(page=served) == audited:
        return []
    return [
        f"the interface snapshot the accessibility suite grades is not the page "
        f"{page_url} serves. Re-record the bundle: until then that suite's score "
        f"is about a file."
    ]


def _excerpt(text: str, width: int = 96) -> str:
    one_line = " / ".join(line for line in text.splitlines() if line.strip())
    return one_line if len(one_line) <= width else one_line[: width - 1] + "…"


# --- driver ----------------------------------------------------------------


def run(config_path: Path, recorded_bundle: Path, *,
        check_page: bool = True) -> tuple[int, list[str]]:
    config = load_config(config_path)
    live_bundle = live_bundle_path(config, config_path)
    endpoint = endpoint_of(config, config_path)

    if not live_bundle.is_dir():
        raise CannotRun(
            f"no live recording at {live_bundle}. ./plumbline-live.sh makes one; "
            f"this compares it, it does not produce it."
        )

    manifest = _read_json(live_bundle / "manifest.json")
    findings: list[str] = []
    findings += check_provenance(manifest, endpoint)
    findings += check_same_questions(manifest, _read_json(recorded_bundle / "checksums.json"))
    findings += compare_responses(
        _read_responses(recorded_bundle), _read_responses(live_bundle)
    )
    if check_page:
        findings += check_interface(endpoint, recorded_bundle)

    lines = []
    recording = manifest.get("recording") or {}
    if findings:
        lines.append(f"LIVE: DIFFERENT — {endpoint}, recorded {recording.get('recorded_at')}")
        lines += [f"  {finding}" for finding in findings]
        lines.append(
            "  Re-record the committed bundle (`python3 -m cairn record`) if the "
            "server is right, and fix the server if it is not. What is not an "
            "option is leaving the gate grading one and users meeting the other."
        )
        lines.append("LIVE: DIFFERENT")
        return EXIT_DIFFERENT, lines

    count = len(_read_responses(recorded_bundle))
    lines.append(f"LIVE: MATCH — {endpoint}, recorded {recording.get('recorded_at')}")
    lines.append(
        f"  {count} answers over HTTP, byte-identical to the recorded evidence "
        f"the gate grades."
    )
    if check_page:
        lines.append("  the audited interface snapshot is the page being served.")
    lines.append("LIVE: MATCH")
    return EXIT_OK, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="live_check.py",
        description=(
            "Compare a recording made from the running server against the "
            "committed evidence the merge gate grades."
        ),
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help=f"live target config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--recorded", default=str(DEFAULT_RECORDED),
                        help=f"the committed bundle (default: {DEFAULT_RECORDED})")
    parser.add_argument("--no-interface", action="store_true",
                        help="skip fetching the served page; for comparing a "
                             "recording after the server has been stopped")
    parser.add_argument("--summary-file", default=None,
                        help="append the result to this file as well (CI job summary)")
    args = parser.parse_args(argv)

    try:
        code, lines = run(Path(args.config), Path(args.recorded),
                          check_page=not args.no_interface)
    except CannotRun as exc:
        print(f"LIVE: COULD NOT RUN — {exc}", file=sys.stderr)
        print("LIVE: a check that could not run is not a check that passed.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN

    report = "\n".join(lines)
    print(report)
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write(f"\n### Live target\n\n```\n{report}\n```\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
