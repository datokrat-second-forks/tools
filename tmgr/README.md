# tmgr — a small tmux session manager

`tmgr` wraps your usual `tmux new -s` / `tmux a -t` workflow with two things:

- **fuzzy switching** via `fzf`, and
- a per-session **`.session` file** (TOML) under `~/.tools/tmgr/` recording when
  the session was created and an optional, possibly multi-line, **description**.

It's a single self-contained Python 3.11+ script — no third-party packages.

## Install

Run the bundled script, which adds this directory to your `PATH` via `~/.bashrc`
(idempotent — it won't add a duplicate line if already present):

```sh
./install.sh
source ~/.bashrc   # or open a new shell
```

Or symlink the script onto your `PATH` yourself:

```sh
ln -s "$PWD/tmgr/tmgr" ~/.local/bin/tmgr   # run from the repo root
```

Requirements:

- `tmux` (required)
- `fzf` (recommended; `tmgr a` falls back to a numbered list without it)
- `vim` / `$EDITOR` for `tmgr edit`

## Commands

| Command | What it does |
| --- | --- |
| `tmgr new <name> [-m DESC]` | Create a tracked session and attach to it. |
| `tmgr edit <name>` | Open `<name>.session` in `$EDITOR` (default `vim`). |
| `tmgr a [name]` | Attach to `name` directly, or fuzzy-pick a **running** session if no name is given. |
| `tmgr rm <name>` | Delete a **non-running** session's tracking files, after a confirmation showing its description. |
| `tmgr log [text]` | Append `text` to the **current** session's log (must be run inside tmux). |
| `tmgr logs [name]` | Show a session log: fuzzy-pick one with `fzf`, or pass a name. |
| `tmgr ls [--all]` | List **running** sessions; `--all` also shows remnants (tracked but not running). |

Session names must match `^[A-Za-z0-9][A-Za-z0-9-]*$` (letters, digits and `-`,
starting alphanumeric — which also keeps tmux happy, since it forbids `.`/`:`).

### `tmgr new <name>`

- **Clean slate** → writes `~/.tools/tmgr/<name>.session` and runs the
  equivalent of `tmux new -s <name>`.
- **A session of that name is already running** → short menu:
  `(a)` attach to it · `(d)` pick a different name · `(q)` quit.
  Attaching also writes a tracking file if the session didn't have one.
- **A `.session` file exists but no live session** (a *remnant* of a session
  that already terminated) → you're warned and offered:
  - `(q)` quit
  - `(k)` keep the file, start a new tmux session
  - `(r)` reset the file (fresh timestamp/description), start a new session
  - `(o)` keep the old file, choose a different name for the new session
  - `(n)` keep the new session under this name; rename the old file to a name
    **you choose** (its created time, description **and `.sessionlog`** are
    preserved/moved with it)

### `tmgr a [name]`

With a `name`, attaches (or, inside tmux, switches) straight to that session,
skipping the picker; it errors if no session of that name is running.

With no argument, lists every running tmux session, **most-recently-attached
first**, so the session you just left sits under the cursor. Each row carries a
compact age column (`16s`, `2m`, `1h`, `3d`) showing how long ago you were last
in it. Sessions with a `.session` file show their description's first line in
the list and the full description (plus created time, window count, attach state
and last-attached age) in the `fzf` preview pane. Below the description, the
preview tacks on the last ~20 lines of the session's active pane (via `tmux
capture-pane`), so you can see at a glance what's actually happening in there.
Sessions started with plain `tmux new` appear too, marked *untracked* — they
get the tail in their preview as well.

If you're **inside** tmux, `tmgr a` and `tmgr new` use `switch-client` instead
of `attach` (you can't nest `tmux attach`).

### `tmgr rm <name>`

Deletes a session's tracking files — its `.session` and, if present, its
`.sessionlog`. It first prints the files to be removed along with the session's
created time and description, then asks for a `y/n` confirmation. It refuses if a
tmux session of that name is currently **running** (kill it first), so it only
ever clears out remnants. This is the one command that deletes `.session` files;
nothing else removes them automatically.

### `tmgr log [text]`

Appends a timestamped entry to `~/.tools/tmgr/<current-session>.sessionlog`.
It only works **inside** a tmux session — the session name is read from the
current pane (via `tmux display-message`), so you don't pass it explicitly.

```sh
tmgr log fixed the off-by-one in the lexer
echo "longer note from a script" | tmgr log      # text can come from stdin
```

The log doesn't need a `.session` file — you can log from an untracked session
too. Entries look like `[2026-05-23 17:20] fixed the off-by-one in the lexer`,
and `tmgr a`'s preview shows the entry count and most recent line.

### `tmgr logs [name]`

Shows a session log. With no argument it opens an `fzf` picker over every
session that has a `.sessionlog`, with the full log scrollable in the preview
pane; selecting one prints it to stdout. Pass a `name` to print that log
directly and skip the picker. Without `fzf` it falls back to a numbered list.

```sh
tmgr logs            # browse logs with fzf
tmgr logs myproj     # print myproj's log straight away
tmgr logs myproj | less
```

## The `.session` file

```toml
name = "myproj"
created = 2026-05-23T16:00:00+00:00
description = """
Refactor the parser.
Remember to run the integration suite before merging.
"""
```

`tmgr edit` validates the TOML after you save and offers to re-open it if you
introduced a syntax error. The file is *not* removed when the tmux session ends —
that surviving file is what becomes a "remnant" and drives the `new` menu above.

Alongside it, `tmgr log` may create a plain-text `<name>.sessionlog`. Neither
file is ever auto-deleted; both are kept for future reference, and the `new`
menu's rename option `(n)` moves them together. The only command that removes
them is `tmgr rm`, which deletes both at once after you confirm.
