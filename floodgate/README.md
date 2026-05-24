# floodgate — review a branch diff in your browser, with persistent marks

`floodgate` helps you review the difference between two branches before merging.
It serves a rendered HTML diff on a local HTTP server where you accept, reject,
or skip each change; the marks are saved to a `.review` file in the current
directory, so you can stop and resume later. Bulk-marking is done by piping
through diffkit's `filter-diff`.

```sh
floodgate review main feature        # open the diff in your browser
floodgate diff | filter-diff --substring "TODO" | floodgate reject   # bulk-mark
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
floodgate review [--continue] [-C DIR] [--only STATUSES | --hide STATUSES]
                 [--two-dot] [--host HOST] [-p PORT] [--no-open] [BASE TARGET]
```

| Option | Meaning |
| --- | --- |
| `--continue` | resume the review recorded in `./.review` — no `BASE`/`TARGET` needed |
| `-C, --directory DIR` | git repo to diff (default: cwd) |
| `--only STATUSES` | show only entries with these statuses (comma-separated: `accepted,rejected,skipped,unreviewed`) |
| `--hide STATUSES` | hide entries with these statuses (comma-separated) |
| `--two-dot` | diff `base..target` (the two tips) instead of the default `base...target` (changes on `target` since the merge-base) |
| `--host HOST` | address to bind (default: `127.0.0.1`; use `0.0.0.0` to reach it from outside the container floodgate runs in) |
| `-p, --port N` | port to serve on (default: 8765; tries the next few if busy) |
| `--no-open` | don't open a browser automatically |

`BASE` and `TARGET` are required unless you pass `--continue`, which reads them
(and the diff mode) back from `./.review` so you don't have to retype the
branches between sessions. `--continue` can't be combined with `BASE`/`TARGET`
or `--two-dot` (both come from the file).

By default floodgate uses **three-dot** (`base...target`) semantics — the same
as a GitHub pull request: it shows what `target` introduces relative to the
common ancestor, not unrelated changes that landed on `base` since. Use
`--two-dot` to compare the two branch tips directly.

#### Filtering the view (`--only` / `--hide`)

`--only` and `--hide` restrict which entries the page shows, by review status —
the counts in the header still reflect the full totals. The unit is the hunk, so
a file is shown whenever any of its hunks is; a file all of whose hunks are
filtered out drops away entirely. The two flags are mutually exclusive.

The motivating workflow is *bulk-accept, then focus on the rest*:

```sh
floodgate diff | filter-diff --substring "vendor/" | floodgate accept
floodgate review main feature --hide accepted      # only what's left to look at
```

When a filter is active, marking an entry into a hidden status (e.g. accepting
something while `--hide accepted`) makes it drop out of view immediately, so the
list shrinks as you work.

If floodgate runs **inside a container** and you want to open the diff in a
browser on the host, bind all interfaces and publish the port:

```sh
floodgate review main feature --host 0.0.0.0 --no-open    # then browse host:8765
```

The server has no authentication, so only bind a non-loopback address on a
trusted network.

Running `review` again for the same pair resumes it (marks are kept). Running it
for a *different* pair prompts before discarding the existing `.review`.

## The bulk-marking pipeline

`floodgate diff` embeds a stable `review_id` on every hunk *inside the diffkit
JSON*. `filter-diff` passes that field through untouched while it selects a
subset, so the marking commands just read the ids off their stdin — no fragile
re-matching:

```sh
# filter-diff defaults to a literal, whole-line, whitespace-trimmed match;
# add --substring to match anywhere in a line.
floodgate diff | filter-diff --substring "TODO"       | floodgate reject
floodgate diff | filter-diff --substring "console.log" | floodgate skip
floodgate diff | filter-diff --exclude "lorem ipsum"  | floodgate accept  # whole line
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

## Tests

A stdlib `unittest` suite (no third-party packages) covers review-id derivation,
annotation/roll-up, marks, the `--only`/`--hide` resolver, and HTML rendering
(including the view filter), plus a few CLI integration tests through a real git
repo + diffkit:

```sh
python3 test_floodgate.py        # or: python3 -m unittest -v
```

The integration tests are skipped if `git` or diffkit's `structured-diff` isn't
available.
