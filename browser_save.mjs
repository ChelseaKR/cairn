// Save pages that refuse scripts, from a real browser, for the corpus pilot.
//
// Dev-only, and deliberately not part of Cairn's demo or core dev path,
// which stay standard-library Python with no Node and no browser. It reuses
// the Playwright that tests/browser/ already pins for the accessibility
// checks — install it there first (`cd tests/browser && npm ci`) — and adds
// no dependency of its own.
//
// Why this exists: ssa.gov and fcc.gov answer 403 to every non-browser
// client, studentaid.gov drops fetch_pages.py's user agent, dhcs.ca.gov
// serves an Incapsula challenge stub, and siskiyoucounty.gov closes the
// connection. A person saving sixteen pages by hand is fine once; a pilot
// that re-fetches its corpus to measure drift is not a thing a person does
// by hand. So: a real Chromium, one page at a time, a pause between pages,
// and the rendered document written out as HTML.
//
// The three steps, and which file each one owns:
//
//   $ python3 fetch_pages.py corpus/pilot-ca/sources/federal.toml -o source_pages/federal --browser-jobs
//       writes source_pages/federal/browser-jobs.json: pages with no good copy yet
//   $ node browser_save.mjs source_pages/federal            (add --headless to hide the window)
//       saves <file>.html for each job; writes browser-saved.json beside them
//   $ python3 fetch_pages.py corpus/pilot-ca/sources/federal.toml -o source_pages/federal --hand-saved
//       registers them in manifest.json, marked saved_by browser_save.mjs
//
// This script never touches manifest.json. The Python side is the manifest's
// only writer, and a page saved here is registered with `status:
// "hand-saved"` plus `saved_by`, so the manifest says what saved every page.
//
// It runs headed by default. Some of these sites decide whether you are a
// browser by more than the user-agent string, and a visible Chromium with a
// real profile is the most honest thing to be. If a site shows a challenge
// (a spinner, a "verifying your browser" page), the script waits a little
// and saves whatever is there; the Python side flags a saved body under
// 1,500 bytes as a stub, and a reviewer looks.

import { createRequire } from "node:module";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const require = createRequire(resolve(here, "tests/browser/package.json"));

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  console.error(
    "browser_save: Playwright is not installed. It is pinned in tests/browser/package.json;\n" +
      "run `cd tests/browser && npm ci && npx playwright install chromium` and try again.",
  );
  process.exit(2);
}

const args = process.argv.slice(2);
const headless = args.includes("--headless");
const only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;
const dir = args.find((a) => !a.startsWith("--") && a !== only);
if (!dir) {
  console.error("usage: node browser_save.mjs <source_pages/layer> [--headless] [--only <file>]");
  process.exit(2);
}

const jobsPath = join(dir, "browser-jobs.json");
if (!existsSync(jobsPath)) {
  console.error(
    `browser_save: no ${jobsPath}. Run fetch_pages.py ... --browser-jobs first; it writes the list\n` +
      "of pages that still need saving, so this script never decides that for itself.",
  );
  process.exit(2);
}
const { layer, jobs } = JSON.parse(readFileSync(jobsPath, "utf8"));
const selected = only ? jobs.filter((j) => j.file === only) : jobs;
if (selected.length === 0) {
  console.log(`${layer}: nothing to save.`);
  process.exit(0);
}

const sidecarPath = join(dir, "browser-saved.json");
const sidecar = existsSync(sidecarPath)
  ? JSON.parse(readFileSync(sidecarPath, "utf8"))
  : { saved: {} };
const PAUSE_MS = 2500;
const MIN_BYTES = 1500;

const browser = await chromium.launch({ headless });
const context = await browser.newContext({ locale: "en-US" });
const page = await context.newPage();

let saved = 0;
let flagged = 0;
console.log(`${layer}: ${selected.length} page(s) to save${headless ? " (headless)" : ""}`);
for (const [i, job] of selected.entries()) {
  if (i > 0) await page.waitForTimeout(PAUSE_MS);
  const target = join(dir, job.file);
  let finalUrl = job.url;
  let note = "";
  try {
    const response = await page.goto(job.url, { waitUntil: "domcontentloaded", timeout: 45000 });
    // Let client-side rendering and any challenge interstitial settle.
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1500);
    finalUrl = page.url();
    const status = response ? response.status() : null;
    const html = await page.content();
    const title = await page.title();
    const bytes = Buffer.byteLength(html, "utf8");
    if (status && status >= 400) {
      // A 404 page is a page, but not this one. Nothing is written, so the
      // Python side sees the job as still outstanding.
      flagged += 1;
      sidecar.saved[job.file] = {
        url: job.url, final_url: finalUrl, status, title, error: `HTTP ${status}`,
        saved_at: new Date().toISOString(),
      };
      console.log(`  ${job.file}: NOT SAVED (HTTP ${status}, "${title}") — fix the URL`);
      writeFileSync(sidecarPath, JSON.stringify(sidecar, null, 2) + "\n", "utf8");
      continue;
    }
    writeFileSync(target, html, "utf8");
    if (bytes < MIN_BYTES) {
      flagged += 1;
      note = `  <- only ${bytes} bytes; probably a challenge page`;
    }
    sidecar.saved[job.file] = {
      url: job.url,
      final_url: finalUrl,
      status,
      title,
      bytes,
      saved_at: new Date().toISOString(),
    };
    saved += 1;
    console.log(`  ${job.file}: ${bytes} bytes, "${title}"${note}`);
  } catch (err) {
    flagged += 1;
    console.log(`  ${job.file}: FAILED (${err.message.split("\n")[0]})`);
    sidecar.saved[job.file] = {
      url: job.url,
      final_url: finalUrl,
      error: err.message.split("\n")[0],
      saved_at: new Date().toISOString(),
    };
  }
  writeFileSync(sidecarPath, JSON.stringify(sidecar, null, 2) + "\n", "utf8");
}

await browser.close();
console.log(
  `${layer}: ${saved} saved, ${flagged} to look at -> ${sidecarPath}\n` +
    `Next: python3 fetch_pages.py <sources/${layer}.toml> -o ${dir} --hand-saved`,
);
process.exit(flagged ? 1 : 0);
