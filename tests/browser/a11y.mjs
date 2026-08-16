/* Accessibility behaviours, driven against real Chromium.
 *
 * tests/test_ui.py already checks everything the markup and stylesheet can
 * promise on their own. This file checks the promises that only a running
 * browser can keep or break:
 *
 *   - the tab order, and that it comes back round instead of trapping;
 *   - that focus is actually visible on every stop, in both presentations;
 *   - that an answer is announced politely and does not steal focus;
 *   - that the assertive channel stays silent on success and speaks on
 *     failure, which is the whole point of having two channels;
 *   - that switching to Arabic mirrors the layout rather than only the words;
 *   - axe-core's WCAG 2.2 AA rule set, in light, dark, and right-to-left.
 *
 * It starts the real `cairn serve` process and drives the real page. Run it
 * with `npm install && npm run check` from this directory. It is deliberately
 * outside Cairn's own dev path: the engine installs, lints and tests with no
 * Node, no browser, and no network.
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/* The rule set is a judgement, so it is pinned like one.
 *
 * package.json names an exact axe-core version and package-lock.json is
 * committed, which fixes what `npm ci` installs. This reads the pin back and
 * compares it to the version that was actually injected into the page, which
 * is a different claim: a stale node_modules, an `npm install` that resolved
 * something else, or a hoisted copy at another version all satisfy the first
 * and break the second. axe-core reports what ran in `testEngine.version`,
 * and a rule set that got stricter overnight and a page that regressed
 * overnight are the same red tick unless somebody knows which version spoke.
 */
const PINNED_AXE = JSON.parse(
  readFileSync(path.join(HERE, "package.json"), "utf8")
).devDependencies["axe-core"];

/* Every check this file is expected to run. A dropped check does not fail:
 * `ok` is never reached, so `checks` is smaller and the final line reads
 * "31/31 behaviour checks passed" in exactly the green the full run prints.
 * The count is the only thing that can tell those apart, so it is pinned, and
 * moving it is a reviewed diff like any other bar in this repository.
 */
const EXPECTED_CHECKS = 63;

let failures = 0;
let checks = 0;

function ok(condition, description, detail) {
  checks += 1;
  if (condition) {
    console.log(`  pass  ${description}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${description}`);
    if (detail !== undefined) console.log(`        ${detail}`);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

/* --- the server under test ------------------------------------------- */

function startServer() {
  return new Promise((resolve, reject) => {
    const proc = spawn("python3", ["-m", "cairn", "serve", "--port", "0"], {
      cwd: ROOT,
      env: { ...process.env, PYTHONUNBUFFERED: "1" }
    });
    const timer = setTimeout(() => reject(new Error("server did not start")), 15000);
    proc.stdout.on("data", (chunk) => {
      const found = String(chunk).match(/http:\/\/[\d.]+:\d+\//);
      if (found) {
        clearTimeout(timer);
        resolve({ proc, base: found[0] });
      }
    });
    proc.stderr.on("data", (chunk) => {
      const text = String(chunk);
      if (text.includes("Traceback")) console.error(text);
    });
    proc.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`server exited with ${code}`));
    });
  });
}

/* --- helpers ---------------------------------------------------------- */

async function focusedDescription(page) {
  return page.evaluate(() => {
    const node = document.activeElement;
    if (!node || node === document.body) return "body";
    return node.id || node.className || node.tagName.toLowerCase();
  });
}

async function focusRing(page) {
  return page.evaluate(() => {
    const node = document.activeElement;
    if (!node || node === document.body) return null;
    const style = getComputedStyle(node);
    return {
      width: parseFloat(style.outlineWidth) || 0,
      style: style.outlineStyle,
      colour: style.outlineColor
    };
  });
}

async function axeScan(page, label) {
  const result = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const summary = result.violations
    .map((v) => `${v.id} (${v.nodes.length}) — ${v.help}`)
    .join("; ");
  ok(result.violations.length === 0, `axe WCAG 2.2 AA clean: ${label}`, summary);
  return result;
}

