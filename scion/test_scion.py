#!/usr/bin/env python3
"""Tests for scion. Stdlib unittest only — no third-party packages.

    python3 test_scion.py        # or: python3 -m unittest -v

Pure helpers are tested by importing the script as a module; the rest drive the
CLI through a real temporary git repo (skipped when git isn't available).
"""

import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "scion"
PIPE = subprocess.PIPE
HAVE_GIT = shutil.which("git") is not None


def _load():
    loader = importlib.machinery.SourceFileLoader("scion_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


sc = _load()


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
class TestPureHelpers(unittest.TestCase):
    def test_valid_name(self):
        self.assertTrue(sc.valid_name("my-scion_1"))
        self.assertFalse(sc.valid_name("-bad"))
        self.assertFalse(sc.valid_name("a/b"))
        self.assertFalse(sc.valid_name(""))

    def test_find_range(self):
        ranges = [{"name": "a"}, {"name": "b"}]
        self.assertEqual(sc.find_range(ranges, "b"), 1)
        self.assertIsNone(sc.find_range(ranges, "z"))

    def test_healthy_through(self):
        rows = lambda *bs: [{"boundary_ok": b} for b in bs]
        self.assertEqual(sc.healthy_through(rows(True, True)), 1)
        self.assertEqual(sc.healthy_through(rows(True, False, True)), 0)
        self.assertEqual(sc.healthy_through([]), -1)


# --------------------------------------------------------------------------- #
# integration: a real git repo + the CLI
# --------------------------------------------------------------------------- #
@unittest.skipUnless(HAVE_GIT, "git not available")
class TestCLI(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        self.commits = [self._commit(f"c{i}") for i in range(5)]
        self.branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        r = self._scion("new", "s")
        self.assertEqual(r.returncode, 0, r.stderr)

    def _git(self, *args):
        res = subprocess.run(["git", "-C", str(self.dir), *args],
                             text=True, stdout=PIPE, stderr=PIPE)
        if res.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {res.stderr}")
        return res.stdout.strip()

    def _commit(self, msg):
        (self.dir / "f").write_text(msg)
        self._git("add", ".")
        self._git("commit", "-q", "-m", msg)
        return self._git("rev-parse", "HEAD")

    def _scion(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              cwd=str(self.dir), text=True, stdout=PIPE, stderr=PIPE)

    def _data(self, name):
        return json.loads((self.dir / ".scions" / f"{name}.json").read_text())

    def test_mark_builds_file(self):
        r = self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._scion("mark", "s", "12982", "--type", "essence",
                        "--tip", self.commits[3], "--branch", "feat")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = self._data("s")
        self.assertEqual([x["name"] for x in data["ranges"]], ["base", "12982"])
        ess = data["ranges"][1]
        self.assertEqual(ess["base"], self.commits[1])  # auto-filled from the top tip
        self.assertEqual(ess["tip"], self.commits[3])
        self.assertEqual(len(ess["tip"]), 40)           # stored in full
        self.assertNotIn("base", data["ranges"][0])     # first range roots at the root

    def test_mark_inserts_out_of_order_and_splits(self):
        # Mark the ends first, then drop a range into the middle by its tip alone.
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "top", "--type", "essence", "--tip", self.commits[3])
        r = self._scion("mark", "s", "mid", "--type", "substrate", "--tip", self.commits[2])
        self.assertEqual(r.returncode, 0, r.stderr)
        data = self._data("s")
        self.assertEqual([x["name"] for x in data["ranges"]], ["base", "mid", "top"])
        mid = data["ranges"][1]
        self.assertEqual(mid["base"], self.commits[1])   # inherits the split range's base
        self.assertEqual(mid["tip"], self.commits[2])
        # the succeeding range's base was bumped to the new tip, so it stays consecutive
        self.assertEqual(data["ranges"][2]["base"], self.commits[2])
        self.assertEqual(self._scion("health", "s").returncode, 0)

    def test_mark_add_rejected_when_unhealthy(self):
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "ess", "--type", "essence", "--tip", self.commits[3])
        self._scion("mark", "s", "base", "--tip", self.commits[2])  # update → boundary breaks
        r = self._scion("mark", "s", "extra", "--type", "substrate", "--tip", self.commits[4])
        self.assertEqual(r.returncode, 1)
        self.assertIn("unhealthy", r.stderr)

    def test_mark_rejects_existing_boundary(self):
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "top", "--type", "essence", "--tip", self.commits[3])
        r = self._scion("mark", "s", "dup", "--type", "substrate", "--tip", self.commits[1])
        self.assertEqual(r.returncode, 1)
        self.assertIn("already", r.stderr)

    def test_mark_base_crosscheck_mismatch(self):
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "top", "--type", "essence", "--tip", self.commits[3])
        # mid splits 'top' (base should be commits[1]); a wrong --base is rejected
        r = self._scion("mark", "s", "mid", "--type", "substrate",
                        "--base", self.commits[0], "--tip", self.commits[2])
        self.assertEqual(r.returncode, 1)
        self.assertIn("doesn't fit", r.stderr)

    def test_show_and_health_when_healthy(self):
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "ess", "--type", "essence", "--tip", self.commits[3])
        h = self._scion("health", "s")
        self.assertEqual(h.returncode, 0, h.stderr)
        self.assertIn("healthy", h.stdout)
        s = self._scion("show", "s")
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertIn("base", s.stdout)
        self.assertIn("ess", s.stdout)
        self.assertIn("commit", s.stdout)

    def test_health_flags_boundary_mismatch(self):
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "ess", "--type", "essence",
                    "--base", self.commits[1], "--tip", self.commits[3])
        self._scion("mark", "s", "base", "--tip", self.commits[2])  # base tip now ≠ ess.base
        h = self._scion("health", "s")
        self.assertEqual(h.returncode, 1)
        self.assertIn("ess", h.stdout)
        self.assertIn("previous range", h.stdout)

    def test_branch_drift(self):
        self._git("branch", "feat", self.commits[2])
        self._scion("mark", "s", "ess", "--type", "essence",
                    "--tip", self.commits[2], "--branch", "feat")
        self.assertEqual(self._scion("health", "s").returncode, 0)
        self._git("branch", "-f", "feat", self.commits[3])  # move it off the tip
        h = self._scion("health", "s")
        self.assertEqual(h.returncode, 1)
        self.assertIn("drifted", h.stdout)

    def test_unmark(self):
        self._scion("mark", "s", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "s", "ess", "--type", "essence", "--tip", self.commits[3])
        r = self._scion("unmark", "s", "ess")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x["name"] for x in self._data("s")["ranges"]], ["base"])

    def test_new_creates_and_mark_requires_existing(self):
        r = self._scion("new", "fresh", "-m", "about it")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = self._data("fresh")
        self.assertEqual(data["description"], "about it")
        self.assertEqual(data["ranges"], [])
        self.assertEqual(self._scion("new", "fresh").returncode, 1)  # no clobber
        # mark on a missing scion errors — no implicit create
        r = self._scion("mark", "ghost", "base", "--type", "substrate", "--tip", self.commits[1])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no scion named", r.stderr)

    def test_ls(self):
        self._scion("new", "alpha", "-m", "first one")
        self._scion("mark", "alpha", "base", "--type", "substrate", "--tip", self.commits[1])
        r = self._scion("ls")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha", r.stdout)
        self.assertIn("first one", r.stdout)
        self.assertIn("1 range", r.stdout)   # alpha has one range
        self.assertIn("0 ranges", r.stdout)  # the empty "s" from setUp

    def test_apply_dry_run_plan(self):
        self._scion("new", "tgt")
        self._scion("mark", "tgt", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "tgt", "X", "--type", "essence", "--tip", self.commits[2])
        self._scion("mark", "tgt", "gen", "--type", "computed",
                    "--tip", self.commits[3], "--command", "echo hi")
        self._scion("new", "src")
        self._scion("mark", "src", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "src", "X", "--type", "essence", "--tip", self.commits[4])
        r = self._scion("apply", "src", "tgt", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fast-forward", r.stdout)  # source's X is ahead of target's X
        self.assertIn("regenerate", r.stdout)    # so the computed range rebuilds

    def test_apply_name_mismatch_errors(self):
        self._scion("new", "a")
        self._scion("mark", "a", "X", "--type", "essence", "--tip", self.commits[2])
        self._scion("new", "b")
        self._scion("mark", "b", "Y", "--type", "essence", "--tip", self.commits[2])
        r = self._scion("apply", "a", "b", "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("essence names", r.stderr)

    def test_unknown_scion_errors(self):
        r = self._scion("show", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no scion named", r.stderr)

    # ----- apply execution (one step per invocation) ----------------------- #
    def _apply_state_exists(self):
        return (self.dir / ".scions" / ".apply.json").exists()

    def test_apply_runs_clean_to_completion(self):
        # target: base, an essence X behind source's, and a computed range that
        # rebuilds once X moves. Source fast-forwards X, so X ff's and gen reruns.
        self._scion("new", "tgt")
        self._scion("mark", "tgt", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "tgt", "X", "--type", "essence", "--tip", self.commits[2])
        self._scion("mark", "tgt", "gen", "--type", "computed", "--tip", self.commits[3],
                    "--command", "echo z >> f && git add f && git commit -q -m gen")
        self._scion("new", "src")
        self._scion("mark", "src", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "src", "X", "--type", "essence", "--tip", self.commits[4])

        r = self._scion("apply", "src", "tgt")  # start: records the plan, no step yet
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._apply_state_exists())

        last = None
        for _ in range(6):  # base (keep) → X (ff) → gen (regen): three continues
            last = self._scion("apply", "--continue")
            self.assertEqual(last.returncode, 0, last.stderr)
            if "complete" in last.stdout:
                break
        self.assertIn("complete", last.stdout)
        self.assertFalse(self._apply_state_exists())               # state cleared
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD"), self.branch)

        data = self._data("tgt")
        x = next(r for r in data["ranges"] if r["name"] == "X")
        self.assertEqual(x["tip"], self.commits[4])                # X fast-forwarded
        gen = next(r for r in data["ranges"] if r["name"] == "gen")
        self.assertEqual(gen["base"], self.commits[4])             # rebuilt on the new X
        self.assertNotEqual(gen["tip"], self.commits[3])           # and regenerated

    def test_apply_conflict_then_resume(self):
        # Construct a guaranteed conflict: source rewrites essence X's line, then
        # target's upper substrate (which edits the same line) replays onto it.
        def commit(msg, content):
            (self.dir / "g").write_text(content)
            self._git("add", "g")
            self._git("commit", "-q", "-m", msg)
            return self._git("rev-parse", "HEAD")

        c0 = commit("g0", "hello\n")
        cx = commit("gX", "hello-X\n")          # target's essence X
        cc = commit("gcollab", "hello-X-collab\n")  # target's upper substrate
        self._git("checkout", "-q", c0)
        sx = commit("gsrc", "hello-SRC\n")      # source's essence X, diverged from cx
        self._git("checkout", "-q", self.branch)

        self._scion("new", "tgt")
        self._scion("mark", "tgt", "base", "--type", "substrate", "--tip", c0)
        self._scion("mark", "tgt", "X", "--type", "essence", "--tip", cx)
        self._scion("mark", "tgt", "collab", "--type", "substrate", "--tip", cc)
        self._scion("new", "src")
        self._scion("mark", "src", "base", "--type", "substrate", "--tip", c0)
        self._scion("mark", "src", "X", "--type", "essence", "--tip", sx)

        self.assertEqual(self._scion("apply", "src", "tgt").returncode, 0)
        self.assertEqual(self._scion("apply", "--continue").returncode, 0)  # base keep
        self.assertEqual(self._scion("apply", "--continue").returncode, 0)  # X clean
        conflict = self._scion("apply", "--continue")                       # collab → conflict
        self.assertEqual(conflict.returncode, 1)
        self.assertIn("conflict", (conflict.stdout + conflict.stderr).lower())
        self.assertTrue(self._apply_state_exists())                # paused, not lost

        # resolve by hand, then continue — the cherry-pick finishes and apply ends
        (self.dir / "g").write_text("resolved\n")
        self._git("add", "g")
        done = self._scion("apply", "--continue")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("complete", done.stdout)
        self.assertFalse(self._apply_state_exists())
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD"), self.branch)
        # the resolved content is what landed on the rebuilt collab tip
        collab_tip = next(r for r in self._data("tgt")["ranges"] if r["name"] == "collab")["tip"]
        self.assertEqual(self._git("show", f"{collab_tip}:g"), "resolved")

    def test_apply_abort_restores_checkout(self):
        self._scion("new", "tgt")
        self._scion("mark", "tgt", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "tgt", "X", "--type", "essence", "--tip", self.commits[2])
        self._scion("new", "src")
        self._scion("mark", "src", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "src", "X", "--type", "essence", "--tip", self.commits[4])

        self._scion("apply", "src", "tgt")           # start
        self._scion("apply", "--continue")           # base keep → detaches HEAD
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD"), "HEAD")  # detached
        r = self._scion("apply", "--abort")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD"), self.branch)
        self.assertFalse(self._apply_state_exists())
        x = next(r for r in self._data("tgt")["ranges"] if r["name"] == "X")
        self.assertEqual(x["tip"], self.commits[2])  # target left untouched

    def test_apply_by_hand_overrides_action(self):
        self._scion("new", "tgt")
        self._scion("mark", "tgt", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "tgt", "X", "--type", "essence", "--tip", self.commits[2])
        self._scion("new", "src")
        self._scion("mark", "src", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "src", "X", "--type", "essence", "--tip", self.commits[4])
        self.assertEqual(self._scion("apply", "src", "tgt").returncode, 0)

        refused = self._scion("apply", "--by-hand")        # the base is a keep
        self.assertEqual(refused.returncode, 1)
        self.assertIn("nothing to do by hand", refused.stderr)

        self.assertEqual(self._scion("apply", "--continue").returncode, 0)  # base

        setup = self._scion("apply", "--by-hand")          # take X over rather than ff
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.assertIn("by hand", setup.stdout)
        self.assertEqual(self._git("rev-parse", "refs/scion/tgt/new"), self.commits[4])

        (self.dir / "m").write_text("manual result")       # build something of my own
        self._git("add", "m")
        self._git("commit", "-q", "-m", "manual")
        custom = self._git("rev-parse", "HEAD")

        done = self._scion("apply", "--continue")          # record HEAD as X's tip
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("complete", done.stdout)
        x = next(r for r in self._data("tgt")["ranges"] if r["name"] == "X")
        self.assertEqual(x["tip"], custom)                 # mine, not source's commits[4]
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD"), self.branch)

    def test_apply_continue_without_start_errors(self):
        r = self._scion("apply", "--continue")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no apply in progress", r.stderr)

    def test_apply_ignores_untracked_files(self):
        self._scion("new", "tgt")
        self._scion("mark", "tgt", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "tgt", "X", "--type", "essence", "--tip", self.commits[2])
        self._scion("new", "src")
        self._scion("mark", "src", "base", "--type", "substrate", "--tip", self.commits[1])
        self._scion("mark", "src", "X", "--type", "essence", "--tip", self.commits[4])
        (self.dir / "scratch.txt").write_text("untracked, should not block apply")
        r = self._scion("apply", "src", "tgt")   # an untracked file is present
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._apply_state_exists())


if __name__ == "__main__":
    unittest.main()
