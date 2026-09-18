"""Google Analytics 4 on the published site, and the guards around it.

Owner decision 2026-09-17: GA4 on every public site, with the privacy copy
changed to match. `site_build.py` owns the loader (see `GA4_MEASUREMENT_ID`
there); this file holds it to three things:

* **The build.** No ID means no analytics anywhere on either page: no script,
  no reference to Google, no opt-out control, and copy that says so. A
  malformed ID fails the build. With the committed ID, both committed pages
  carry exactly one loader, the footer control and a link to the privacy page.

* **The loader, executed.** The script is lifted out of the committed page and
  run in Node against a stubbed `window`/`navigator`/`document`. Off the
  production host or outside this project's path, under Global Privacy
  Control, under any of the three Do Not Track spellings, or after the footer
  opt-out, it creates no `dataLayer` and requests nothing. Otherwise it sets
  both Consent Mode defaults before `config`, turns Google signals and ad
  personalization off, and loads gtag.js once.

* **Negative controls.** Each guard is deleted from the script in turn. Every
  control first asserts that the deletion landed (the guard occurred exactly
  once before and not at all after), then asserts that GA now loads in the
  case the guard exists for. A control whose sabotage silently no-ops would
  otherwise read as a pass.

Node is on every GitHub-hosted runner. Locally the executed tests skip when
it is missing; under CI they fail instead, so a runner without Node cannot
turn them into a green skip.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import site_build

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "site" / "index.html"
PRIVACY = ROOT / "site" / "privacy.html"
PAGES = (INDEX, PRIVACY)

ID = "G-BJR1YH7N91"
KEY = "cairn:analytics-opt-out"
GTAG_SRC = f"https://www.googletagmanager.com/gtag/js?id={ID}"
DENIED_REGIONS = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    "IS", "LI", "NO", "GB", "CH",
]  # fmt: skip

PRODUCTION = {"hostname": "chelseakr.github.io", "pathname": "/cairn/"}

# The guards, exactly as the committed script spells them. The negative
# controls delete each one; the occurrence count is how they prove it landed.
GUARDS = {
    "host": 'if (w.location.hostname !== "chelseakr.github.io") return;',
    "path": 'if (w.location.pathname.indexOf("/cairn/") !== 0) return;',
    "gpc": "if (n.globalPrivacyControl === true) return;",
    "dnt": 'if (dnt === "1" || dnt === "yes") return;',
    "opt-out": "if (optedOut()) return;",
}

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const sc of input.scenarios) {
  const appended = [];
  const listeners = {};
  const store = Object.assign({}, sc.storage || {});
  const status = { textContent: "" };
  const button = {
    hidden: false, textContent: "Opt out of analytics", handlers: {},
    addEventListener(type, fn) { this.handlers[type] = fn; },
  };
  const box = {
    hidden: true,
    querySelector(sel) {
      return sel === "button" ? button : sel === "[role=status]" ? status : null;
    },
  };
  const document = {
    head: { appendChild(el) { appended.push(el); } },
    createElement(tag) { return { tag: tag }; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    querySelector(sel) { return sel === "[data-analytics-choice]" ? box : null; },
  };
  const window = {
    location: {
      hostname: sc.hostname, pathname: sc.pathname, protocol: sc.protocol || "https:",
    },
    doNotTrack: sc.windowDnt,
  };
  if (sc.storageThrows) {
    Object.defineProperty(window, "localStorage", {
      get() { throw new Error("SecurityError"); },
    });
  } else {
    window.localStorage = {
      getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
      setItem(k, v) { store[k] = String(v); },
      removeItem(k) { delete store[k]; },
    };
  }
  const navigator = {
    globalPrivacyControl: sc.gpc, doNotTrack: sc.dnt, msDoNotTrack: sc.msDnt,
  };
  const ctx = vm.createContext({
    window: window, navigator: navigator, document: document, Date: Date,
  });
  vm.runInContext(input.script, ctx);
  (listeners.DOMContentLoaded || []).forEach((fn) => fn());
  const control = [{
    label: button.textContent, hidden: button.hidden, boxHidden: box.hidden,
    status: status.textContent,
  }];
  for (let i = 0; i < (sc.clicks || 0); i++) {
    button.handlers.click();
    control.push({
      label: button.textContent, hidden: button.hidden, status: status.textContent,
      flag: Object.prototype.hasOwnProperty.call(store, input.key) ? store[input.key] : null,
      disabled: window["ga-disable-" + input.id],
    });
  }
  out[sc.name] = {
    dataLayer: window.dataLayer === undefined ? null
      : window.dataLayer.map(
        (args) => Array.from(args).map((a) => (a instanceof Date ? "<date>" : a)),
      ),
    scripts: appended.map((el) => ({ tag: el.tag, src: el.src, async: el.async })),
    control: control,
  };
}
process.stdout.write(JSON.stringify(out));
"""


