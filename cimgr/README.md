# cimgr — helpers for complex Lean 4 CI tasks

`cimgr` collects facts you need when working on Lean 4 CI, straight from the
GitHub API — no local clones of the involved repositories required.

## Commands

### `cimgr stats lean4 [commit] [--json]`

Given a commit of [leanprover/lean4](https://github.com/leanprover/lean4)
(hash or any ref; defaults to the HEAD of the Git repository in the current
directory, which is assumed to be a lean4 checkout), reports:

- **merge base** with `master`, plus how far the commit is ahead/behind;
- **nightly**: the most recent nightly release the commit is based on, i.e.
  the newest `nightly-YYYY-MM-DD` tag of
  [leanprover/lean4-nightly](https://github.com/leanprover/lean4-nightly)
  whose commit is an ancestor of the merge base;
- **nightly w/ mathlib**: the most recent such nightly that also has a
  mathlib4 nightly-testing release, together with the corresponding
  `nightly-testing-YYYY-MM-DD` commit of
  [leanprover-community/mathlib4-nightly-testing](https://github.com/leanprover-community/mathlib4-nightly-testing).
  Often the same as **nightly**, but falls back to an earlier day when
  mathlib's nightly-testing build hasn't landed (or failed) for the newest
  nightlies.

```
$ cimgr stats lean4 master
commit:              548f78b6df79  doc: fix stale references in `do` elaborator docs (#14026) (2026-06-12)
merge base:          548f78b6df79  (0 ahead, 0 behind master)
nightly:             nightly-2026-06-12  c2b551f5f513
nightly w/ mathlib:  nightly-2026-06-10  659e8bb85899
  mathlib4-nightly-testing: nightly-testing-2026-06-10  49e20716a159
```

`--json` emits the same data as a JSON object for scripting.

## How it works

Nightly tags in `lean4-nightly` point at the very commit objects of
`leanprover/lean4`, so everything reduces to GitHub `compare` calls against
that one repo: `master...<commit>` yields the merge base, and a tag is "based
on" when comparing shows it zero commits ahead of the merge base. The nightly
search walks tag dates backward from the merge base's commit date (skipping
days without a release), then forward again to catch later nightlies that
re-tag the same history.

## Install

```sh
./install.sh    # appends this directory to PATH in ~/.bashrc
```

Requires Python 3 (stdlib only). Unauthenticated GitHub API access allows 60
requests/hour — a single `stats` run needs roughly ten — so set
`GITHUB_TOKEN` (or `GH_TOKEN`) for frequent use.

## Tests

```sh
python3 test_cimgr.py
```

The tests stub the GitHub client with a small fake history, so they run
offline.