/* Which rule set graded the page — asked of the page, not of the manifest. */
async function checkRuleSetVersion(page) {
  section("the rule set that graded this run");
  const ran = (await new AxeBuilder({ page }).withTags(WCAG).analyze()).testEngine;
  ok(
    ran !== undefined && ran.version === PINNED_AXE,
    `axe-core ${PINNED_AXE} is what ran in the browser`,
    `package.json pins ${PINNED_AXE}; the page was graded by ${JSON.stringify(ran)}`
  );
}

/* --- the checks ------------------------------------------------------- */

/* Is the ring actually drawn, on every stop, in the presentation the reader
 * is using?
 *
 * This used to live inside checkKeyboardPath, which runs once, in a light
 * context — while the comment at the top of this file said focus visibility
 * was checked "in both presentations". `--focus` does have a dark override
 * (tests/test_ui.py requires every colour a contrast pair uses to be
 * re-themed), so this is a claim being made true rather than a bug being
 * caught. A ring drawn in a colour nobody re-themed is exactly the shape of
 * defect that check found in the palette, one layer up.
 */
async function checkFocusVisibility(page, base, scheme) {
  section(`focus visibility (${scheme})`);
  await page.goto(base);
  await page.evaluate(() => document.body.focus());

  const stops = [];
  for (let step = 0; step < 8; step += 1) {
    await page.keyboard.press("Tab");
    const where = await focusedDescription(page);
    if (where === "body") break;
    stops.push(where);
    const ring = await focusRing(page);
    ok(
      ring !== null && ring.width >= 2 && ring.style !== "none",
      `focus is visible on "${where}" (${scheme})`,
      JSON.stringify(ring)
    );
    ok(
      ring !== null && ring.colour !== "rgba(0, 0, 0, 0)",
      `focus indicator is not transparent on "${where}" (${scheme})`,
      ring && ring.colour
    );
  }
  // Without this the loop above is a check that passes by finding nothing:
  // a page with no reachable control emits no assertions and no failures.
  ok(
    stops.length >= 4,
    `there were controls to check the ring on (${scheme})`,
    stops.join(" -> ")
  );
}

async function checkKeyboardPath(page, base) {
  section("keyboard path");
  await page.goto(base);
  await page.evaluate(() => document.body.focus());

  const visited = [];
  for (let step = 0; step < 8; step += 1) {
    await page.keyboard.press("Tab");
    visited.push(await focusedDescription(page));
    if (visited[visited.length - 1] === "body") break;
  }

  ok(visited[0] === "skip-link", "the first tab stop is the skip link", visited.join(" -> "));
  ok(
    visited.includes("transcript") &&
      visited.includes("lang") &&
      visited.includes("question"),
    "the tab order reaches the transcript, the language selector and the input",
    visited.join(" -> ")
  );
  ok(
    new Set(visited).size === visited.length,
    "no stop is visited twice before leaving the page (no trap)",
    visited.join(" -> ")
  );
  ok(
    visited[visited.length - 1] === "body",
    "tabbing past the last control leaves the page instead of cycling forever",
    visited.join(" -> ")
  );

  // Backwards, too: a one-way path is still a trap for anyone going back.
  await page.locator("#question").focus();
  await page.keyboard.press("Shift+Tab");
  ok(
    (await focusedDescription(page)) === "lang",
    "shift+tab moves backwards out of the input"
  );
}

async function checkSkipLink(page, base) {
  section("skip link");
  await page.goto(base);
  await page.evaluate(() => document.body.focus());
  await page.keyboard.press("Tab");
  const box = await page.locator(".skip-link").boundingBox();
  const width = page.viewportSize().width;
  ok(
    box !== null && box.x >= 0 && box.x < width,
    "the skip link becomes visible when focused",
    JSON.stringify(box)
  );
  await page.keyboard.press("Enter");
  ok(
    (await focusedDescription(page)) === "question",
    "activating the skip link puts focus in the question box"
  );
}

