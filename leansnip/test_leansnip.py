#!/usr/bin/env python3
"""Tests for leansnip. Stdlib unittest only -- no third-party packages.

    python3 test_leansnip.py            # or: python3 -m unittest -v

Pure helpers (snippet add/remove, body normalization, link/unlink against a
temp dir, config + editor discovery via a redirected XDG_CONFIG_HOME) are
tested by importing the script as a module. A couple of integration tests drive
the CLI as a subprocess; the git-backed `sync` path is skipped when git is
absent.
"""

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "leansnip"
PIPE = subprocess.PIPE


def _load():
    loader = importlib.machinery.SourceFileLoader("leansnip_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ls = _load()


# --------------------------------------------------------------------------- #
# snippet model
# --------------------------------------------------------------------------- #
class TestSnippetModel(unittest.TestCase):
    def test_add_single_line_body_is_string(self):
        out = ls.add_snippet({}, "Sorry", "sry", ["sorry"], "placeholder")
        self.assertEqual(out["Sorry"]["body"], "sorry")
        self.assertEqual(out["Sorry"]["prefix"], "sry")
        self.assertEqual(out["Sorry"]["description"], "placeholder")

    def test_add_multi_line_body_is_list(self):
        out = ls.add_snippet({}, "Lemma", "lem", ["lemma $1 : $2 := by", "  $0"])
        self.assertEqual(out["Lemma"]["body"], ["lemma $1 : $2 := by", "  $0"])
        self.assertNotIn("description", out["Lemma"])  # omitted when empty

    def test_add_is_pure(self):
        original = {}
        ls.add_snippet(original, "A", "a", ["x"])
        self.assertEqual(original, {})  # input untouched

    def test_add_duplicate_name_raises(self):
        data = ls.add_snippet({}, "A", "a", ["x"])
        with self.assertRaises(ValueError):
            ls.add_snippet(data, "A", "b", ["y"])

    def test_empty_body_raises(self):
        with self.assertRaises(ValueError):
            ls.normalize_body([])

    def test_remove(self):
        data = ls.add_snippet({}, "A", "a", ["x"])
        out = ls.remove_snippet(data, "A")
        self.assertNotIn("A", out)
        self.assertIn("A", data)  # original untouched

    def test_remove_missing_raises(self):
        with self.assertRaises(KeyError):
            ls.remove_snippet({}, "nope")

    def test_body_lines_roundtrip(self):
        self.assertEqual(ls.body_lines("a\nb"), ["a", "b"])
        self.assertEqual(ls.body_lines(["a", "b"]), ["a", "b"])

    def test_describe_handles_list_prefix_and_malformed(self):
        self.assertEqual(ls.describe_snippet("N", {"prefix": ["a", "b"]}),
                         ("N", "a, b", ""))
        self.assertEqual(ls.describe_snippet("N", "oops")[2], "(malformed entry)")


# --------------------------------------------------------------------------- #
# read/write the file
# --------------------------------------------------------------------------- #
class TestFileIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(ls.read_snippets(self.repo), {})

    def test_write_then_read_roundtrip(self):
        data = ls.add_snippet({}, "A", "a", ["x", "y"], "d")
        ls.write_snippets(self.repo, data)
        self.assertEqual(ls.read_snippets(self.repo), data)
        # pretty-printed with a trailing newline
        self.assertTrue(ls.snippet_path(self.repo).read_text().endswith("}\n"))

    def test_invalid_json_raises(self):
        ls.snippet_path(self.repo).write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ls.SnippetFileError):
            ls.read_snippets(self.repo)

    def test_non_object_top_level_raises(self):
        ls.snippet_path(self.repo).write_text("[]", encoding="utf-8")
        with self.assertRaises(ls.SnippetFileError):
            ls.read_snippets(self.repo)

    def test_read_or_die_turns_bad_file_into_exit(self):
        ls.snippet_path(self.repo).write_text("{ nope", encoding="utf-8")
        with self.assertRaises(SystemExit):
            ls.read_snippets_or_die(self.repo)


