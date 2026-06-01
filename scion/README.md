# scion — compose Git branches from labeled ranges

`scion` tracks how a line of work is composed out of ordered ranges of commits,
so you can see its structure, check its health, and replay your essential changes
onto another composition. State for each scion lives in `.scions/<name>.json` at
the repo root.

A *scion* is a shoot grafted onto rootstock; here it's the recipe for what you
graft and where. Each range is one of three types:

- **substrate** — carried, fixed commits you don't author.
- **essence** — your authored payload, named (e.g. by PR number); the part you
  review and transplant.
- **computed** — machine-generated commits; carries the `command` that
  regenerates them.

Every range records its `base` and `tip` as full commit hashes. A range's `base`
should equal the previous range's `tip`; where it doesn't, the scion is stale at
that boundary, and operations run only over the healthy prefix below it.

The **read/edit half** — `new`, `ls`, `show`, `health`, `mark`, `unmark` — builds
and inspects scions. The **`apply`** engine replays one scion's essence onto
another, one reviewable step at a time (see [Applying](#applying) below). The full
design is in [../scion-design.md](../scion-design.md).

## Example

```sh
scion new  mywork -m "widget refactor + parser"
scion mark mywork base   --type substrate --tip main
scion mark mywork 12982  --type essence   --tip pr-12982 --branch pr-12982
scion mark mywork stage0 --type computed  --tip HEAD \
    --command "make -C build/release update-stage0-commit"
scion show mywork
scion health mywork
```

## Commands

| Command | What it does |
| --- | --- |
| `scion new <name> [-m DESC]` | Create a new, empty scion (with an optional description). |
| `scion ls` | List the scions in this repo, with their range counts and descriptions. |
| `scion show <name>` | Render the scion's ranges with commit counts and linked-branch sync state. |
| `scion health <name>` | Diagnose problems — boundary mismatches, drifted/missing branches, broken ranges — and exit non-zero if any. It only reports; you fix by hand. |
| `scion mark <name> <range> …` | Add a range or update an existing one by name. When adding, `--type` and `--tip` are required; the range is slotted in by where its tip falls — on top, or splitting the range it lands in and bumping the next range's base — so marks needn't be made bottom-up. Adding requires the scion to be healthy. |
| `scion unmark <name> <range>` | Remove a range. |
| `scion apply <src> <tgt>` | Replay `src`'s essence onto `tgt`, one step per invocation. `--dry-run` previews the plan; `--continue` does the next step; `--abort` undoes. |

Create a scion with `new`, then build it up with `mark`. You can add ranges in any
order — `mark` infers each one's position from its tip — as long as the scion is
healthy first, so the ranges form a consecutive chain it can place into. `mark`
resolves every revision you pass to a full hash, so the stored `base`/`tip` are
unambiguous. Editing `.scions/<name>.json` by hand stays a first-class path.
`.scions/` isn't meant to be committed — add it to `.gitignore` if you like.

## Applying

`apply` replays `src`'s essence onto `tgt` by matching the **same sequence of
essence names**: it keeps `tgt`'s substrate, swaps in `src`'s essence, and
regenerates computed ranges on top. It walks bottom-up over the healthy prefix,
fast-forwarding where it can and cherry-picking where it must.

You stay in the loop at every step. `scion apply <src> <tgt>` records the plan and
stops without touching anything. Each `scion apply --continue` then performs
exactly one step, prints what it did and what's next, and exits — so between steps
you can inspect the result, leave it as is, or `scion apply --abort` to return to
where you started.

```sh
scion apply newbase mywork --dry-run   # preview the plan
scion apply newbase mywork             # start: show the plan, change nothing
scion apply --continue                 # do the next step, then stop again
scion apply --by-hand                  # …or apply that step yourself
```

If a step conflicts, the working tree is left conflicted exactly as a normal
cherry-pick would be: resolve it, `git add`, and `scion apply --continue` to carry
on (the tips involved are parked under `refs/scion/<tgt>/` for reference). Only
tracked changes block an apply — untracked files are ignored. Before any linked
branch is moved to follow its new tip, its old tip is backed up under
`refs/scion/backup/<tgt>/`.

scion picks each step's action — fast-forward, cherry-pick, or regenerate — for
you. To apply a step yourself instead, run `scion apply --by-hand`: it parks those
same `refs/scion/<tgt>/` refs, leaves HEAD on the rebuilt base, and stops. Build
the range however you like, commit, and `scion apply --continue` records your HEAD
as its tip.

## Install

Run the bundled script, which adds this directory to your `PATH` via `~/.bashrc`
(idempotent):

```sh
./install.sh
source ~/.bashrc   # or open a new shell
```

Or symlink it yourself:

```sh
ln -s "$PWD/scion/scion" ~/.local/bin/scion
```

Requirements: `git` and Python 3.11+. No third-party packages.

## Tests

```sh
python3 test_scion.py
```
