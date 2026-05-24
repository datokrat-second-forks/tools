#!/usr/bin/env python3
"""Tests for the diffkit tools (structured-diff, filter-diff, render-diff).

Stdlib unittest only — no third-party packages, matching the tools themselves.

    python3 test_diffkit.py            # or: python3 -m unittest -v

The parser (_diffcommon.parse_git_diff) is tested by importing it directly; the
three CLI tools are tested as black boxes (run via `sys.executable <script>`),
so arg parsing and the file-dropping logic are exercised for real. The
structured-diff tests build a throwaway git repo and are skipped without `git`.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_diffcommon():
    spec = importlib.util.spec_from_file_location("_diffcommon", HERE / "_diffcommon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dc = _load_diffcommon()


def run_tool(name, args, stdin):
    """Run a diffkit script with stdin, returning the CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(HERE / name), *args],
        input=stdin if isinstance(stdin, str) else json.dumps(stdin),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def filtered(args, doc):
    """Run filter-diff and return the parsed output document."""
    res = run_tool("filter-diff", args, doc)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def paths(doc):
    return {f["new_path"] or f["old_path"] for f in doc["files"]}


# --------------------------------------------------------------------------- #
# helpers to build schema docs without going through the parser
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
    return {"schema": dc.SCHEMA, "old": "a", "new": "b", "files": list(files)}


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
class TestParser(unittest.TestCase):
    def test_modified_single_hunk(self):
        text = (
            "diff --git a/foo.txt b/foo.txt\n"
            "index e69de29..d95f3ad 100644\n"
            "--- a/foo.txt\n"
            "+++ b/foo.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+LINE2\n"
            " line3\n"
        )
        files = dc.parse_git_diff(text)
        self.assertEqual(len(files), 1)
        f = files[0]
        self.assertEqual(f["status"], "modified")
        self.assertEqual((f["old_path"], f["new_path"]), ("foo.txt", "foo.txt"))
        kinds = [ln["kind"] for ln in f["hunks"][0]["lines"]]
        self.assertEqual(kinds, ["context", "del", "add", "context"])
        del_line = f["hunks"][0]["lines"][1]
        add_line = f["hunks"][0]["lines"][2]
        self.assertEqual((del_line["text"], del_line["old_lineno"]), ("line2", 2))
        self.assertEqual((add_line["text"], add_line["new_lineno"]), ("LINE2", 2))

    def test_added_file(self):
        text = (
            "diff --git a/new.txt b/new.txt\n"
            "new file mode 100644\n"
            "index 0000000..3b18e51\n"
            "--- /dev/null\n"
            "+++ b/new.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world\n"
        )
        f = dc.parse_git_diff(text)[0]
        self.assertEqual(f["status"], "added")
        self.assertIsNone(f["old_path"])
        self.assertEqual(f["new_path"], "new.txt")
        self.assertTrue(all(ln["kind"] == "add" for ln in f["hunks"][0]["lines"]))

    def test_deleted_file(self):
        text = (
            "diff --git a/gone.txt b/gone.txt\n"
            "deleted file mode 100644\n"
            "index 3b18e51..0000000\n"
            "--- a/gone.txt\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-hello\n"
            "-world\n"
        )
        f = dc.parse_git_diff(text)[0]
        self.assertEqual(f["status"], "deleted")
        self.assertEqual(f["old_path"], "gone.txt")
        self.assertIsNone(f["new_path"])

    def test_rename_no_content_change(self):
        text = (
            "diff --git a/old.txt b/new.txt\n"
            "similarity index 100%\n"
            "rename from old.txt\n"
            "rename to new.txt\n"
        )
        f = dc.parse_git_diff(text)[0]
        self.assertEqual(f["status"], "renamed")
        self.assertEqual((f["old_path"], f["new_path"]), ("old.txt", "new.txt"))
        self.assertEqual(f["similarity"], 100)
        self.assertEqual(f["hunks"], [])

    def test_mode_change(self):
        text = (
            "diff --git a/s.sh b/s.sh\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        f = dc.parse_git_diff(text)[0]
        self.assertEqual(f["status"], "mode")
        self.assertEqual((f["old_mode"], f["new_mode"]), ("100644", "100755"))

    def test_no_newline_at_eof(self):
        text = (
            "diff --git a/n.txt b/n.txt\n"
            "index 111..222 100644\n"
            "--- a/n.txt\n"
            "+++ b/n.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        lines = dc.parse_git_diff(text)[0]["hunks"][0]["lines"]
        self.assertTrue(lines[0].get("no_newline"))   # the "-old" line
        self.assertTrue(lines[1].get("no_newline"))   # the "+new" line

    def test_binary_added(self):
        text = (
            "diff --git a/img.png b/img.png\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
            "Binary files /dev/null and b/img.png differ\n"
        )
        f = dc.parse_git_diff(text)[0]
        self.assertTrue(f["binary"])
        self.assertEqual(f["status"], "added")
        self.assertEqual(f["new_path"], "img.png")

    def test_multiple_files(self):
        text = (
            "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/y b/y\n--- a/y\n+++ b/y\n@@ -1 +1 @@\n-c\n+d\n"
        )
        files = dc.parse_git_diff(text)
        self.assertEqual([f["new_path"] for f in files], ["x", "y"])

    def test_count_changes(self):
        d = doc(file_rec("x", "x", hunks=[hunk([
            line("context", "k"), line("add", "1"), line("add", "2"), line("del", "3")])]))
        self.assertEqual(dc.count_changes(d), (1, 2, 1))


# --------------------------------------------------------------------------- #
# filter-diff
#
# Defaults: literal string, whole-line, whitespace-trimmed, keep matches.
# Opt out with -E/--regexp, --substring, --no-trim, -v/--exclude.
# --------------------------------------------------------------------------- #
def sample_doc():
    """a.txt (two adds), a rename, and c.txt (one add) -- for the dropping rules.

    Lines are exact so the default whole-line literal match applies cleanly.
    """
    return doc(
        file_rec("a.txt", "a.txt", hunks=[hunk([
            line("context", "x", 1, 1),
            line("add", "DROP", None, 2),
            line("add", "keep", None, 3),
            line("context", "y", 2, 4),
        ])]),
        file_rec("old.txt", "new.txt", status="renamed", similarity=100),
        file_rec("c.txt", "c.txt", hunks=[hunk([line("add", "DROP", None, 1)])]),
    )


class TestFilterDiff(unittest.TestCase):
    # ---- defaults: literal, whole-line, whitespace-trimmed ----
    def test_whole_line_literal_default(self):
        out = filtered(["DROP"], sample_doc())
        self.assertEqual(paths(out), {"a.txt", "c.txt"})
        a = next(f for f in out["files"] if f["new_path"] == "a.txt")
        self.assertEqual([ln["text"] for ln in a["hunks"][0]["lines"]],
                         ["x", "DROP", "y"])          # "keep" dropped

    def test_exclude(self):
        out = filtered(["-v", "DROP"], sample_doc())
        a = next(f for f in out["files"] if f["new_path"] == "a.txt")
        self.assertEqual([ln["text"] for ln in a["hunks"][0]["lines"]],
                         ["x", "keep", "y"])          # "DROP" dropped
        self.assertNotIn("c.txt", paths(out))         # its only line was DROP

    def test_whole_line_rejects_partial(self):
        d = doc(file_rec("f", "f", hunks=[hunk([line("add", "has DROP here")])]))
        self.assertEqual(filtered(["DROP"], d)["files"], [])            # not the whole line
        self.assertEqual(paths(filtered(["--substring", "DROP"], d)), {"f"})

    def test_literal_by_default(self):
        d = doc(file_rec("f", "f", hunks=[hunk([line("add", "a.b")])]))
        self.assertEqual(paths(filtered(["a.b"], d)), {"f"})            # literal dot
        self.assertEqual(filtered(["axb"], d)["files"], [])             # not a regex
        self.assertEqual(paths(filtered(["-E", "a.b"], d)), {"f"})      # regex dot matches

    def test_regexp(self):
        d = doc(file_rec("f", "f", hunks=[hunk([line("add", "x abc123 y")])]))
        self.assertEqual(filtered(["-E", r"\d+"], d)["files"], [])      # fullmatch fails
        self.assertEqual(paths(filtered(["-E", "--substring", r"\d+"], d)), {"f"})

    def test_ignore_case(self):
        d = doc(file_rec("f", "f", hunks=[hunk([line("add", "todo")])]))
        self.assertEqual(filtered(["TODO"], d)["files"], [])
        self.assertEqual(paths(filtered(["-i", "TODO"], d)), {"f"})

    def test_trim_on_by_default(self):
        d = doc(file_rec("f", "f", hunks=[hunk([line("add", "   DROP   ")])]))
        self.assertEqual(paths(filtered(["DROP"], d)), {"f"})           # whitespace ignored
        self.assertEqual(filtered(["--no-trim", "DROP"], d)["files"], [])
        self.assertEqual(paths(filtered(["--no-trim", "   DROP   "], d)), {"f"})

    def test_side_selection(self):
        # Only the chosen side is tested; the other side's lines are retained.
        def units(args):
            out = filtered(args, doc(file_rec("f", "f", hunks=[hunk([
                line("del", "X", 1), line("add", "X", None, 1)])])))
            return [(ln["kind"], ln["text"]) for f in out["files"]
                    for h in f["hunks"] for ln in h["lines"]]
        self.assertEqual(units(["-v", "--side", "removed", "X"]), [("add", "X")])
        self.assertEqual(units(["-v", "--side", "added", "X"]), [("del", "X")])
        self.assertEqual(units(["-v", "--side", "both", "X"]), [])      # both dropped

    def test_recount_matches_kept_lines(self):
        out = filtered(["DROP"], sample_doc())
        h = next(f for f in out["files"] if f["new_path"] == "a.txt")["hunks"][0]
        # kept: context x, add DROP, context y  ->  old=2 (contexts), new=3
        self.assertEqual((h["old_count"], h["new_count"]), (2, 3))

    # ---- structural-only (rename) disposition: counts as non-matching ----
    def test_rename_dropped_when_keeping_matches(self):
        self.assertNotIn("new.txt", paths(filtered(["DROP"], sample_doc())))

    def test_rename_kept_when_excluding(self):
        self.assertIn("new.txt", paths(filtered(["-v", "DROP"], sample_doc())))

    def test_rename_kept_with_keep_empty_files(self):
        out = filtered(["DROP", "--keep-empty-files"], sample_doc())
        self.assertIn("new.txt", paths(out))

    def test_rename_dropped_when_nothing_matches(self):
        self.assertEqual(filtered(["NOPE"], sample_doc())["files"], [])

    # ---- the property floodgate relies on: extra keys survive ----
    def test_extra_keys_pass_through(self):
        d = doc(
            file_rec("a.txt", "a.txt", review_id="FILE1", hunks=[
                hunk([line("add", "content")], review_id="HUNK1")]),
            file_rec("old", "new", status="renamed", review_id="RENAME1"),
        )
        out = filtered(["-v", "NOPE"], d)   # exclude a non-match -> everything kept
        a = next(f for f in out["files"] if f["new_path"] == "a.txt")
        self.assertEqual(a["review_id"], "FILE1")
        self.assertEqual(a["hunks"][0]["review_id"], "HUNK1")
        ren = next(f for f in out["files"] if f["new_path"] == "new")
        self.assertEqual(ren["review_id"], "RENAME1")


# --------------------------------------------------------------------------- #
# render-diff
# --------------------------------------------------------------------------- #
class TestRenderDiff(unittest.TestCase):
    def test_renders_and_escapes(self):
        d = doc(file_rec("src/a.py", "src/a.py", hunks=[hunk([
            line("del", "old", 1), line("add", "<script>evil</script>", None, 1)])]))
        res = run_tool("render-diff", [], d)
        self.assertEqual(res.returncode, 0, res.stderr)
        html = res.stdout
        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("src/a.py", html)
        self.assertIn("b-modified", html)
        self.assertIn("&lt;script&gt;", html)      # escaped
        self.assertNotIn("<script>evil", html)      # not raw

    def test_empty_doc(self):
        res = run_tool("render-diff", [], doc())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("No changes", res.stdout)


# --------------------------------------------------------------------------- #
# structured-diff (integration; needs git)
# --------------------------------------------------------------------------- #
@unittest.skipUnless(shutil.which("git"), "git not available")
class TestStructuredDiff(unittest.TestCase):
    def _repo(self):
        d = tempfile.mkdtemp(prefix="diffkit-test-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        run = lambda *a: subprocess.run(["git", "-C", d, *a], check=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        run("init", "-q")
        run("config", "user.email", "t@t.t")
        run("config", "user.name", "t")
        return d, run

    def test_modified_working_tree(self):
        d, run = self._repo()
        (Path(d) / "a.txt").write_text("1\n2\n3\n")
        run("add", "a.txt")
        run("commit", "-qm", "init")
        (Path(d) / "a.txt").write_text("1\nTWO\n3\n")
        res = run_tool("structured-diff", ["-C", d], "")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual(out["schema"], dc.SCHEMA)
        self.assertEqual(len(out["files"]), 1)
        f = out["files"][0]
        self.assertEqual(f["status"], "modified")
        self.assertEqual(f["new_path"], "a.txt")

    def test_detects_rename_against_commit(self):
        d, run = self._repo()
        (Path(d) / "a.txt").write_text("hello\nworld\ncontent\n")
        run("add", "a.txt")
        run("commit", "-qm", "init")
        run("mv", "a.txt", "b.txt")
        run("commit", "-qm", "rename")
        res = run_tool("structured-diff", ["-C", d, "HEAD~1", "HEAD"], "")
        self.assertEqual(res.returncode, 0, res.stderr)
        f = json.loads(res.stdout)["files"][0]
        self.assertEqual(f["status"], "renamed")
        self.assertEqual((f["old_path"], f["new_path"]), ("a.txt", "b.txt"))

    def test_pipeline_structured_then_filter(self):
        d, run = self._repo()
        (Path(d) / "a.txt").write_text("keep\n")
        run("add", "a.txt")
        run("commit", "-qm", "init")
        (Path(d) / "a.txt").write_text("keep\nDROP\nstay\n")
        sd = run_tool("structured-diff", ["-C", d], "")
        out = filtered(["DROP"], json.loads(sd.stdout))   # default whole-line literal
        texts = [ln["text"] for f in out["files"] for h in f["hunks"]
                 for ln in h["lines"] if ln["kind"] == "add"]
        self.assertEqual(texts, ["DROP"])   # "stay" filtered out


if __name__ == "__main__":
    unittest.main(verbosity=2)
