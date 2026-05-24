#!/usr/bin/env python3
"""Tests for floodgate. Stdlib unittest only — no third-party packages.

    python3 test_floodgate.py            # or: python3 -m unittest -v

Most tests import the floodgate script as a module and exercise its functions
directly (review-id derivation, annotation/roll-up, marks, the --only/--hide
resolver, and HTML rendering). A few integration tests drive the CLI through a
real git repo + diffkit and are skipped when git or diffkit isn't available.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "floodgate"
DIFFKIT = HERE.parent / "diffkit"
PIPE = subprocess.PIPE


def _load_floodgate():
    # The script has no .py extension, so load it by an explicit source loader.
    loader = importlib.machinery.SourceFileLoader("floodgate_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


fg = _load_floodgate()


# --------------------------------------------------------------------------- #
# helpers to build diffkit-schema docs
# --------------------------------------------------------------------------- #
def line(kind, text, old=None, new=None):
    return {"kind": kind, "text": text, "old_lineno": old, "new_lineno": new}


def hunk(lines, old_start=1, new_start=1, section="", **extra):
    h = {"old_start": old_start, "old_count": 0, "new_start": new_start,
         "new_count": 0, "section": section, "lines": lines}
    h.update(extra)
    return h


def file_rec(old_path, new_path, status="modified", hunks=None, **extra):
    f = {"old_path": old_path, "new_path": new_path, "status": status,
         "old_mode": None, "new_mode": None, "similarity": None,
         "binary": False, "hunks": hunks or []}
    f.update(extra)
    return f


def doc(*files):
    return {"schema": "diffkit.diff/v1", "old": "a", "new": "b", "files": list(files)}


def silence_stderr():
    return contextlib.redirect_stderr(io.StringIO())


# --------------------------------------------------------------------------- #
# review ids
# --------------------------------------------------------------------------- #
class TestReviewIds(unittest.TestCase):
    def test_hunk_id_deterministic(self):
        h = lambda: hunk([line("add", "x"), line("del", "y")])
        self.assertEqual(fg.hunk_review_id("p", 0, h()), fg.hunk_review_id("p", 0, h()))

    def test_hunk_id_sensitive_to_content_path_ordinal(self):
        base = fg.hunk_review_id("p", 0, hunk([line("add", "x"), line("del", "y")]))
        self.assertNotEqual(base, fg.hunk_review_id("p", 0, hunk([line("add", "X"), line("del", "y")])))
        self.assertNotEqual(base, fg.hunk_review_id("p", 1, hunk([line("add", "x"), line("del", "y")])))
        self.assertNotEqual(base, fg.hunk_review_id("q", 0, hunk([line("add", "x"), line("del", "y")])))

    def test_hunk_id_ignores_context_lines(self):
        # Only changed (add/del) lines feed the id; context must not affect it.
        a = fg.hunk_review_id("p", 0, hunk([line("add", "x"), line("del", "y")]))
        b = fg.hunk_review_id("p", 0, hunk([line("context", "c"), line("add", "x"), line("del", "y")]))
        self.assertEqual(a, b)

    def test_file_unit_id_distinguishes_paths(self):
        self.assertNotEqual(
            fg.file_unit_id(file_rec("a", "b", status="renamed")),
            fg.file_unit_id(file_rec("a", "c", status="renamed")))


# --------------------------------------------------------------------------- #
# annotate + roll-up
# --------------------------------------------------------------------------- #
class TestAnnotate(unittest.TestCase):
    def test_stamps_ids_and_unreviewed_by_default(self):
        d = doc(file_rec("a.py", "a.py", hunks=[hunk([line("add", "foo")])]))
        fg.annotate(d, {})
        h = d["files"][0]["hunks"][0]
        self.assertIn("review_id", h)
        self.assertEqual(h["review_status"], "unreviewed")
        self.assertEqual(d["files"][0]["review_status"], "unreviewed")

    def test_applies_marks(self):
        d = doc(file_rec("a.py", "a.py", hunks=[hunk([line("add", "foo")])]))
        fg.annotate(d, {})                      # learn the id
        hid = d["files"][0]["hunks"][0]["review_id"]
        d2 = doc(file_rec("a.py", "a.py", hunks=[hunk([line("add", "foo")])]))
        fg.annotate(d2, {hid: {"status": "accepted"}})
        self.assertEqual(d2["files"][0]["hunks"][0]["review_status"], "accepted")
        self.assertEqual(d2["files"][0]["review_status"], "accepted")

    def test_file_rollup_partial(self):
        mk = lambda: doc(file_rec("a.py", "a.py", hunks=[
            hunk([line("add", "1")]), hunk([line("add", "2")], new_start=20)]))
        d = mk()
        fg.annotate(d, {})
        first = d["files"][0]["hunks"][0]["review_id"]
        d2 = mk()
        fg.annotate(d2, {first: {"status": "accepted"}})
        self.assertEqual(d2["files"][0]["review_status"], "partial")

    def test_structural_file_status_from_mark(self):
        d = doc(file_rec("old", "new", status="renamed"))
        fg.annotate(d, {})
        fid = d["files"][0]["review_id"]
        d2 = doc(file_rec("old", "new", status="renamed"))
        fg.annotate(d2, {fid: {"status": "rejected"}})
        self.assertEqual(d2["files"][0]["review_status"], "rejected")

    def test_collect_units_covers_hunks_and_structural_files(self):
        d = doc(file_rec("a.py", "a.py", hunks=[hunk([line("add", "1")])]),
                file_rec("old", "new", status="renamed"))
        fg.annotate(d, {})
        pairs = fg.collect_units(d)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(sorted(p for _id, p in pairs), ["a.py", "new"])


class TestRollup(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(fg.rollup([]), "unreviewed")
        self.assertEqual(fg.rollup(["unreviewed", "unreviewed"]), "unreviewed")
        self.assertEqual(fg.rollup(["accepted", "accepted"]), "accepted")
        self.assertEqual(fg.rollup(["accepted", "unreviewed"]), "partial")
        self.assertEqual(fg.rollup(["accepted", "rejected"]), "mixed")


# --------------------------------------------------------------------------- #
# marks + tally
# --------------------------------------------------------------------------- #
class TestMarks(unittest.TestCase):
    def test_apply_and_tally(self):
        review = {"marks": {}}
        fg.apply_marks(review, [("id1", "a"), ("id2", "b")], "accepted")
        self.assertEqual(review["marks"]["id1"]["status"], "accepted")
        self.assertEqual(review["marks"]["id1"]["path"], "a")
        self.assertIn("updated", review)
        c = fg.tally(["id1", "id2", "id3"], review["marks"])
        self.assertEqual((c["accepted"], c["unreviewed"], c["total"]), (2, 1, 3))

    def test_clear_removes_mark(self):
        review = {"marks": {"id1": {"status": "accepted", "path": "a"}}}
        fg.apply_marks(review, [("id1", "a")], "clear")
        self.assertNotIn("id1", review["marks"])

    def test_mark_status_default(self):
        self.assertEqual(fg.mark_status({}, "missing"), "unreviewed")
        self.assertEqual(fg.mark_status({"x": {"status": "skipped"}}, "x"), "skipped")


# --------------------------------------------------------------------------- #
# --only / --hide resolver
# --------------------------------------------------------------------------- #
class TestResolveVisible(unittest.TestCase):
    def test_none_means_all(self):
        self.assertIsNone(fg.resolve_visible(None, None))

    def test_only(self):
        self.assertEqual(fg.resolve_visible("accepted", None), {"accepted"})
        self.assertEqual(fg.resolve_visible("skipped,unreviewed", None), {"skipped", "unreviewed"})

    def test_hide_is_complement(self):
        self.assertEqual(fg.resolve_visible(None, "accepted"),
                         {"rejected", "skipped", "unreviewed"})

    def test_whitespace_tolerated(self):
        self.assertEqual(fg.resolve_visible("  accepted , skipped ", None), {"accepted", "skipped"})

    def test_errors(self):
        with silence_stderr():
            for only, hide in [("accepted", "skipped"), ("bogus", None),
                               (None, "nope"), ("", None)]:
                with self.assertRaises(SystemExit):
                    fg.resolve_visible(only, hide)


# --------------------------------------------------------------------------- #
# resolve_pair (--continue)
# --------------------------------------------------------------------------- #
class _Args:
    def __init__(self, base=None, target=None, cont=False, two_dot=False):
        self.base, self.target, self.cont, self.two_dot = base, target, cont, two_dot


class TestResolvePair(unittest.TestCase):
    REVIEW = {"base": {"rev": "main"}, "target": {"rev": "feat"}, "mode": "two-dot"}

    def test_explicit_pair(self):
        self.assertEqual(fg.resolve_pair(_Args(base="m", target="f"), None),
                         ("m", "f", "three-dot"))
        self.assertEqual(fg.resolve_pair(_Args(base="m", target="f", two_dot=True), None),
                         ("m", "f", "two-dot"))

    def test_missing_pair_errors(self):
        with silence_stderr():
            with self.assertRaises(SystemExit):
                fg.resolve_pair(_Args(), None)
            with self.assertRaises(SystemExit):
                fg.resolve_pair(_Args(base="m"), None)        # only one given

    def test_continue_reads_review(self):
        self.assertEqual(fg.resolve_pair(_Args(cont=True), self.REVIEW),
                         ("main", "feat", "two-dot"))

    def test_continue_defaults_mode_three_dot(self):
        self.assertEqual(
            fg.resolve_pair(_Args(cont=True), {"base": {"rev": "a"}, "target": {"rev": "b"}}),
            ("a", "b", "three-dot"))

    def test_continue_errors(self):
        with silence_stderr():
            with self.assertRaises(SystemExit):                 # no .review
                fg.resolve_pair(_Args(cont=True), None)
            with self.assertRaises(SystemExit):                 # branches with --continue
                fg.resolve_pair(_Args(cont=True, base="m", target="f"), self.REVIEW)
            with self.assertRaises(SystemExit):                 # --two-dot with --continue
                fg.resolve_pair(_Args(cont=True, two_dot=True), self.REVIEW)
            with self.assertRaises(SystemExit):                 # review lacks branch info
                fg.resolve_pair(_Args(cont=True), {"mode": "three-dot"})


# --------------------------------------------------------------------------- #
# HTML rendering (incl. the view filter)
# --------------------------------------------------------------------------- #
class TestRenderPage(unittest.TestCase):
    def _annotated(self, marks=None):
        d = doc(file_rec("acc.py", "acc.py", hunks=[hunk([line("add", "aaa")])]),
                file_rec("un.py", "un.py", hunks=[hunk([line("add", "bbb")])]))
        fg.annotate(d, marks or {})
        return d

    def _accepted_id(self):
        d = self._annotated()
        return next(h["review_id"] for f in d["files"] if f["new_path"] == "acc.py"
                    for h in f["hunks"])

    def test_no_filter(self):
        d = self._annotated()
        html = fg.render_page(d, {"marks": {}}, "main", "feat", False, None)
        self.assertIn("FLOODGATE_VISIBLE = null", html)
        self.assertNotIn("display:none", html)
        self.assertNotIn("showing:", html)
        self.assertIn("acc.py", html)
        self.assertIn("un.py", html)

    def test_hide_accepted(self):
        marks = {self._accepted_id(): {"status": "accepted", "path": "acc.py"}}
        d = self._annotated(marks)
        visible = fg.resolve_visible(None, "accepted")
        html = fg.render_page(d, {"marks": marks}, "main", "feat", False, visible)
        self.assertIn('FLOODGATE_VISIBLE = ["rejected", "skipped", "unreviewed"]', html)
        self.assertIn("showing: rejected, skipped, unreviewed", html)
        self.assertIn('data-status="accepted" style="display:none"', html)   # hidden
        self.assertIn('data-status="unreviewed">', html)                     # still shown
        self.assertIn('<b id="cnt-accepted">1</b>', html)                    # full counts kept

    def test_all_hidden_note(self):
        ids = [h["review_id"] for f in self._annotated()["files"] for h in f["hunks"]]
        marks = {i: {"status": "accepted", "path": "x"} for i in ids}
        d = self._annotated(marks)
        html = fg.render_page(d, {"marks": marks}, "m", "f", False,
                              fg.resolve_visible(None, "accepted"))
        self.assertIn("are hidden by the current filter", html)

    def test_escapes_content(self):
        d = doc(file_rec("a", "a", hunks=[hunk([line("add", "<script>x</script>")])]))
        fg.annotate(d, {})
        html = fg.render_page(d, {"marks": {}}, "m", "f", False, None)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>x</script>", html)


# --------------------------------------------------------------------------- #
# .review load / save
# --------------------------------------------------------------------------- #
class TestReviewIO(unittest.TestCase):
    def test_roundtrip_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".review"
            review = {"schema": fg.SCHEMA, "marks": {"x": {"status": "accepted"}}}
            fg.save_review(p, review)
            self.assertEqual(fg.load_review(p), review)
            self.assertIsNone(fg.load_review(Path(d) / "absent"))


# --------------------------------------------------------------------------- #
# CLI integration (needs git + diffkit's structured-diff)
# --------------------------------------------------------------------------- #
@unittest.skipUnless(shutil.which("git") and (DIFFKIT / "structured-diff").exists(),
                     "needs git and diffkit")
class TestCli(unittest.TestCase):
    def _env(self):
        env = dict(os.environ)
        env["PATH"] = str(DIFFKIT) + os.pathsep + env.get("PATH", "")
        return env

    def _fg(self, args, cwd, stdin=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd,
                              env=self._env(), input=stdin, text=True,
                              stdout=PIPE, stderr=PIPE)

    def _repo(self, with_review=True):
        d = tempfile.mkdtemp(prefix="fg-test-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        g = lambda *a: subprocess.run(["git", "-C", d, *a], check=True,
                                      stdout=PIPE, stderr=PIPE)
        g("init", "-q")
        g("config", "user.email", "t@t.t")
        g("config", "user.name", "t")
        (Path(d) / "f.txt").write_text("a\n")
        g("add", "f.txt")
        g("commit", "-qm", "init")
        g("switch", "-qc", "feat")
        (Path(d) / "f.txt").write_text("a\nNEW\n")
        g("add", "f.txt")
        g("commit", "-qm", "change")
        if with_review:
            rev = lambda r: subprocess.run(["git", "-C", d, "rev-parse", r],
                                           text=True, stdout=PIPE).stdout.strip()
            review = {"schema": fg.SCHEMA, "created": "t", "updated": "t",
                      "base": {"rev": "master", "commit": rev("master")},
                      "target": {"rev": "feat", "commit": rev("feat")},
                      "merge_base": rev("master"), "mode": "three-dot", "marks": {}}
            (Path(d) / ".review").write_text(json.dumps(review))
        return d

    def test_diff_accept_status(self):
        d = self._repo()
        diff = self._fg(["diff"], d)
        self.assertEqual(diff.returncode, 0, diff.stderr)
        self.assertIn("review_id", diff.stdout)
        acc = self._fg(["accept"], d, stdin=diff.stdout)
        self.assertEqual(acc.returncode, 0, acc.stderr)
        marks = json.loads((Path(d) / ".review").read_text())["marks"]
        self.assertTrue(marks and all(v["status"] == "accepted" for v in marks.values()))
        status = self._fg(["status"], d)
        self.assertIn("accepted   : 1", status.stdout)

    def test_diff_without_review_errors(self):
        d = self._repo(with_review=False)
        r = self._fg(["diff"], d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no .review", r.stderr)

    def test_accept_rejects_input_without_ids(self):
        d = self._repo()
        raw = subprocess.run([sys.executable, str(DIFFKIT / "structured-diff"),
                              "-C", d, "master...feat"], text=True, stdout=PIPE).stdout
        r = self._fg(["accept"], d, stdin=raw)        # raw diff has no review_id
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no review_id", r.stderr)

    def test_review_validates_filter_flag(self):
        # --only with a bad status dies before serving (no server to hang on).
        r = self._fg(["review", "master", "feat", "--only", "bogus", "--no-open"], self._repo())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown status", r.stderr)

    def test_continue_without_review_errors(self):
        # --continue with no .review dies before serving.
        r = self._fg(["review", "--continue", "--no-open"], self._repo(with_review=False))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("to continue", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
