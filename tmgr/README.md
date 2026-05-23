# tmgr — a small tmux session manager

`tmgr` wraps your usual `tmux new -s` / `tmux a -t` workflow with two things:

- **fuzzy switching** via `fzf`, and
- a per-session **`.session` file** (TOML) under `~/.tools/tmgr/` recording when
  the session was created and an optional, possibly multi-line, **description**.

It's a single self-contained Python 3.11+ script — no third-party packages.

## Install

The script lives at `tmgr/tmgr` in this repo. Symlink it onto your `PATH`:

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
| `tmgr a` | Fuzzy-pick a **running** session and attach/switch to it. |
| `tmgr log [text]` | Append `text` to the **current** session's log (must be run inside tmux). |
| `tmgr ls` | List tracked sessions plus their run state. |

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

### `tmgr a`

Lists every running tmux session. Sessions with a `.session` file show their
description's first line in the list and the full description (plus created time,
window count and attach state) in the `fzf` preview pane. Sessions started with
plain `tmux new` appear too, marked *untracked*.

If you're **inside** tmux, `tmgr a` and `tmgr new` use `switch-client` instead
of `attach` (you can't nest `tmux attach`).

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
menu's rename option `(n)` moves them together.