async function checkAnnouncement(page, base) {
  section("announcement and focus");
  await page.goto(base);
  await page.locator("#question").fill("How much is the monthly grocery allowance?");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".turn-answered");

  ok(
    (await focusedDescription(page)) === "question",
    "an arriving answer never steals focus"
  );
  const status = (await page.locator("#status").textContent()).trim();
  ok(status.length > 0, "answer completion is announced", JSON.stringify(status));
  ok(
    (await page.locator("#errors").textContent()).trim() === "",
    "the assertive channel stays silent on success"
  );
  ok(
    (await page.locator("#transcript").getAttribute("aria-live")) === "polite",
    "the transcript queues politely"
  );
  ok(
    (await page.locator(".turn-answered .answer").first().textContent()).includes("$212"),
    "the answer reached the transcript"
  );
  ok(
    (await page.locator(".turn-answered .sources li").count()) > 0,
    "the answer arrived with its sources"
  );

  // A second question accumulates rather than replacing. Asserted on the
  // *first* question still being there: waiting for two turns proves a second
  // one arrived, which is not the same claim.
  await page.locator("#question").fill("Who can apply for the grocery allowance?");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelectorAll(".turn-asked").length === 2);
  const asked = await page.locator(".turn-asked .asked").allTextContents();
  ok(
    asked.length === 2 && asked[0].includes("How much is the monthly grocery allowance?"),
    "the transcript accumulates: the first question is still in it",
    JSON.stringify(asked)
  );
}

async function checkErrorChannel(page, base) {
  section("errors-only assertive channel");
  await page.goto(base);
  await page.route("**/ask", (route) => route.abort());
  await page.locator("#question").fill("How much is the monthly grocery allowance?");
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => document.getElementById("errors").textContent.trim().length > 0
  );

  const spoken = (await page.locator("#errors").textContent()).trim();
  ok(spoken.length > 0, "a failed request speaks on the assertive channel", spoken);
  ok(
    (await page.locator("#status").textContent()).trim() === "",
    "the polite channel does not also report the failure"
  );
  ok(
    (await page.locator(".turn-answered").count()) === 0,
    "nothing enters the transcript when nothing was answered"
  );
  ok(
    (await page.locator("#errors").getAttribute("role")) === "alert",
    "the error region is the assertive one"
  );
  await page.unroute("**/ask");

  // An empty question is a user error, not a server one, and uses the same
  // channel — but must not reach the network. The second half of that used to
  // be in the description of a check that asserted nothing, so count the
  // requests and say it for real: the browser must not post the form either,
  // which is what a missing preventDefault would do.
  await page.goto(base);
  let posted = 0;
  const countAsk = (request) => {
    if (request.url().endsWith("/ask")) posted += 1;
  };
  page.on("request", countAsk);
  await page.locator("#question").fill("   ");
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => document.getElementById("errors").textContent.trim().length > 0
  );
  page.off("request", countAsk);
  ok(
    (await page.locator("#errors").textContent()).trim().length > 0,
    "an empty question is reported on the assertive channel"
  );
  ok(posted === 0, "…and nothing was sent to /ask", `${posted} request(s)`);
}

async function checkRightToLeft(page, base) {
  section("right to left is layout, not just words");
  await page.goto(base);
  const before = await page.locator(".send").boundingBox();
  await page.waitForFunction(
    () => document.documentElement.getAttribute("data-strings") === "ready"
  );
  await page.selectOption("#lang", "ar");
  await page.waitForFunction(() => document.documentElement.dir === "rtl");

  ok((await page.getAttribute("html", "lang")) === "ar", "the document language switches");
  ok((await page.getAttribute("html", "dir")) === "rtl", "the document direction switches");

  const after = await page.locator(".send").boundingBox();
  ok(
    Math.abs(after.x - before.x) > 20,
    "the send control moves to the other side of the page",
    `before x=${before.x}, after x=${after.x}`
  );

  const heading = await page.locator("h1").textContent();
  ok(/[؀-ۿ]/.test(heading), "the chrome is retranslated, not only reflowed");

  const disclosure = await page.locator(".disclosure li").first().textContent();
  ok(
    /[؀-ۿ]/.test(disclosure),
    "the standing disclosure is retranslated too"
  );

  // An answer in a right-to-left page still marks a left-to-right quote.
  await page.locator("#question").fill("How much does the GoPass cost per year?");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".turn-answered .answer");
  const quote = page.locator(".turn-answered .answer").first();
  ok((await quote.getAttribute("lang")) === "en", "an English quote declares English");
  ok((await quote.getAttribute("dir")) === "ltr", "an English quote declares left-to-right");
  ok(
    (await page.locator(".turn-answered .notice").getAttribute("dir")) === "rtl",
    "the notice about it is right-to-left"
  );
}