def loader(page: Path) -> str:
    """The inline script in a committed page's <head>, exactly as published."""
    head = page.read_text(encoding="utf-8").split("</head>", 1)[0]
    scripts = re.findall(r"<script>(.*?)</script>", head, re.S)
    if len(scripts) != 1:
        raise AssertionError(f"{page.name}: expected one inline script, found {len(scripts)}")
    return scripts[0]


def node() -> str | None:
    found = shutil.which("node")
    if found is None and os.environ.get("CI"):
        raise AssertionError("Node is required in CI to execute the GA4 loader")
    return found


def run(script: str, scenarios: list[dict]) -> dict[str, dict]:
    binary = node()
    if binary is None:
        raise unittest.SkipTest("node is not installed; CI runs these")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        payload = json.dumps({"script": script, "scenarios": scenarios, "key": KEY, "id": ID})
        done = subprocess.run(
            [binary, str(harness)], input=payload, capture_output=True, text=True,
            timeout=60, check=False,
        )
    if done.returncode != 0:
        raise AssertionError(f"node harness failed: {done.stderr}")
    result: dict[str, dict] = json.loads(done.stdout)
    return result


def scenario(name: str, **overrides: object) -> dict:
    return {"name": name, **PRODUCTION, **overrides}


class TestTheBuild(unittest.TestCase):
    def test_no_id_means_no_analytics_on_either_page(self):
        for render in (site_build.render, site_build.render_privacy):
            for empty in ("", "   ", None):
                with self.subTest(page=render.__name__, id=empty):
                    page = render(empty)
                    self.assertNotIn("<script", page)
                    self.assertNotIn("google", page.lower().replace("google analytics", ""))
                    self.assertNotIn("googletagmanager", page)
                    self.assertNotIn("Opt out of analytics", page)
                    self.assertNotIn("data-analytics-choice", page)
                    self.assertIn("This site runs no analytics", page)

    def test_the_no_id_build_is_otherwise_the_same_page(self):
        # Removing the ID removes the loader and swaps the footer line, and
        # changes nothing else: the evidence is not conditional on analytics.
        with_id = site_build.render(ID)
        without = site_build.render("")
        self.assertEqual(
            without.split("<footer>", 1)[0],
            with_id.split("<footer>", 1)[0].replace(site_build.ga4_snippet(ID), ""),
        )

    def test_a_malformed_id_fails_the_build(self):
        for bad in ("UA-12345-1", "G-abc123", 'G-ABC"};alert(1);//', "G-", "BJR1YH7N91"):
            with self.subTest(id=bad), self.assertRaises(ValueError):
                site_build.render(bad)

    def test_the_committed_pages_are_the_rendered_pages(self):
        for out, page in site_build.pages().items():
            with self.subTest(page=out.name):
                self.assertEqual(out.read_text(encoding="utf-8"), page)

    def test_each_committed_page_carries_one_loader_with_the_committed_id(self):
        self.assertEqual(site_build.GA4_MEASUREMENT_ID, ID)
        for page in PAGES:
            with self.subTest(page=page.name):
                source = page.read_text(encoding="utf-8")
                head, body = source.split("</head>", 1)
                self.assertEqual(source.count("<script"), 1)
                self.assertNotIn("<script", body)
                self.assertNotIn("src=", loader(page).replace("s.src =", ""))
                script = loader(page)
                self.assertIn(json.dumps(ID), script)
                self.assertIn(json.dumps(GTAG_SRC), script)
                self.assertIn(json.dumps(KEY), script)
                for guard in GUARDS.values():
                    self.assertEqual(script.count(guard), 1, guard)

    def test_each_committed_page_links_the_privacy_page_and_the_opt_out(self):
        for page in PAGES:
            with self.subTest(page=page.name):
                footer = page.read_text(encoding="utf-8").split("<footer>", 1)[1]
                self.assertIn('<a href="privacy.html">Privacy</a>', footer)
                self.assertIn("Google Analytics 4", footer)
                self.assertIn(
                    '<span data-analytics-choice hidden><button type="button" '
                    'class="link-button">Opt out of analytics</button> '
                    '<span role="status"></span></span>',
                    footer,
                )

    def test_the_privacy_page_makes_no_root_relative_reference(self):
        # Same reason as the evidence page: /x resolves against the shared
        # origin, not /cairn/.
        source = PRIVACY.read_text(encoding="utf-8")
        rooted = re.findall(r'(?:href|src|content)="(/(?!/)[^"]*)"', source)
        self.assertEqual(rooted, [])
        self.assertIn(
            '<link rel="canonical" href="https://chelseakr.github.io/cairn/privacy.html">',
            source,
        )

    def test_the_privacy_page_describes_what_ships(self):
        text = PRIVACY.read_text(encoding="utf-8")
        for claim in (
            "Google Analytics 4",
            "Google LLC",
            "<code>_ga</code>",
            "European Economic Area, the United Kingdom and Switzerland",
            "cookieless ping",
            "Google signals and ad personalization are both turned off",
            "14 months",
            "Global Privacy Control",
            "Do Not Track",
            "&ldquo;Opt out of analytics&rdquo;",
            "&ldquo;Opt back in&rdquo;",
            f"<code>{KEY}</code>",
            "https://tools.google.com/dlpage/gaoptout",
        ):
            with self.subTest(claim=claim):
                self.assertIn(claim, text)
        self.assertNotIn("runs no analytics", text)
        self.assertEqual(site_build.GA4_DATA_RETENTION, "14 months")

    def test_the_opt_out_key_names_this_project(self):
        # Every chelseakr.github.io project shares one localStorage. A key
        # that does not name this one would opt a visitor out of all of them.
        self.assertEqual(site_build.GA4_OPT_OUT_KEY, KEY)
        self.assertTrue(KEY.startswith("cairn:"), KEY)


