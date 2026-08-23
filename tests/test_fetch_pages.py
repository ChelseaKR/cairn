"""`fetch_pages.py`: a dev-only page fetcher with a manifest. Offline — the
fetcher is injected, and nothing here opens a socket."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import fetch_pages

GOOD = """
layer = "federal"
terms = "https://www.usa.gov/about-this-site"
terms_checked = "2026-08-23"
terms_note = "federal works, public domain"

[[page]]
url = "https://www.ssa.gov/benefits/retirement/"
lang = "en"
program = "ssa-retirement"

[[page]]
url = "https://www.ssa.gov/es/benefits/retirement/"
lang = "es"
program = "ssa-retirement"
file = "ssa-retirement-es"
"""


# Real pages are big; fetch_pages treats a body under MIN_PAGE_BYTES as a
# bot-challenge stub, so the fake pages here are padded past it.
PAGE = b"<html><title>%s</title><body>" + b"<p>content</p>" * 200 + b"</body></html>"


def _write(tmp: str, text: str) -> Path:
    path = Path(tmp) / "sources.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestFileStem(unittest.TestCase):
    def test_last_two_segments_and_language(self):
        self.assertEqual(
            fetch_pages.file_stem_for("https://www.cdss.ca.gov/food-nutrition/calfresh", "en"),
            "food-nutrition-calfresh-en",
        )

    def test_single_segment(self):
        self.assertEqual(
            fetch_pages.file_stem_for("https://www.usa.gov/food-stamps", "es"), "food-stamps-es"
        )

    def test_bare_host_falls_back_to_the_host(self):
        self.assertEqual(
            fetch_pages.file_stem_for("https://www.usa.gov/", "en"), "www-usa-gov-en"
        )

    def test_unsafe_characters_are_folded(self):
        self.assertEqual(
            fetch_pages.file_stem_for("https://x.gov/A%20B/Q?x=1", "en"), "a-20b-q-en"
        )


class TestLoadSources(unittest.TestCase):
    def test_good_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
        self.assertEqual(sources.layer, "federal")
        self.assertEqual(len(sources.pages), 2)
        self.assertEqual(sources.pages[0].file, "benefits-retirement-en")
        self.assertEqual(sources.pages[1].file, "ssa-retirement-es")
        self.assertEqual(sources.pages[1].lang, "es")

    def test_missing_terms_refuses_to_run(self):
        text = GOOD.replace('terms = "https://www.usa.gov/about-this-site"\n', "")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError) as ctx:
                fetch_pages.load_sources(_write(tmp, text))
        self.assertIn("conditions of use", str(ctx.exception))

    def test_missing_terms_checked_refuses_to_run(self):
        text = GOOD.replace('terms_checked = "2026-08-23"\n', "")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError):
                fetch_pages.load_sources(_write(tmp, text))

    def test_a_blocked_layer_refuses_to_run_and_says_why(self):
        text = 'blocked = "county terms prohibit re-use without written permission"\n' + GOOD
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError) as ctx:
                fetch_pages.load_sources(_write(tmp, text))
        self.assertIn("written permission", str(ctx.exception))
        self.assertIn("blocked", str(ctx.exception))

    def test_duplicate_file_names_are_an_error(self):
        text = GOOD + '\n[[page]]\nurl = "https://other.gov/benefits/retirement/"\n'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError) as ctx:
                fetch_pages.load_sources(_write(tmp, text))
        self.assertIn("benefits-retirement-en", str(ctx.exception))

    def test_duplicate_urls_are_an_error(self):
        text = GOOD + '\n[[page]]\nurl = "https://www.ssa.gov/benefits/retirement/"\nfile="x"\n'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError):
                fetch_pages.load_sources(_write(tmp, text))

    def test_non_http_url_is_an_error(self):
        text = GOOD.replace("https://www.ssa.gov/benefits/retirement/", "file:///etc/passwd")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError):
                fetch_pages.load_sources(_write(tmp, text))

    def test_empty_list_is_an_error(self):
        text = GOOD.split("[[page]]")[0]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fetch_pages.SourceError):
                fetch_pages.load_sources(_write(tmp, text))


class TestRun(unittest.TestCase):
    def _sources(self, tmp: str) -> fetch_pages.SourceList:
        return fetch_pages.load_sources(_write(tmp, GOOD))

    def test_writes_pages_and_a_manifest_the_importer_can_read(self):
        bodies = {
            "https://www.ssa.gov/benefits/retirement/": PAGE % b"Retire",
            "https://www.ssa.gov/es/benefits/retirement/": PAGE % b"Jubilar",
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            failed = fetch_pages.run(
                self._sources(tmp),
                out,
                fetcher=lambda url: (200, bodies[url]),
                pause=0,
                today="2026-08-23",
                log=lambda _: None,
            )
            self.assertEqual(failed, 0)
            self.assertEqual(
                sorted(p.name for p in out.iterdir()),
                ["benefits-retirement-en.html", "manifest.json", "ssa-retirement-es.html"],
            )
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["layer"], "federal")
            self.assertEqual(manifest["terms_checked"], "2026-08-23")
            by_file = {p["file"]: p for p in manifest["pages"]}
            es = by_file["ssa-retirement-es.html"]
            self.assertEqual(es["url"], "https://www.ssa.gov/es/benefits/retirement/")
            self.assertEqual(es["lang"], "es")
            self.assertEqual(es["status"], 200)
            self.assertEqual(es["fetched_at"], "2026-08-23")
            self.assertEqual(len(es["sha256"]), 64)
            self.assertEqual(es["terms"], "https://www.usa.gov/about-this-site")

            # The join the whole pipeline depends on: import_corpus.py reads
            # this manifest by file name and gets the URL and language back.
            import import_corpus

            loaded = import_corpus.load_manifest(out)
            self.assertEqual(loaded["ssa-retirement-es.html"]["lang"], "es")

    def test_a_failure_is_recorded_and_does_not_stop_the_batch(self):
        def fetcher(url: str) -> tuple[int, bytes]:
            if "/es/" in url:
                return 404, b"not found"
            return 200, PAGE % b"ok"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            lines: list[str] = []
            failed = fetch_pages.run(
                self._sources(tmp), out, fetcher=fetcher, pause=0, today="x", log=lines.append
            )
            self.assertEqual(failed, 1)
            self.assertTrue((out / "benefits-retirement-en.html").is_file())
            self.assertFalse((out / "ssa-retirement-es.html").exists())
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            by_file = {p["file"]: p for p in manifest["pages"]}
            self.assertEqual(by_file["ssa-retirement-es.html"]["status"], 404)
            self.assertEqual(by_file["ssa-retirement-es.html"]["error"], "HTTP 404")
            self.assertNotIn("sha256", by_file["ssa-retirement-es.html"])
            self.assertTrue(any("FAILED" in line for line in lines))

    def test_a_tiny_200_is_a_stub_not_a_page(self):
        def fetcher(url: str) -> tuple[int, bytes]:
            return 200, b"<html><script src='/_Incapsula_Resource'></script></html>"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            failed = fetch_pages.run(
                self._sources(tmp), out, fetcher=fetcher, pause=0, today="x", log=lambda _: None
            )
            self.assertEqual(failed, 2)
            self.assertFalse((out / "benefits-retirement-en.html").exists())
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("stub", manifest["pages"][0]["error"])
            self.assertEqual(manifest["pages"][0]["status"], 200)

    def test_a_network_error_is_recorded_not_raised(self):
        def fetcher(url: str) -> tuple[int, bytes]:
            raise OSError("connection refused")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            failed = fetch_pages.run(
                self._sources(tmp), out, fetcher=fetcher, pause=0, today="x", log=lambda _: None
            )
            self.assertEqual(failed, 2)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["pages"][0]["status"], 0)
            self.assertIn("connection refused", manifest["pages"][0]["error"])

    def test_already_saved_pages_are_skipped_unless_refresh(self):
        calls: list[str] = []

        def fetcher(url: str) -> tuple[int, bytes]:
            calls.append(url)
            return 200, PAGE % b"ok"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            sources = self._sources(tmp)
            quiet = {"pause": 0, "today": "x", "log": lambda _: None}
            fetch_pages.run(sources, out, fetcher=fetcher, **quiet)
            self.assertEqual(len(calls), 2)
            fetch_pages.run(sources, out, fetcher=fetcher, **quiet)
            self.assertEqual(len(calls), 2)
            fetch_pages.run(sources, out, fetcher=fetcher, refresh=True, **quiet)
            self.assertEqual(len(calls), 4)

    def test_a_failed_page_is_retried_on_the_next_run(self):
        attempts: list[str] = []

        def first(url: str) -> tuple[int, bytes]:
            attempts.append(url)
            return (503, b"") if "/es/" in url else (200, PAGE % b"ok")

        def second(url: str) -> tuple[int, bytes]:
            attempts.append(url)
            return 200, PAGE % b"ok"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            sources = self._sources(tmp)
            quiet = {"pause": 0, "today": "x", "log": lambda _: None}
            self.assertEqual(fetch_pages.run(sources, out, fetcher=first, **quiet), 1)
            self.assertEqual(fetch_pages.run(sources, out, fetcher=second, **quiet), 0)
            # Only the failed page was re-requested.
            self.assertEqual(attempts.count("https://www.ssa.gov/benefits/retirement/"), 1)
            self.assertEqual(attempts.count("https://www.ssa.gov/es/benefits/retirement/"), 2)


class TestHandSaved(unittest.TestCase):
    def test_registers_saved_files_and_reports_missing_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            out.mkdir()
            (out / "benefits-retirement-en.html").write_bytes(b"<html>saved by hand</html>")
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
            lines: list[str] = []
            n = fetch_pages.register_hand_saved(
                sources, out, today="2026-08-23", log=lines.append
            )
            self.assertEqual(n, 1)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            by_file = {p["file"]: p for p in manifest["pages"]}
            entry = by_file["benefits-retirement-en.html"]
            self.assertEqual(entry["status"], "hand-saved")
            self.assertEqual(entry["url"], "https://www.ssa.gov/benefits/retirement/")
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertNotIn("ssa-retirement-es.html", by_file)
            self.assertTrue(any("not saved" in line for line in lines))

    def test_a_fetched_page_is_not_overwritten_as_hand_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
            fetch_pages.run(
                sources, out, fetcher=lambda u: (200, PAGE % b"fetched"), pause=0,
                today="x", log=lambda _: None,
            )
            n = fetch_pages.register_hand_saved(sources, out, today="y", log=lambda _: None)
            self.assertEqual(n, 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(all(p["status"] == 200 for p in manifest["pages"]))

    def test_cli_hand_saved_mode_never_calls_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            out.mkdir()
            (out / "ssa-retirement-es.html").write_bytes(b"<html>x</html>")
            path = _write(tmp, GOOD)

            def explode(url: str) -> tuple[int, bytes]:
                raise AssertionError("network touched")

            original = fetch_pages.fetch_url
            fetch_pages.fetch_url = explode  # type: ignore[assignment]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = fetch_pages.main([str(path), "-o", str(out), "--hand-saved"])
            finally:
                fetch_pages.fetch_url = original  # type: ignore[assignment]
            self.assertEqual(code, 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["pages"][0]["status"], "hand-saved")


class TestMain(unittest.TestCase):
    def test_bad_source_list_exits_2_before_any_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, 'layer = "x"\n[[page]]\nurl = "https://a.gov/b"\n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = fetch_pages.main([str(path), "-o", str(Path(tmp) / "out")])
            self.assertEqual(code, 2)
            self.assertIn("conditions of use", err.getvalue())
            self.assertFalse((Path(tmp) / "out").exists())


if __name__ == "__main__":
    unittest.main()


class TestBrowserJobsAndSidecar(unittest.TestCase):
    """The handshake with browser_save.mjs: Python writes the job list from
    the manifest, the browser script saves files and a sidecar, Python
    registers them and says what saved each one."""

    def test_jobs_list_only_the_pages_without_a_good_copy(self):
        def fetcher(url: str) -> tuple[int, bytes]:
            return (403, b"") if "/es/" in url else (200, PAGE % b"ok")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
            quiet = {"pause": 0, "today": "x", "log": lambda _: None}
            fetch_pages.run(sources, out, fetcher=fetcher, **quiet)
            n = fetch_pages.write_browser_jobs(sources, out, log=lambda _: None)
            self.assertEqual(n, 1)
            jobs = json.loads((out / "browser-jobs.json").read_text(encoding="utf-8"))
            self.assertEqual(jobs["layer"], "federal")
            self.assertEqual(
                jobs["jobs"],
                [
                    {
                        "file": "ssa-retirement-es.html",
                        "url": "https://www.ssa.gov/es/benefits/retirement/",
                        "lang": "es",
                        "program": "ssa-retirement",
                    }
                ],
            )

    def test_registration_reads_the_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            out.mkdir()
            (out / "ssa-retirement-es.html").write_bytes(PAGE % b"Jubilar")
            (out / "browser-saved.json").write_text(
                json.dumps(
                    {
                        "saved": {
                            "ssa-retirement-es.html": {
                                "url": "https://www.ssa.gov/es/benefits/retirement/",
                                "final_url": "https://www.ssa.gov/es/retirement",
                                "status": 200,
                                "title": "Jubilación",
                                "saved_at": "2026-08-24T10:00:00.000Z",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
            n = fetch_pages.register_hand_saved(
                sources, out, today="2026-08-25", log=lambda _: None
            )
            self.assertEqual(n, 1)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            entry = {p["file"]: p for p in manifest["pages"]}["ssa-retirement-es.html"]
            self.assertEqual(entry["status"], "hand-saved")
            self.assertEqual(entry["saved_by"], "browser_save.mjs")
            self.assertEqual(entry["final_url"], "https://www.ssa.gov/es/retirement")
            # The browser's date, not the registration's.
            self.assertEqual(entry["fetched_at"], "2026-08-24")
            self.assertNotIn("error", entry)

    def test_a_file_the_browser_reported_an_error_for_is_not_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            out.mkdir()
            (out / "ssa-retirement-es.html").write_bytes(PAGE % b"Page not found")
            (out / "browser-saved.json").write_text(
                json.dumps(
                    {
                        "saved": {
                            "ssa-retirement-es.html": {
                                "url": "https://www.ssa.gov/es/benefits/retirement/",
                                "status": 404,
                                "error": "HTTP 404",
                                "saved_at": "2026-08-24T10:00:00.000Z",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
            lines: list[str] = []
            n = fetch_pages.register_hand_saved(sources, out, today="x", log=lines.append)
            self.assertEqual(n, 0)
            self.assertTrue(any("HTTP 404" in line for line in lines))

    def test_a_saved_stub_is_registered_and_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pages"
            out.mkdir()
            (out / "ssa-retirement-es.html").write_bytes(b"<html>challenge</html>")
            sources = fetch_pages.load_sources(_write(tmp, GOOD))
            fetch_pages.register_hand_saved(sources, out, today="x", log=lambda _: None)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            entry = {p["file"]: p for p in manifest["pages"]}["ssa-retirement-es.html"]
            self.assertIn("stub", entry["error"])
            self.assertNotIn("saved_by", entry)  # no sidecar: a person saved it
            # And it is still outstanding for the next browser run.
            n = fetch_pages.write_browser_jobs(sources, out, log=lambda _: None)
            self.assertEqual(n, 2)
