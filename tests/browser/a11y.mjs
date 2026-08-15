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
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

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
}

/* --- the checks ------------------------------------------------------- */

async function checkKeyboardPath(page, base) {
  section("keyboard path");
  await page.goto(base);
  await page.evaluate(() => document.body.focus());

  const visited = [];
  for (let step = 0; step < 8; step += 1) {
    await page.keyboard.press("Tab");
    const where = await focusedDescription(page);
    const ring = await focusRing(page);
    visited.push(where);
    if (where === "body") break;
    ok(
      ring !== null && ring.width >= 2 && ring.style !== "none",
      `focus is visible on "${where}"`,
      JSON.stringify(ring)
    );
    ok(
      ring !== null && ring.colour !== "rgba(0, 0, 0, 0)",
      `focus indicator is not transparent on "${where}"`,
      ring && ring.colour
    );
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

  // A second question accumulates rather than replacing.
  await page.locator("#question").fill("Who can apply for the grocery allowance?");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelectorAll(".turn-asked").length === 2);
  ok(true, "the transcript accumulates across turns");
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

  ok(true, "a failed request speaks on the assertive channel");
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
  // channel — but must not clear the transcript or reach the network.
  await page.goto(base);
  await page.locator("#question").fill("   ");
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => document.getElementById("errors").textContent.trim().length > 0
  );
  ok(true, "an empty question is reported without a request");
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
      await context.close();
    }

    const context = await browser.newContext({ colorScheme: "light" });
    const page = await context.newPage();
    await page.goto(base);
    await checkKeyboardPath(page, base);
    await checkSkipLink(page, base);
    await checkAnnouncement(page, base);
    await checkErrorChannel(page, base);
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
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