# --------------------------------------------------------------------------- #
# linking against a fake editor snippets dir
# --------------------------------------------------------------------------- #
class TestLinking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        ls.write_snippets(self.repo, {})
        self.sdir = base / "User" / "snippets"

    def tearDown(self):
        self.tmp.cleanup()

    def target(self):
        return self.sdir / ls.SNIPPET_FILE

    def test_link_creates_symlink(self):
        self.assertEqual(ls.link_one(self.repo, self.sdir), "linked")
        self.assertTrue(self.target().is_symlink())
        self.assertEqual(self.target().resolve(), ls.snippet_path(self.repo).resolve())
        self.assertEqual(ls.link_state(self.repo, self.sdir), "linked")

    def test_link_is_idempotent(self):
        ls.link_one(self.repo, self.sdir)
        self.assertEqual(ls.link_one(self.repo, self.sdir), "already linked")

    def test_link_backs_up_real_file(self):
        self.sdir.mkdir(parents=True)
        self.target().write_text('{"Old": {}}', encoding="utf-8")
        result = ls.link_one(self.repo, self.sdir)
        self.assertIn("backed up", result)
        self.assertTrue(self.target().is_symlink())
        baks = list(self.sdir.glob(ls.SNIPPET_FILE + ".bak.*"))
        self.assertEqual(len(baks), 1)
        self.assertIn("Old", baks[0].read_text())

    def test_relink_replaces_foreign_symlink(self):
        self.sdir.mkdir(parents=True)
        other = Path(self.tmp.name) / "other.json"
        other.write_text("{}", encoding="utf-8")
        os.symlink(other, self.target())
        self.assertIn("relinked", ls.link_one(self.repo, self.sdir))
        self.assertEqual(self.target().resolve(), ls.snippet_path(self.repo).resolve())

    def test_unlink_only_removes_symlinks(self):
        ls.link_one(self.repo, self.sdir)
        self.assertEqual(ls.unlink_one(self.sdir), "unlinked")
        self.assertFalse(self.target().exists())

    def test_unlink_leaves_real_file(self):
        self.sdir.mkdir(parents=True)
        self.target().write_text("{}", encoding="utf-8")
        self.assertIn("left in place", ls.unlink_one(self.sdir))
        self.assertTrue(self.target().exists())


