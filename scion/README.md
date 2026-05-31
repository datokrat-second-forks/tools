# scion — compose Git branches from labeled ranges

`scion` tracks how a line of work is composed out of ordered ranges of commits,
so you can see its structure, check its health, and (eventually) replay your
essential changes onto another composition. State for each scion lives in
`.scions/<name>.json` at the repo root.

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

This directory currently implements the **read/edit half** — `show`, `health`,
`mark`, `unmark`. The `apply` engine (replaying essence onto another scion) is
still to come. The full design is in [../scion-design.md](../scion-design.md).

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
| `scion mark <name> <range> …` | Add a range (appended on top) or update an existing one by name. `--type` and `--tip` are required when adding; `--base` defaults to the current top range's tip. |
| `scion unmark <name> <range>` | Remove a range. |

Create a scion with `new`, then build it up with `mark`. `mark` resolves every
revision you pass to a full hash, so the stored `base`/`tip` are unambiguous.
Editing `.scions/<name>.json` by hand stays a first-class path.
`.scions/` isn't meant to be committed — add it to `.gitignore` if you like.

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
