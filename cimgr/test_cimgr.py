#!/usr/bin/env python3
"""Tests for cimgr. Stdlib unittest only — no third-party packages.

    python3 test_cimgr.py        # or: python3 -m unittest -v

All GitHub access goes through a stub client, so the tests run offline. The
stub models a small slice of lean4 history: a linear master with nightly tags
on most days, and mathlib nightly-testing tags on a subset of them.
"""

import base64
import datetime
import importlib.machinery
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "cimgr"


def _load():
    loader = importlib.machinery.SourceFileLoader("cimgr_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cm = _load()

D = datetime.date

# The fake history below lives in June 2026; pin "now" so the forward scan
# for newer nightlies behaves the same whenever the tests run.
cm.today = lambda: D(2026, 6, 12)


class FakeGitHub:
    """Stub for cimgr.GitHub backed by a linear fake master history.

    `master` is an ordered list of (sha, date) from oldest to newest; ancestry
    is list order. `nightlies` / `mathlib_tags` map ISO dates to shas.
    """

    def __init__(
        self,
        master,
        nightlies,
        mathlib_tags,
        branch_commits=None,
        manifests=None,
        refman_tags=None,
    ):
        self.master = master
        self.order = {sha: i for i, (sha, _) in enumerate(master)}
        self.dates = dict(master)
        self.nightlies = nightlies
        self.mathlib_tags = mathlib_tags
        self.refman_tags = refman_tags or {}
        # branch commits: sha -> (merge_base_sha, ahead_by)
        self.branch_commits = branch_commits or {}
        # mathlib sha -> {package: rev} backing lake-manifest.json
        self.manifests = manifests or {}
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        parts = path.split("/")
        if path.startswith(f"repos/{cm.LEAN_REPO}/commits/"):
            return self._commit(parts[-1])
        if path.startswith(f"repos/{cm.LEAN_REPO}/compare/"):
            base, head = parts[-1].split("...")
            return self._compare(base, head)
        if "/git/ref/tags/" in path:
            repo = "/".join(parts[1:3])
            return self._tag(repo, parts[-1])
        if "/contents/lake-manifest.json" in path:
            return self._manifest(path.split("ref=")[-1])
        raise AssertionError(f"unexpected API path: {path}")

    def _manifest(self, ref):
        packages = self.manifests.get(ref)
        if packages is None:
            return 404, None
        body = json.dumps(
            {"packages": [{"name": n, "rev": r} for n, r in packages.items()]}
        )
        content = base64.b64encode(body.encode("utf-8")).decode("ascii")
        return 200, {"content": content, "encoding": "base64"}

    def _resolve(self, ref):
        if ref == "master":
            return self.master[-1][0]
        for sha in list(self.order) + list(self.branch_commits):
            if sha.startswith(ref):
                return sha
        return None

    def _commit(self, ref):
        sha = self._resolve(ref)
        if sha is None:
            return 404, None
        date = self.dates.get(sha) or self.dates[self.branch_commits[sha][0]]
        return 200, {
            "sha": sha,
            "commit": {
                "message": f"subject of {sha}\n\nbody",
                "committer": {"date": f"{date.isoformat()}T08:00:00Z"},
            },
        }

    def _mb(self, a, b):
        """Merge base of two shas in the fake history."""
        if a in self.branch_commits:
            a = self.branch_commits[a][0]
        if b in self.branch_commits:
            b = self.branch_commits[b][0]
        return a if self.order[a] <= self.order[b] else b

    def _compare(self, base, head):
        base, head = self._resolve(base), self._resolve(head)
        if base is None or head is None:
            return 404, None
        mb = self._mb(base, head)
        ahead = self.branch_commits.get(head, (None, 0))[1] or (
            self.order.get(head, 0) - self.order[mb]
            if head not in self.branch_commits
            else 0
        )
        behind = self.order.get(base, len(self.master) - 1) - self.order[mb]
        if head in self.branch_commits:
            ahead = self.branch_commits[head][1]
        return 200, {
            "merge_base_commit": {
                "sha": mb,
                "commit": {
                    "committer": {"date": f"{self.dates[mb].isoformat()}T08:00:00Z"}
                },
            },
            "ahead_by": ahead,
            "behind_by": behind,
        }

    def _tag(self, repo, tag):
        table = {
            cm.NIGHTLY_REPO: self.nightlies,
            cm.MATHLIB_REPO: self.mathlib_tags,
            cm.REFMAN_REPO: self.refman_tags,
        }[repo]
        for prefix in ("nightly-testing-", "nightly-"):
            if tag.startswith(prefix):
                date = tag[len(prefix):]
                break
        sha = table.get(date)
        if sha is None:
            return 404, None
        return 200, {"object": {"sha": sha, "type": "commit"}}


def make_world():
    """A week of fake history.

    master:    c1 .. c6 on June 4..9 (no commit on the 7th)
    nightlies: June 5, 6, 8, 9 (skipped on the 7th); the June 6 nightly is
               re-tagged on the (quiet) 7th? -> no, the 7th has no tag at all.
    mathlib:   June 5 and 8 only.
    refman:    June 5 and 9 only (a different subset than mathlib).
    branch:    'feat1' commit, 2 ahead of merge base c4 (June 6).
    """
    master = [
        ("c1" * 20, D(2026, 6, 4)),
        ("c2" * 20, D(2026, 6, 5)),
        ("c3" * 20, D(2026, 6, 5)),
        ("c4" * 20, D(2026, 6, 6)),
        ("c5" * 20, D(2026, 6, 8)),
        ("c6" * 20, D(2026, 6, 9)),
    ]
    nightlies = {
        "2026-06-05": "c2" * 20,
        "2026-06-06": "c3" * 20,
        "2026-06-08": "c4" * 20,
        "2026-06-09": "c5" * 20,
    }
    mathlib_tags = {
        "2026-06-05": "m5" * 20,
        "2026-06-08": "m8" * 20,
    }
    refman_tags = {
        "2026-06-05": "r5" * 20,
        "2026-06-09": "r9" * 20,
    }
    branch_commits = {"f1" * 20: ("c4" * 20, 2)}
    manifests = {
        "m5" * 20: {"batteries": "ba5" * 13 + "b", "Qq": "qq5" * 13 + "q"},
        "m8" * 20: {"batteries": "ba8" * 13 + "b", "Qq": "qq8" * 13 + "q"},
    }
    return FakeGitHub(
        master, nightlies, mathlib_tags, branch_commits, manifests, refman_tags
    )


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
class TestHelpers(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(
            cm.parse_date("2026-06-10T12:34:56Z"), D(2026, 6, 10)
        )

    def test_tag_names(self):
        self.assertEqual(cm.nightly_tag(D(2026, 6, 5)), "nightly-2026-06-05")
        self.assertEqual(
            cm.mathlib_tag(D(2026, 6, 5)), "nightly-testing-2026-06-05"
        )

    def test_is_ancestor(self):
        gh = make_world()
        self.assertTrue(cm.is_ancestor(gh, "c2" * 20, "c4" * 20))
        self.assertTrue(cm.is_ancestor(gh, "c4" * 20, "c4" * 20))
        self.assertFalse(cm.is_ancestor(gh, "c5" * 20, "c4" * 20))

    def test_commit_info_not_found(self):
        gh = make_world()
        with self.assertRaises(cm.CimgrError):
            cm.commit_info(gh, "deadbeef")


# --------------------------------------------------------------------------- #
# nightly resolution
# --------------------------------------------------------------------------- #
class TestFindNightly(unittest.TestCase):
    def test_basic(self):
        gh = make_world()
        # merge base c4 (June 6): June 8's nightly tags c4 itself, and it is
        # the newest nightly that's still an ancestor -> the skipped day and
        # the forward walk over re-tagged history are both exercised.
        date, tag, sha = cm.find_nightly(gh, "c4" * 20, D(2026, 6, 6))
        self.assertEqual(tag, "nightly-2026-06-08")
        self.assertEqual(sha, "c4" * 20)

    def test_tip_of_master(self):
        gh = make_world()
        date, tag, sha = cm.find_nightly(gh, "c6" * 20, D(2026, 6, 9))
        self.assertEqual(tag, "nightly-2026-06-09")
        self.assertEqual(sha, "c5" * 20)

    def test_no_nightly_found(self):
        gh = make_world()
        gh.nightlies = {}
        with self.assertRaises(cm.CimgrError):
            cm.find_nightly(gh, "c4" * 20, D(2026, 6, 6))


class TestFindNightlyWithMathlib(unittest.TestCase):
    def test_falls_back_past_missing_mathlib_tag(self):
        gh = make_world()
        # Starting at June 9 (nightly exists, no mathlib tag): must fall back
        # to June 8, where both tags exist.
        tag, sha, ml_tag, ml_sha = cm.find_nightly_with_mathlib(
            gh, "c5" * 20, D(2026, 6, 9)
        )
        self.assertEqual(tag, "nightly-2026-06-08")
        self.assertEqual(sha, "c4" * 20)
        self.assertEqual(ml_tag, "nightly-testing-2026-06-08")
        self.assertEqual(ml_sha, "m8" * 20)

    def test_same_day_hit(self):
        gh = make_world()
        tag, sha, ml_tag, ml_sha = cm.find_nightly_with_mathlib(
            gh, "c4" * 20, D(2026, 6, 8)
        )
        self.assertEqual(tag, "nightly-2026-06-08")
        self.assertEqual(ml_tag, "nightly-testing-2026-06-08")

    def test_none_within_lookback(self):
        gh = make_world()
        gh.mathlib_tags = {}
        with self.assertRaises(cm.CimgrError):
            cm.find_nightly_with_mathlib(gh, "c4" * 20, D(2026, 6, 8))


class TestFindNightlyWithRefman(unittest.TestCase):
    def test_falls_back_past_missing_refman_tag(self):
        gh = make_world()
        # Starting at June 8 (nightly exists, no refman tag): must fall back
        # to June 5, where both a nightly and a refman tag exist.
        tag, sha, rm_tag, rm_sha = cm.find_nightly_with_refman(
            gh, "c4" * 20, D(2026, 6, 8)
        )
        self.assertEqual(tag, "nightly-2026-06-05")
        self.assertEqual(sha, "c2" * 20)
        self.assertEqual(rm_tag, "nightly-testing-2026-06-05")
        self.assertEqual(rm_sha, "r5" * 20)

    def test_same_day_hit(self):
        gh = make_world()
        # June 9: nightly (c5) and a refman tag both exist, and c5 is an
        # ancestor of the master tip.
        tag, sha, rm_tag, rm_sha = cm.find_nightly_with_refman(
            gh, "c6" * 20, D(2026, 6, 9)
        )
        self.assertEqual(tag, "nightly-2026-06-09")
        self.assertEqual(rm_tag, "nightly-testing-2026-06-09")
        self.assertEqual(rm_sha, "r9" * 20)

    def test_none_within_lookback(self):
        gh = make_world()
        gh.refman_tags = {}
        with self.assertRaises(cm.CimgrError):
            cm.find_nightly_with_refman(gh, "c4" * 20, D(2026, 6, 8))


class TestMathlibDeps(unittest.TestCase):
    def test_reads_pinned_revs(self):
        gh = make_world()
        deps = cm.mathlib_deps(gh, "m8" * 20)
        self.assertEqual(list(deps), list(cm.DEP_PACKAGES))
        self.assertEqual(deps["batteries"], "ba8" * 13 + "b")
        self.assertEqual(deps["Qq"], "qq8" * 13 + "q")

    def test_missing_package_is_none(self):
        gh = make_world()
        gh.manifests["m8" * 20] = {"batteries": "ba8" * 13 + "b"}
        deps = cm.mathlib_deps(gh, "m8" * 20)
        self.assertEqual(deps["batteries"], "ba8" * 13 + "b")
        self.assertIsNone(deps["Qq"])

    def test_missing_manifest_errors(self):
        gh = make_world()
        with self.assertRaises(cm.CimgrError):
            cm.mathlib_deps(gh, "nope" * 10)


# --------------------------------------------------------------------------- #
# end to end (stubbed network)
# --------------------------------------------------------------------------- #
class TestGatherStats(unittest.TestCase):
    def test_branch_commit(self):
        gh = make_world()
        stats = cm.gather_stats(gh, "f1f1")
        self.assertEqual(stats["commit"]["sha"], "f1" * 20)
        self.assertEqual(stats["merge_base"]["sha"], "c4" * 20)
        self.assertEqual(stats["merge_base"]["ahead_by"], 2)
        self.assertEqual(stats["merge_base"]["behind_by"], 2)
        self.assertEqual(stats["nightly"]["tag"], "nightly-2026-06-08")
        self.assertEqual(
            stats["nightly_with_mathlib"]["tag"], "nightly-2026-06-08"
        )
        self.assertEqual(
            stats["nightly_with_mathlib"]["mathlib"]["sha"], "m8" * 20
        )
        self.assertEqual(
            stats["nightly_with_mathlib"]["mathlib"]["deps"],
            {"batteries": "ba8" * 13 + "b", "Qq": "qq8" * 13 + "q"},
        )
        # The newest nightly with a refman build at/below c4 is June 5.
        self.assertEqual(
            stats["nightly_with_refman"]["tag"], "nightly-2026-06-05"
        )
        self.assertEqual(
            stats["nightly_with_refman"]["reference_manual"]["sha"], "r5" * 20
        )

    def test_master_tip_splits_the_two_nightlies(self):
        gh = make_world()
        stats = cm.gather_stats(gh, "c6c6")
        self.assertEqual(stats["nightly"]["tag"], "nightly-2026-06-09")
        self.assertEqual(
            stats["nightly_with_mathlib"]["tag"], "nightly-2026-06-08"
        )
        # The refman tag on June 9 lands on the same nightly as the plain one.
        self.assertEqual(
            stats["nightly_with_refman"]["tag"], "nightly-2026-06-09"
        )
        self.assertEqual(
            stats["nightly_with_refman"]["reference_manual"]["tag"],
            "nightly-testing-2026-06-09",
        )

    def test_render_and_json_roundtrip(self):
        gh = make_world()
        stats = cm.gather_stats(gh, "c6c6")
        text = cm.render_stats(stats)
        self.assertIn("nightly-2026-06-09", text)
        self.assertIn("nightly-testing-2026-06-08", text)
        # The reference-manual line is rendered with its nightly-testing tag.
        self.assertIn("reference-manual: nightly-testing-2026-06-09", text)
        # Mathlib's nightly differs from the plain one (no "(same)"); the
        # refman nightly happens to match it, so a single "(same)" appears.
        self.assertEqual(text.count("(same)"), 1)
        # batteries/Qq lines carry the manifest revs of the mathlib commit.
        self.assertIn("batteries: " + ("ba8" * 13 + "b")[:12], text)
        self.assertIn("Qq (quote4): " + ("qq8" * 13 + "q")[:12], text)
        self.assertEqual(json.loads(json.dumps(stats)), stats)

    def test_render_marks_same_nightly(self):
        gh = make_world()
        stats = cm.gather_stats(gh, "f1f1")
        self.assertIn("(same)", cm.render_stats(stats))


if __name__ == "__main__":
    unittest.main()