# --------------------------------------------------------------------------- #
# config + editor discovery (redirect HOME into a temp dir; our config lives at
# ~/.tools/leansnip/ like tmgr, while editor discovery falls back to ~/.config)
# --------------------------------------------------------------------------- #
class TestConfigAndDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME")}
        os.environ["HOME"] = str(self.home)
        os.environ.pop("XDG_CONFIG_HOME", None)  # discovery -> ~/.config

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_config_roundtrip(self):
        self.assertEqual(ls.load_config(), {})
        ls.save_config({"repo": "/x"})
        self.assertEqual(ls.load_config()["repo"], "/x")
        # stored under ~/.tools/leansnip/, matching tmgr's convention
        self.assertTrue((self.home / ".tools" / "leansnip" / "config").exists())

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "discovery layout is platform-specific")
    def test_detects_installed_editor_only(self):
        # Code is "installed" (has a User dir under ~/.config); Cursor is not.
        cfg = self.home / ".config"
        (cfg / "Code" / "User").mkdir(parents=True)
        labels = {label for label, _ in ls.detected_snippet_dirs()}
        self.assertEqual(labels, {"VS Code"})
        sdirs = dict(ls.detected_snippet_dirs())
        self.assertEqual(sdirs["VS Code"], cfg / "Code" / "User" / "snippets")

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "discovery layout is platform-specific")
    def test_detects_code_server_under_data_root(self):
        # code-server lives under ~/.local/share, not ~/.config.
        cs = self.home / ".local" / "share" / "code-server" / "User"
        cs.mkdir(parents=True)
        sdirs = dict(ls.detected_snippet_dirs())
        self.assertIn("code-server", sdirs)
        self.assertEqual(sdirs["code-server"], cs / "snippets")

    def test_effective_targets_unions_and_dedupes(self):
        # A registered custom target shows up; one that duplicates a detected
        # editor does not appear twice.
        cfg = self.home / ".config"
        (cfg / "Code" / "User").mkdir(parents=True)
        detected = cfg / "Code" / "User" / "snippets"
        custom = self.home / "mnt" / "User" / "snippets"
        ls.save_config({"repo": "/x", "targets": [str(custom), str(detected)]})
        args = argparse.Namespace(dir=None)
        result = ls.effective_targets(args)
        self.assertIn(("VS Code", detected), result)
        self.assertIn(("(custom)", custom), result)
        # detected path registered as a target too -> still only once
        self.assertEqual(len(result), 2)

    def test_dir_overrides_everything(self):
        (self.home / ".config" / "Code" / "User").mkdir(parents=True)
        ls.save_config({"targets": ["/some/custom/dir"]})
        args = argparse.Namespace(dir="/only/this")
        self.assertEqual(ls.effective_targets(args),
                         [("(--dir)", Path("/only/this"))])


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.env = dict(os.environ)
        self.env["LEANSNIP_REPO"] = str(self.repo)
        self.env["HOME"] = str(Path(self.tmp.name) / "home")  # isolate config

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              text=True, input=stdin, stdout=PIPE, stderr=PIPE,
                              env=self.env)

    def test_add_via_flags_then_ls_and_rm(self):
        r = self.run_cli("add", "Sorry", "--prefix", "sry", "--body", "sorry",
                         "--desc", "leave a hole")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(ls.snippet_path(self.repo).read_text())
        self.assertEqual(data["Sorry"], {"prefix": "sry", "body": "sorry",
                                         "description": "leave a hole"})
        r = self.run_cli("ls")
        self.assertIn("Sorry", r.stdout)
        self.assertIn("sry", r.stdout)
        r = self.run_cli("rm", "Sorry")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(ls.snippet_path(self.repo).read_text()), {})

    def test_add_body_from_stdin_multiline(self):
        r = self.run_cli("add", "Lemma", "--prefix", "lem",
                         stdin="lemma $1 : $2 := by\n  $0\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = json.loads(ls.snippet_path(self.repo).read_text())["Lemma"]["body"]
        self.assertEqual(body, ["lemma $1 : $2 := by", "  $0"])

    def test_add_duplicate_fails(self):
        self.run_cli("add", "A", "--body", "x")
        r = self.run_cli("add", "A", "--body", "y")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already exists", r.stderr)

    def test_link_status_unlink_with_explicit_dir(self):
        sdir = Path(self.tmp.name) / "User" / "snippets"
        r = self.run_cli("link", "--dir", str(sdir))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((sdir / ls.SNIPPET_FILE).is_symlink())
        r = self.run_cli("status", "--dir", str(sdir))
        self.assertIn("linked", r.stdout)
        r = self.run_cli("unlink", "--dir", str(sdir))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((sdir / ls.SNIPPET_FILE).exists())

    def test_target_register_then_link_picks_it_up(self):
        custom = Path(self.tmp.name) / "code-server" / "User" / "snippets"
        r = self.run_cli("target", "add", str(custom))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(str(custom), self.run_cli("target", "ls").stdout)
        # link (no --dir) acts on the union; here only the custom target exists
        r = self.run_cli("link")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((custom / ls.SNIPPET_FILE).is_symlink())
        # and it can be removed again
        r = self.run_cli("target", "rm", str(custom))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(str(custom), self.run_cli("target", "ls").stdout)

    def test_status_survives_invalid_json(self):
        # A broken file must not abort `status` -- it's the diagnostic command.
        ls.snippet_path(self.repo).write_text(
            '{\n  "a": {}\n  "b": {}\n}\n', encoding="utf-8")  # missing comma
        r = self.run_cli("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("INVALID", r.stdout)
        self.assertIn("git:", r.stdout)  # kept going past the bad file

    def test_add_refuses_to_clobber_invalid_json(self):
        ls.snippet_path(self.repo).write_text('{ broken', encoding="utf-8")
        r = self.run_cli("add", "X", "--body", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not valid JSON", r.stderr)

    def test_no_repo_set_errors_clearly(self):
        env = dict(os.environ)
        env.pop("LEANSNIP_REPO", None)
        env["HOME"] = str(Path(self.tmp.name) / "empty-home")  # no saved config
        r = subprocess.run([sys.executable, str(SCRIPT), "ls"],
                           text=True, stdout=PIPE, stderr=PIPE, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no snippets repo set", r.stderr)


# --------------------------------------------------------------------------- #
# interactive `add` (prompt for whatever wasn't passed as a flag)
# --------------------------------------------------------------------------- #
class TestInteractiveAdd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(repo=str(self.repo), name=None, prefix=None, desc=None,
                    body=None)
        base.update(kw)
        return argparse.Namespace(**base)

    def _add(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            ls.cmd_add(args)

    @mock.patch("builtins.input")
    @mock.patch("sys.stdin")
    def test_full_interactive(self, mock_stdin, mock_input):
        mock_stdin.isatty.return_value = True
        mock_input.side_effect = ["My Snippet", "mys", "does a thing",
                                  "line one $1", "line two $0", EOFError()]
        self._add(self._args())
        data = json.loads(ls.snippet_path(self.repo).read_text())
        self.assertEqual(data["My Snippet"], {
            "prefix": "mys", "body": ["line one $1", "line two $0"],
            "description": "does a thing"})

    @mock.patch("builtins.input")
    @mock.patch("sys.stdin")
    def test_prefix_defaults_to_name_and_desc_skipped(self, mock_stdin, mock_input):
        # name given as a flag; Enter at prefix -> name; Enter at desc -> omit.
        mock_stdin.isatty.return_value = True
        mock_input.side_effect = ["", "", "sorry", EOFError()]
        self._add(self._args(name="Sorry"))
        entry = json.loads(ls.snippet_path(self.repo).read_text())["Sorry"]
        self.assertEqual(entry["prefix"], "Sorry")
        self.assertEqual(entry["body"], "sorry")
        self.assertNotIn("description", entry)

    @mock.patch("builtins.input")
    @mock.patch("sys.stdin")
    def test_prompt_name_rejects_empty_and_duplicate(self, mock_stdin, mock_input):
        ls.write_snippets(self.repo, {"Taken": {"prefix": "t", "body": "x"}})
        mock_stdin.isatty.return_value = True
        mock_input.side_effect = ["", "Taken", "Fresh", "fr", "", "b", EOFError()]
        self._add(self._args())
        data = json.loads(ls.snippet_path(self.repo).read_text())
        self.assertIn("Fresh", data)
        self.assertEqual(len(data), 2)

    @mock.patch("builtins.input")
    @mock.patch("sys.stdin")
    def test_flags_skip_prompts(self, mock_stdin, mock_input):
        # Everything passed -> input() must never be called, even at a TTY.
        mock_stdin.isatty.return_value = True
        self._add(self._args(name="A", prefix="a", desc="d", body=["x"]))
        mock_input.assert_not_called()
        self.assertEqual(
            json.loads(ls.snippet_path(self.repo).read_text())["A"]["prefix"], "a")


if __name__ == "__main__":
    unittest.main()
