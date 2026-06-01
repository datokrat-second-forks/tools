# Scion: composing Git branches from labeled ranges

`scion` manages **scions**: standalone recipes that describe how a line of work
is composed, and that can be replayed onto other compositions. It targets
complex / stacked Git work — several PRs in a tower, with the occasional
machine-generated commit (e.g. a Lean `stage0` update) mixed in.

A *scion* is a shoot grafted onto rootstock; here it's the description of what
you graft and where.

## Concepts

A **scion** is a standalone object — a file at `.scions/<name>.json`. It is *not*
metadata on a branch; it relates to branches only through its ranges.

A scion is an ordered, chronological list of **ranges** (bottom → top). Each
range covers a contiguous span of commits and records its own endpoints. Every
range has one of three **types**:

- **substrate** — the fixed foundation and any carried commits you don't author.
  scion never edits substrate; it only *replays* it when a range below changes.
- **essence** — your authored payload, identified by a human **name** (typically
  a PR number). This is what gets transplanted, and what you review.
- **computed** — a machine-generated range; carries the `command` that
  regenerates it.

A range looks like:

```json
{ "type": "essence", "name": "12982",
  "base": "9b7e2d4a1c8f6053e7a9b2c4d6f8013579ace024",
  "tip":  "0c5e1b8d4a2f9c7e6b3d0a1f3f1a9c4e8b2d7a6f",
  "branch": "pr-12982", "description": "#12982 widget refactor" }
```

- `name` — stable **identity** (the match key for `apply`); survives rebases.
- `base` — the **full** hash this range is built on. Omitted on the first range
  (its base is the repo root).
- `tip` — the **full** hash of the range's last commit; its current location.
  scion rewrites it on every operation.
- `branch` — optional ref scion keeps pointing at the tip (see below).
- `command` — `computed` ranges only: how to regenerate.
- `description` — optional free text. The scion itself also has a top-level
  `description`.

Hashes are stored in full, for unambiguous identity.

### Healthy prefix

A boundary is **healthy** when a range's `base` equals the previous range's
`tip`. In a healthy scion they all match, so the `base` fields are
redundant-but-explicit — and that's on purpose: when you change one range, the
boundary just above it goes stale (its `base` no longer equals the new `tip`
below) instead of silently forcing every range above to update at once.

scion operates only over the **healthy prefix** — the bottom run of matching
boundaries. At the first base/tip **mismatch** it stops and reports it; you must
replay that range onto the new tip (and `mark` it) before operating past it.
Re-syncing a mismatch is manual for now.

### `branch` always follows the tip

A linked `branch` is a **projection**: scion force-updates it to equal the
range's tip after every operation. One direction only — scion → branch. If a
branch is moved outside scion it has **drifted** off its tip. scion doesn't
repair this; `scion health` diagnoses it and you fix it by hand (e.g. `mark` the
range to adopt the new tip, or reset the branch).

There is no upstream tracking and no pull. A scion's substrate is frozen at its
anchor commits; to move work onto a newer base you build a new scion on that base
and `apply` onto it (below).

## Example

A tower of two PRs with a `stage0` update wedged in, plus carried collaborator
commits (full hashes elided in the middle for readability):

```json
{
  "description": "widget refactor (#12982) + parser (#19539)",
  "ranges": [
    { "type": "substrate", "name": "base",
      "tip": "3f1a9c4e8b2d7a6f0c5e1b8d4a2f9c7e6b3d0a1f" },
    { "type": "essence", "name": "12982", "branch": "pr-12982", "description": "#12982 widget refactor",
      "base": "3f1a9c4e8b2d7a6f0c5e1b8d4a2f9c7e6b3d0a1f",
      "tip":  "9b7e2d4a1c8f6053e7a9b2c4d6f8013579ace024" },
    { "type": "computed", "name": "stage0", "command": "make -C build/release update-stage0-commit",
      "base": "9b7e2d4a1c8f6053e7a9b2c4d6f8013579ace024",
      "tip":  "0c5e1b8d4a2f9c7e6b3d0a1f3f1a9c4e8b2d7a6f" },
    { "type": "substrate", "name": "collab", "description": "teammates' unrelated commits",
      "base": "0c5e1b8d4a2f9c7e6b3d0a1f3f1a9c4e8b2d7a6f",
      "tip":  "a1f3f1a9c4e8b2d7a6f0c5e1b8d4a2f9c7e6b3d0" },
    { "type": "essence", "name": "19539", "branch": "pr-19539", "description": "#19539 parser",
      "base": "a1f3f1a9c4e8b2d7a6f0c5e1b8d4a2f9c7e6b3d0",
      "tip":  "6f8013579ace0249b7e2d4a1c8f6053e7a9b2c4d" }
  ]
}
```

