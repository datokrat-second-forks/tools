#!/usr/bin/env python3
"""Tests for linepick. Stdlib unittest only — no third-party packages.

    python3 test_linepick.py     # or: python3 -m unittest -v

The pure transform is tested by importing the script as a module with a fake
`resolve` chooser; the JSON contract and handler dispatch are tested by driving
the CLI with $LINEPICK_PICKER and a stub linepick-<type> handler.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "linepick"


def load_module():
    loader = importlib.machinery.SourceFileLoader("linepick", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TransformTest(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def fixed(self, value):
        return lambda type_, current: value

    def test_replaces_placeholder(self):
        line, _ = self.m.transform("a [[note|?]] b", 6, resolve=self.fixed("d/x.md"))
        self.assertEqual(line, "a [[note|d/x.md]] b")

    def test_replaces_existing_path(self):
        line, _ = self.m.transform("[[n|old/p.md]]", 3, resolve=self.fixed("new.md"))
        self.assertEqual(line, "[[n|new.md]]")

    def test_inserts_path_into_pipeless_link(self):
        line, col = self.m.transform("[[abc]]", 4, resolve=self.fixed("d/x.md"))
        self.assertEqual(line, "[[abc|d/x.md]]")
        self.assertEqual(col, 15)  # 1-based byte col just past ]]

    def test_inserts_path_keeping_surrounding_text(self):
        line, _ = self.m.transform("see [[abc]] end", 7, resolve=self.fixed("p"))
        self.assertEqual(line, "see [[abc|p]] end")

    def test_cursor_not_on_link_is_noop(self):
        called = []
        line, col = self.m.transform(
            "text [[n|?]]", 1, resolve=lambda t, c: called.append(1) or "x"
        )
        self.assertEqual((line, col), ("text [[n|?]]", 1))
        self.assertEqual(called, [])  # chooser never runs off a link

    def test_cancel_leaves_line(self):
        line, col = self.m.transform("[[n|?]]", 3, resolve=lambda t, c: None)
        self.assertEqual((line, col), ("[[n|?]]", 3))

    def test_picks_link_under_cursor(self):
        line, _ = self.m.transform("[[a|?]] [[b|?]]", 11, resolve=self.fixed("Z"))
        self.assertEqual(line, "[[a|?]] [[b|Z]]")  # cursor was in the 2nd link

    def test_cursor_moves_past_link(self):
        line, col = self.m.transform("[[n|?]] x", 3, resolve=self.fixed("abc"))
        self.assertEqual(line, "[[n|abc]] x")
        self.assertEqual(col, 10)  # 1-based byte col of the space after ]]

    def test_multibyte_name_keeps_columns(self):
        line, _ = self.m.transform("[[Über|?]]", 4, resolve=self.fixed("p.md"))
        self.assertEqual(line, "[[Über|p.md]]")

    # --- typed links --------------------------------------------------------
    def test_typed_link_keeps_type_and_passes_it(self):
        seen = []
        line, _ = self.m.transform(
            "[[session:?]]", 5, resolve=lambda t, c: seen.append((t, c)) or "work"
        )
        self.assertEqual(line, "[[session:work]]")
        self.assertEqual(seen, [("session", "?")])  # type + current handed over

    def test_typed_link_with_name(self):
        line, _ = self.m.transform("[[note|session:?]]", 10, resolve=self.fixed("work"))
        self.assertEqual(line, "[[note|session:work]]")

    def test_untyped_target_passes_none_type(self):
        seen = []
        self.m.transform("[[n|p]]", 4, resolve=lambda t, c: seen.append((t, c)) or "X")
        self.assertEqual(seen, [(None, "p")])


class CliContractTest(unittest.TestCase):
    def run_tool(self, line, col, env_extra):
        with tempfile.TemporaryDirectory() as d:
            infile, outfile = Path(d) / "in.json", Path(d) / "out.json"
            infile.write_text(json.dumps({"line": line, "col": col}))
            env = dict(os.environ, **env_extra)
            subprocess.run(
                [sys.executable, str(SCRIPT), str(infile), str(outfile)],
                check=True, env=env, capture_output=True, text=True,
            )
            return json.loads(outfile.read_text())["line"]

    def _handler_dir(self, body):
        d = tempfile.mkdtemp()
        h = Path(d) / "linepick-session"
        h.write_text("#!/bin/sh\n" + body + "\n")
        h.chmod(0o755)
        return d

    def test_untyped_uses_picker_env(self):
        got = self.run_tool("see [[n|?]]", 8, {"LINEPICK_PICKER": "printf 'docs/readme.md'"})
        self.assertEqual(got, "see [[n|docs/readme.md]]")

    def test_typed_dispatches_to_handler(self):
        d = self._handler_dir("printf 'mysess'")
        got = self.run_tool("[[session:?]]", 5, {"LINEPICK_HANDLER_DIR": d})
        self.assertEqual(got, "[[session:mysess]]")

    def test_handler_receives_current_value_as_arg(self):
        d = self._handler_dir('printf "got:%s" "$1"')
        got = self.run_tool("[[session:abc]]", 5, {"LINEPICK_HANDLER_DIR": d})
        self.assertEqual(got, "[[session:got:abc]]")


class SessionHandlerTest(unittest.TestCase):
    """linepick-session forwards the current value to `tmgr pick` as --query,
    except the `?` placeholder. Stubs `tmgr` on PATH to echo its arguments."""

    HANDLER = HERE / "linepick-session"

    def invoke(self, arg):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / "tmgr"
            stub.write_text('#!/bin/sh\nprintf "%s" "$*"\n')
            stub.chmod(0o755)
            env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"])
            return subprocess.run(
                [str(self.HANDLER), arg], env=env,
                capture_output=True, text=True,
            ).stdout

    def test_existing_value_prefills_query(self):
        self.assertEqual(self.invoke("mysession"), "pick --all --query mysession")

    def test_placeholder_omits_query(self):
        self.assertEqual(self.invoke("?"), "pick --all")


if __name__ == "__main__":
    unittest.main()
