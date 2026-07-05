#!/usr/bin/env python3
"""Tests for impgraph. Stdlib unittest only — no third-party packages.

    python3 test_impgraph.py     # or: python3 -m unittest -v

The graph logic is tested by importing the script as a module and building a
small fake source tree in a temp dir; the CLI/JSON contract is tested by driving
the executable as a subprocess.
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
SCRIPT = HERE / "impgraph"


def load_module():
    loader = importlib.machinery.SourceFileLoader("impgraph", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


impgraph = load_module()

# A small fake tree under <root>/Pkg:
#   A --public--> B --public--> D
#   A --private-> C --private-> D
#   E imports G, with a fenced `import Pkg.F` inside a docstring (must be ignored)
#   User --public--> A          (a downstream importer)
#   Cyc  --public--> A          (used to provoke a cycle when added to A)
FILES = {
    "Pkg/A.lean": "public import Pkg.B\nimport Pkg.C\n",
    "Pkg/B.lean": "public import Pkg.D\n",
    "Pkg/C.lean": "import Pkg.D\n",
    "Pkg/D.lean": "-- leaf\n",
    "Pkg/E.lean": "import Pkg.G\n\n/-!\nExample:\n```\npublic import Pkg.F\n```\n-/\n",
    "Pkg/F.lean": "-- leaf\n",
    "Pkg/G.lean": "-- leaf\n",
    "Pkg/User.lean": "public import Pkg.A\n",
    "Pkg/Cyc.lean": "public import Pkg.A\n",
}


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "src"
        for rel, content in FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.root = str(root)
        self.g = impgraph.Graph(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_imports_public_flag(self):
        self.assertEqual(self.g.imports("Pkg.A"),
                         (("Pkg.B", True), ("Pkg.C", False)))

    def test_docstring_imports_ignored(self):
        names = [n for n, _ in self.g.imports("Pkg.E")]
        self.assertEqual(names, ["Pkg.G"])
        self.assertNotIn("Pkg.F", names)

    def test_closure_build_follows_all(self):
        self.assertEqual(self.g.closure(["Pkg.A"]),
                         {"Pkg.B", "Pkg.C", "Pkg.D"})

    def test_closure_public_drops_private_edges(self):
        # A --private--> C is not followed; only A->B->D remain.
        self.assertEqual(self.g.closure(["Pkg.A"], public_only=True),
                         {"Pkg.B", "Pkg.D"})

    def test_path_and_no_path(self):
        self.assertEqual(self.g.path("Pkg.A", "Pkg.D")[0], "Pkg.A")
        self.assertEqual(self.g.path("Pkg.A", "Pkg.D")[-1], "Pkg.D")
        self.assertIsNone(self.g.path("Pkg.D", "Pkg.A"))

    def test_reverse_reachable_build(self):
        self.assertEqual(self.g.reverse_reachable("Pkg.D"),
                         {"Pkg.A", "Pkg.B", "Pkg.C", "Pkg.User", "Pkg.Cyc"})

    def test_reverse_reachable_public(self):
        # C->D is private, so C cannot reach D publicly; A reaches D via B.
        got = self.g.reverse_reachable("Pkg.D", public_only=True)
        self.assertIn("Pkg.B", got)
        self.assertIn("Pkg.A", got)
        self.assertNotIn("Pkg.C", got)

    def test_override_models_hypothetical(self):
        # Pretend A imports nothing: its closure is empty.
        self.assertEqual(self.g.closure(["Pkg.A"], override={"Pkg.A": []}), set())


class ParseAddTest(unittest.TestCase):
    def test_split_and_public_prefix(self):
        self.assertEqual(
            impgraph.parse_add(["public:Pkg.X", "Pkg.Y,Pkg.Z"]),
            [("Pkg.X", True), ("Pkg.Y", False), ("Pkg.Z", False)],
        )


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "src"
        for rel, content in FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.root = str(root)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", self.root, *args],
            capture_output=True, text=True,
        )

    def test_closure_count(self):
        r = self.run_cli("closure", "Pkg.A", "--count")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "3")

    def test_path_exit_codes(self):
        self.assertEqual(self.run_cli("path", "Pkg.A", "Pkg.D").returncode, 0)
        self.assertEqual(self.run_cli("path", "Pkg.D", "Pkg.A").returncode, 1)

    def test_impact_new_in_closure_json(self):
        # Add a brand-new private import G to A: G enters A's build closure.
        r = self.run_cli("--json", "impact", "Pkg.A", "--add", "Pkg.G")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("Pkg.G", data["new_in_closure"])
        self.assertEqual(data["mode"], "build")

    def test_impact_private_add_no_public_gain(self):
        # A private add does not propagate to downstream importers in public mode.
        r = self.run_cli("--public", "--json", "impact", "Pkg.A", "--add", "Pkg.G")
        data = json.loads(r.stdout)
        gains = {d["module"]: d["gain_via_change"] for d in data["downstream"]}
        self.assertEqual(gains["Pkg.G"], 0)

    def test_impact_build_add_propagates(self):
        # In build mode, importers of A that lacked G now gain it.
        r = self.run_cli("--json", "impact", "Pkg.A", "--add", "Pkg.G")
        data = json.loads(r.stdout)
        gains = {d["module"]: d["gain_via_change"] for d in data["downstream"]}
        self.assertGreater(gains["Pkg.G"], 0)  # User and Cyc import A, gain G

    def test_impact_cycle_detected(self):
        # Cyc imports A, so adding Cyc to A would create a cycle.
        r = self.run_cli("--json", "impact", "Pkg.A", "--add", "Pkg.Cyc")
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        self.assertTrue(data["cycles"])
        self.assertEqual(data["cycles"][0][0], "Pkg.Cyc")


if __name__ == "__main__":
    unittest.main()