## Commands

### `scion show <name>`

Render the composition: each range's type, name, description, commit count
(`git rev-list --count <base>..<tip>`), and a terse sync glyph for linked ranges.

```
widget refactor (#12982) + parser (#19539)
  substrate  base                      tip 3f1a9c4
  essence    12982   4 commits   ✓     → pr-12982
  computed   stage0  1 commit          (make -C build/release update-stage0-commit)
  substrate  collab  2 commits
  essence    19539   6 commits   ✗     → pr-19539   (drifted — see `scion health`)
```

### `scion health <name>`

Diagnose and explain the scion's problems — it only diagnoses; fixing is by hand:

- **base/tip mismatches** — where the healthy prefix ends, and why;
- **drifted branches** — a linked branch no longer at its range's tip;
- **broken ranges** — a `base`/`tip` that doesn't resolve, or a `base` that isn't
  an ancestor of its `tip`.

### `scion mark <name> <range> …` / `scion unmark <name> <range>`

Add, update, or remove a range of any type (substrate included). Marks needn't be
made bottom-up: when adding, `mark` infers the range's place from where its `--tip`
falls — above the stack it goes on top, inside an existing range it splits that one
and bumps the **succeeding range's base** to the new tip so the chain stays
consecutive. That inference only holds on a healthy scion, so adding to an unhealthy
one is refused (`scion health` explains; repair via `mark`'s in-place update first,
which is the one path left untouched by the health gate). `mark` doesn't create a
scion — use `scion new`. Hand-editing the JSON stays a first-class path.

### `scion apply <source> <target>`

Bring `source`'s essence work onto `target`'s composition. Requires `source` and
`target` to have the **same sequence of essence names** (equality). scion rebuilds
`target` bottom-up, over its healthy prefix:

- **substrate** → keep `target`'s, replayed onto whatever changed below it;
- **essence "N"** → replace with `source`'s "N";
- **computed** → regenerate by re-running its `command`.

`target` must be healthy first; a stale boundary aborts the apply with a pointer
to `scion health` (you replay the stale range by hand, then apply). Linked
branches are force-updated to follow the new tips, with their old tips backed up
under `refs/scion/backup/<target>/`. `--dry-run` prints the plan without touching
anything.

This single operation also covers "rebase onto a newer base": build a fresh
`target` scion on the new base (same essence names), then `apply` your working
scion onto it.

#### Stepping through an apply

The human stays in the loop before every step. `scion apply <source> <target>`
records the plan and stops without changing anything. Each `scion apply
--continue` then performs exactly one step — fast-forward, cherry-pick,
regenerate, or keep — prints what it did and what comes next, and exits. Between
steps you resume with `--continue`, leave the half-built result as it is, or
`scion apply --abort` to return to where you started. One apply runs at a time.

A step that conflicts leaves the working tree conflicted, exactly like an ordinary
cherry-pick: resolve it, `git add`, and `--continue` finishes that step and moves
on. For reference it parks the commits being replayed at `refs/scion/<target>/new`
(and, for an essence range, the target's prior version at `/old`). Only tracked
changes block an apply — untracked files are ignored.

scion chooses each step's action for you — fast-forward when it can, cherry-pick
when it must, regenerate computed ranges. To decide for yourself, run `scion apply
--by-hand` in place of `--continue`: it parks those same `refs/scion/<target>/`
refs, leaves HEAD on the rebuilt base, and stops. Build the range however you
like — cherry-pick `…/new`, take a subset, edit, whatever — commit, then `scion
apply --continue` records your HEAD as the range's tip and carries on.

## Invariants

- `name` is identity, `base`/`tip` are location, `branch` is a scion-owned
  projection that follows the tip.
- Operations run over the healthy prefix only; mismatches and drift are
  diagnosed by `scion health` and fixed by hand.
- Substrate is fixed; essence is the review surface; computed is regenerated
  rather than trusted — re-running its `command` overwrites whatever was there,
  which is handy when reviewing untrusted work.

## Future work

- Export/import of patch files, to move a scion between checkouts.
- A retrospective `diff` between two states of a scion (the earlier idea) isn't
  included here; `apply --dry-run` covers the forward "what would change" need.
