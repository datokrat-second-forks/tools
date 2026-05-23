# diffkit — structured Git diffs you can filter and render

Three small, composable CLI tools for turning a Git diff into something you can
machine-filter before reading it:

```
structured-diff main feature \
  | filter-diff --exclude --trim-whitespace "lorem ipsum" \
  | render-diff out.html
```

- **`structured-diff`** runs `git diff` and emits it as one JSON document.
- **`filter-diff`** keeps or drops changed lines by pattern, pruning empty
  hunks and files.
- **`render-diff`** renders that JSON into a self-contained, unified-view HTML
  page.

The motivating case: two branches differ mostly by the same trivial insertion
(say `lorem ipsum`, with assorted leading/trailing whitespace), and you only
want to see the *interesting* changes. Exclude the noise in the middle and
render the rest.

They're self-contained Python 3.11+ scripts — no third-party packages. The
three scripts share `_diffcommon.py` (the JSON schema and the `git diff`
parser); each resolves its own real directory to import it, so symlinking the
scripts onto your `PATH` works fine.

## Install

```sh
# from the repo root
for t in structured-diff filter-diff render-diff; do
  ln -s "$PWD/diffkit/$t" ~/.local/bin/$t
done
```

Requirement: `git` (only `structured-diff` shells out to it).

## `structured-diff`

```
structured-diff [-C DIR] [-U N] [--no-renames] [--pretty] [REVS...]
```

Everything after the options is passed straight through to `git diff`, so the
full revision/pathspec surface is available:

```sh
structured-diff main feature          # diff main..feature
structured-diff main..feature         # range form
structured-diff --cached              # staged changes
structured-diff -C ~/proj HEAD~3 HEAD -- src/   # restrict to a pathspec
```

| Option | Meaning |
| --- | --- |
| `-C, --directory DIR` | run git in `DIR` (default: cwd) |
| `-U, --unified N` | context lines per hunk (default: 3) |
| `--no-renames` | disable rename detection (on by default, via `-M`) |
| `--pretty` | indent the JSON (default: compact, one line) |

Output goes to stdout. Rename detection is on by default; renames appear with
`status: "renamed"` and a `similarity` percentage.

## `filter-diff`

```
filter-diff [-v] [-F] [-x] [-i] [--trim-whitespace] [--side ...] PATTERN
```

Reads a diff document on stdin, tests `PATTERN` against **changed**
(added/removed) lines, and writes the filtered document to stdout. Context
lines are always retained; a hunk with no remaining changes is dropped, and a
file that *had* changes but no longer does is dropped too (structural-only
changes such as renames or mode changes are kept).

Matching follows `grep` conventions:

| Option | Meaning |
| --- | --- |
| *(default)* | lines that **match** are kept |
| `-v, --exclude` | invert: drop the matches instead (like `grep -v`) |
| `-F, --fixed-strings` | treat `PATTERN` as a literal string, not a regex |
| `-x, --line-regexp` | require the match to span the whole line |
| `-i, --ignore-case` | case-insensitive |
| `--trim-whitespace` | strip leading/trailing whitespace before matching |
| `--side {both,added,removed}` | which changed lines to test (default: both) |
| `--keep-empty-files` | keep files even after all their changes are removed |
| `--pretty` | indent the JSON output |

So the headline example — *"hide insertions that are just `lorem ipsum` once
you ignore surrounding whitespace"* — is:

```sh
filter-diff --exclude --trim-whitespace "lorem ipsum"
```

> Note: filtering removes individual changed lines, so the result is meant for
> *viewing*, not for `git apply`. `filter-diff` recomputes each hunk's `@@`
> line counts to match the lines it kept.

## `render-diff`

```
render-diff [OUTPUT]      # or: render-diff -o OUTPUT
```

Reads a diff document on stdin and writes a unified-view HTML page (embedded
CSS, no external assets). With no argument it writes to stdout; otherwise it
writes the file and prints a one-line summary to stderr. Each file is a
collapsible section with status badge; added lines are green, removed red,
context plain. HTML in the diff content is escaped, and a missing trailing
newline is flagged inline.

## The JSON schema (`diffkit.diff/v1`)

A single object: `{schema, old, new, files[]}`. Each file has
`old_path`/`new_path` (null against `/dev/null`), a `status`
(`added`/`deleted`/`modified`/`renamed`/`copied`/`mode`), modes, a `similarity`
percent for renames/copies, a `binary` flag, and `hunks[]`. Each hunk carries
its `@@` line numbers, the section heading, and `lines[]`; each line has a
`kind` (`context`/`add`/`del`), the `text` (no leading `+`/`-`/space), and the
`old_lineno`/`new_lineno` it sits at. See the docstring in `_diffcommon.py` for
the full shape — any tool that emits this schema can feed `filter-diff` and
`render-diff`.