def loads_ga(result: dict) -> bool:
    return result["dataLayer"] is not None or bool(result["scripts"])


class TestTheLoaderExecuted(unittest.TestCase):
    def test_on_the_production_page_it_loads_with_the_right_config(self):
        for page in PAGES:
            with self.subTest(page=page.name):
                result = run(loader(page), [scenario("live")])["live"]
                self.assertEqual(
                    result["scripts"], [{"tag": "script", "src": GTAG_SRC, "async": True}]
                )
                self.assertEqual(
                    result["dataLayer"],
                    [
                        [
                            "consent", "default",
                            {
                                "ad_storage": "denied", "ad_user_data": "denied",
                                "ad_personalization": "denied",
                                "analytics_storage": "denied", "region": DENIED_REGIONS,
                            },
                        ],
                        [
                            "consent", "default",
                            {
                                "ad_storage": "denied", "ad_user_data": "denied",
                                "ad_personalization": "denied",
                                "analytics_storage": "granted",
                            },
                        ],
                        ["js", "<date>"],
                        [
                            "config", ID,
                            {
                                "allow_google_signals": False,
                                "allow_ad_personalization_signals": False,
                            },
                        ],
                    ],
                )
                self.assertEqual(len(DENIED_REGIONS), 32)

    def test_off_the_production_host_or_path_it_loads_nothing(self):
        cases = [
            scenario("localhost", hostname="localhost", protocol="http:"),
            scenario("loopback", hostname="127.0.0.1", protocol="http:"),
            scenario("file", hostname="", pathname="/tmp/site/index.html", protocol="file:"),
            scenario("other-host", hostname="example.com"),
            scenario("sibling-project", pathname="/chalkline/"),
            scenario("origin-root", pathname="/"),
            scenario("prefix-lookalike", pathname="/cairn-fork/"),
        ]
        results = run(loader(INDEX), cases)
        self.assertEqual(set(results), {c["name"] for c in cases})
        for name, result in results.items():
            with self.subTest(case=name):
                self.assertFalse(loads_ga(result), result)

    def test_a_privacy_signal_or_the_opt_out_loads_nothing(self):
        cases = [
            scenario("gpc", gpc=True),
            scenario("dnt-navigator", dnt="1"),
            scenario("dnt-yes", dnt="yes"),
            scenario("dnt-window", windowDnt="1"),
            scenario("dnt-ms", msDnt="1"),
            scenario("opted-out", storage={KEY: "1"}),
        ]
        results = run(loader(INDEX), cases)
        self.assertEqual(set(results), {c["name"] for c in cases})
        for name, result in results.items():
            with self.subTest(case=name):
                self.assertFalse(loads_ga(result), result)

    def test_an_unrelated_or_false_signal_still_loads(self):
        # The guards are exact: GPC false, DNT "0", or another site's opt-out
        # key under the same origin do not switch this site's analytics off.
        cases = [
            scenario("gpc-false", gpc=False),
            scenario("dnt-zero", dnt="0"),
            scenario("sibling-opt-out", storage={"chalkline:analytics-opt-out": "1"}),
            scenario("opt-out-not-1", storage={KEY: "0"}),
            scenario("storage-blocked", storageThrows=True),
            scenario("deep-path", pathname="/cairn/privacy.html"),
        ]
        results = run(loader(INDEX), cases)
        for name, result in results.items():
            with self.subTest(case=name):
                self.assertTrue(loads_ga(result), result)

    def test_the_footer_control_opts_out_and_back_in(self):
        results = run(loader(INDEX), [scenario("toggle", clicks=2)])
        control = results["toggle"]["control"]
        self.assertEqual(control[0]["label"], "Opt out of analytics")
        self.assertFalse(control[0]["hidden"])
        self.assertFalse(control[0]["boxHidden"])
        self.assertEqual(control[1]["label"], "Opt back in")
        self.assertEqual(control[1]["flag"], "1")
        self.assertTrue(control[1]["disabled"])
        self.assertIn("Opted out", control[1]["status"])
        self.assertEqual(control[2]["label"], "Opt out of analytics")
        self.assertIsNone(control[2]["flag"])
        self.assertFalse(control[2]["disabled"])
        self.assertIn("Opted back in", control[2]["status"])

    def test_the_footer_control_reports_a_signal_or_an_earlier_opt_out(self):
        results = run(
            loader(INDEX),
            [scenario("gpc", gpc=True), scenario("was-out", storage={KEY: "1"}),
             scenario("no-storage", storageThrows=True)],
        )
        self.assertTrue(results["gpc"]["control"][0]["hidden"])
        self.assertIn("Global Privacy Control", results["gpc"]["control"][0]["status"])
        self.assertEqual(results["was-out"]["control"][0]["label"], "Opt back in")
        self.assertIn("You have opted out", results["was-out"]["control"][0]["status"])
        self.assertTrue(results["no-storage"]["control"][0]["hidden"])
        self.assertIn("blocking site storage", results["no-storage"]["control"][0]["status"])


