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

    def test_unknown_scion_errors(self):
        r = self._scion("show", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no scion named", r.stderr)


if __name__ == "__main__":
    unittest.main()
