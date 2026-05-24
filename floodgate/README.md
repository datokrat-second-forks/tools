# floodgate — review a branch diff in your browser, with persistent marks

`floodgate` helps you review the difference between two branches before merging.
It serves a rendered HTML diff on a local HTTP server where you accept, reject,
or skip each change; the marks are saved to a `.review` file in the current
directory, so you can stop and resume later. Bulk-marking is done by piping
through diffkit's `filter-diff`.

```sh
floodgate review main feature        # open the diff in your browser
floodgate diff | filter-diff -i "TODO" | floodgate reject   # bulk-mark
floodgate status                     # how much is left to review
```

floodgate is built on [diffkit](../diffkit/): it shells out to `structured-diff`
for the diff and reuses `filter-diff` in the pipeline. It's a self-contained
Python 3.11+ script — no third-party packages (the server is `http.server`).

## How it works

- **The unit of review is the hunk.** Each hunk gets a `review_id` derived from
  its file path and *changed-line content*. A file shows the roll-up of its
  hunks and offers whole-file actions. Files with no hunks (renames, mode-only,
  binary) are a single unit of their own.
- **Marks live in `./.review`** (JSON), keyed by the two compared commits. Four
  states: `accepted`, `rejected`, `skipped`, and the implicit `unreviewed`.
- **Content-derived ids make stale review self-correcting.** If the branch
  changes a hunk, its `review_id` changes, the old mark no longer matches, and
  the hunk reappears as `unreviewed`. The commit SHAs in `.review` let floodgate
  warn you when the branches have moved since you started.
- **Marking is immediate.** Clicking a button POSTs to the server, which writes
  `.review` and updates the page in place — nothing is ever unsaved, so you can
  quit at any point and resume.

> Add `.review` to your `.gitignore` so a stray `git add -A` can't commit it.
> `floodgate review` prints a hint if it isn't ignored.

## Install

Run the bundled script, which adds this directory to your `PATH` via `~/.bashrc`
(idempotent):

```sh
./install.sh
source ~/.bashrc   # or open a new shell
```

Or symlink it yourself:

```sh
ln -s "$PWD/floodgate/floodgate" ~/.local/bin/floodgate
```

Requirements: `git`, and diffkit's `structured-diff` and `filter-diff` on your
`PATH` (see [../diffkit](../diffkit/)).

## Commands

| Command | What it does |
| --- | --- |
| `floodgate review <base> <target>` | Create or resume the review for this pair and serve it in the browser. |
| `floodgate diff` | Emit the active review's diff as JSON, each hunk annotated with its `review_id` and current `review_status`. The source of the bulk pipeline. |
| `floodgate accept` | Read a diff document on stdin; mark every change in it `accepted`. |
| `floodgate reject` | …mark them `rejected`. |
| `floodgate skip` | …mark them `skipped`. |
| `floodgate clear` | …remove their marks (back to `unreviewed`). |
| `floodgate status` | Print the pair, counts per state, and whether the branches moved. |

### `floodgate review <base> <target>`

```
floodgate review [-C DIR] [--two-dot] [-p PORT] [--no-open] BASE TARGET
```

| Option | Meaning |
| --- | --- |
| `-C, --directory DIR` | git repo to diff (default: cwd) |
| `--two-dot` | diff `base..target` (the two tips) instead of the default `base...target` (changes on `target` since the merge-base) |
| `-p, --port N` | port to serve on (default: 8765; tries the next few if busy) |
| `--no-open` | don't open a browser automatically |

By default floodgate uses **three-dot** (`base...target`) semantics — the same
as a GitHub pull request: it shows what `target` introduces relative to the
common ancestor, not unrelated changes that landed on `base` since. Use
`--two-dot` to compare the two branch tips directly.

Running `review` again for the same pair resumes it (marks are kept). Running it
for a *different* pair prompts before discarding the existing `.review`.

## The bulk-marking pipeline

`floodgate diff` embeds a stable `review_id` on every hunk *inside the diffkit
JSON*. `filter-diff` passes that field through untouched while it selects a
subset, so the marking commands just read the ids off their stdin — no fragile
re-matching:

```sh
floodgate diff | filter-diff -i "TODO"        | floodgate reject   # by content
floodgate diff | filter-diff -F "console.log" | floodgate skip
floodgate diff | filter-diff --exclude "lorem ipsum" | floodgate accept
```

Then open `floodgate review` (or refresh the page) to see the marks and review
what's left.

> Note on structural-only changes: a rename or mode-only change has no changed
> lines for `filter-diff` to test, so it counts as *non-matching*. A keep-mode
> filter (`filter-diff PATTERN | floodgate reject`) leaves it out; an `--exclude`
> filter (`filter-diff --exclude PATTERN | floodgate accept`) keeps it, so it
> gets marked along with the non-matching content. Mark such files individually
> in the UI if that isn't what you want.

## The `.review` file (`floodgate.review/v1`)

```json
{
  "schema": "floodgate.review/v1",
  "created": "2026-05-24T22:23:04+00:00",
  "updated": "2026-05-24T22:23:09+00:00",
  "base":   { "rev": "main",    "commit": "<base tip sha>" },
  "target": { "rev": "feature", "commit": "<target tip sha>" },
  "merge_base": "<sha>",
  "mode": "three-dot",
  "marks": {
    "ca84b7f8787a": { "status": "rejected", "path": "src/a.py", "at": "…" }
  }
}
```

Each mark stores the path and timestamp alongside the status, so the file stays
readable and `floodgate status` can summarize without re-running git.