class TestNegativeControls(unittest.TestCase):
    """Delete one guard, prove it is gone, and prove the harness now sees GA."""

    TRIGGERS = {
        "host": scenario("host", hostname="localhost", protocol="http:"),
        "path": scenario("path", pathname="/chalkline/"),
        "gpc": scenario("gpc", gpc=True),
        "dnt": scenario("dnt", dnt="1"),
        "opt-out": scenario("opt-out", storage={KEY: "1"}),
    }

    def test_every_guard_has_a_control(self):
        self.assertEqual(set(self.TRIGGERS), set(GUARDS))

    def test_each_guard_is_what_stops_ga(self):
        original = loader(INDEX)
        guarded = run(original, list(self.TRIGGERS.values()))
        for name in GUARDS:
            with self.subTest(guard=name):
                self.assertFalse(loads_ga(guarded[name]), "the intact script loaded GA")
        for name, guard in GUARDS.items():
            with self.subTest(guard=name):
                self.assertEqual(original.count(guard), 1, "the guard is not in the script")
                sabotaged = original.replace(guard, "")
                # The sabotage landed: the guard is gone and nothing else moved.
                self.assertEqual(sabotaged.count(guard), 0)
                self.assertNotEqual(sabotaged, original)
                self.assertEqual(len(original) - len(sabotaged), len(guard))
                result = run(sabotaged, [self.TRIGGERS[name]])[name]
                self.assertTrue(loads_ga(result), f"removing the {name} guard changed nothing")


if __name__ == "__main__":
    unittest.main()