/* The interface has to be able to speak before it has fetched anything.
 *
 * This is a regression check with a date on it: the announcements used to
 * come from /strings.json along with every other language, so between page
 * load and that response the script wrote the empty string into the live
 * regions. An empty live region announces nothing. On a fast laptop the
 * window was invisible; on a CI runner it was wide enough to fail the two
 * checks above roughly every time, which is how it was found. Blocking the
 * fetch outright makes the window permanent and the check deterministic.
 */
async function checkVoiceWithoutTheFetch(page, base) {
  section("announcements do not wait for /strings.json");
  await page.route("**/strings.json", (route) => route.abort());
  await page.goto(base);
  await page.waitForFunction(
    () => document.documentElement.getAttribute("data-strings") === "unavailable"
  );

  await page.locator("#question").fill("How much is the monthly grocery allowance?");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".turn-answered");
  ok(
    (await page.locator("#status").textContent()).trim().length > 0,
    "an answer is still announced when the catalogue never arrived"
  );
  ok(
    (await page.locator(".turn-answered .turn-label").first().textContent()).trim()
      .length > 0,
    "the transcript still labels who is speaking"
  );

  await page.route("**/ask", (route) => route.abort());
  await page.locator("#question").fill("How much is the monthly grocery allowance?");
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => document.getElementById("errors").textContent.trim().length > 0
  );
  ok(
    (await page.locator("#errors").textContent()).trim().length > 0,
    "a failure is still spoken on the assertive channel"
  );
  await page.unroute("**/ask");
  await page.unroute("**/strings.json");
}

async function checkTargetSizes(page, base) {
  section("target size");
  await page.goto(base);
  for (const selector of ["#lang", "#question", ".send"]) {
    const box = await page.locator(selector).boundingBox();
    ok(
      box.width >= 24 && box.height >= 24,
      `"${selector}" clears the 24 by 24 minimum`,
      JSON.stringify(box)
    );
  }
}

async function main() {
  const { proc, base } = await startServer();
  const browser = await chromium.launch();
  try {
    for (const scheme of ["light", "dark"]) {
      const context = await browser.newContext({ colorScheme: scheme });
      const page = await context.newPage();
      section(`axe (${scheme})`);
      await page.goto(base);
      await axeScan(page, `${scheme}, English, empty transcript`);
      await page.locator("#question").fill("How much is the monthly grocery allowance?");
      await page.keyboard.press("Enter");
      await page.waitForSelector(".turn-answered");
      await axeScan(page, `${scheme}, English, with an answer`);
      await page.goto(`${base}?lang=ar`);
      await axeScan(page, `${scheme}, Arabic, right to left`);
      await checkFocusVisibility(page, base, scheme);
      await context.close();
    }

    const context = await browser.newContext({ colorScheme: "light" });
    const page = await context.newPage();
    await page.goto(base);
    await checkRuleSetVersion(page);
    await checkKeyboardPath(page, base);
    await checkSkipLink(page, base);
    await checkAnnouncement(page, base);
    await checkErrorChannel(page, base);
    await checkVoiceWithoutTheFetch(page, base);
    await checkTargetSizes(page, base);
    await checkRightToLeft(page, base);
    await context.close();
  } finally {
    await browser.close();
    proc.kill("SIGINT");
  }

  console.log(`\n${checks - failures}/${checks} behaviour checks passed`);
  if (failures) {
    console.log(`${failures} failed`);
    process.exit(1);
  }
  if (checks !== EXPECTED_CHECKS) {
    console.log(
      `\nFAIL  ${checks} checks ran and this file pins ${EXPECTED_CHECKS}. ` +
        (checks < EXPECTED_CHECKS
          ? "Checks that stop running report as a smaller green total, which is " +
            "why the total is pinned."
          : "Adopt the new count here in the same commit that added them, and " +
            "in the README, or the next one to go missing has room to hide.")
    );
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
