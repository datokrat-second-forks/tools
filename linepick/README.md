# linepick

Fill the target of a `[[...]]` **wiki link** under your cursor in Vim by picking
from an interactive menu (fzf by default), with per-**type** menus.

Press a key in Vim on a link and `linepick` rewrites the line:

| Link under cursor | After picking |
| --- | --- |
| `[[note]]` | `[[note\|chosen/file.md]]` — fzf file picker, inserts `\|path` |
| `[[note\|?]]` | `[[note\|chosen/file.md]]` — fzf replaces the `?` placeholder |
| `[[session:?]]` | `[[session:mysession]]` — the `session` handler picks the value |
| `[[name\|session:?]]` | `[[name\|session:mysession]]` — same, `name\|` preserved |

The part after an optional `name|` is the **target**. If it begins `type:`, the
`type` selects a dedicated menu (and is kept); otherwise the whole target is
filled by the default picker. The cursor lands just past the link. Off a link,
or if you cancel the menu, the line is left unchanged.

## How it fits together

```
Vim (linepick.vim)  --JSON-->  linepick  --type-->  linepick-<type>  (e.g. fzf)
   <leader>f                   (parser)             (the menu)
```

- **`linepick.vim`** maps a key to send the current line + cursor column to the
  tool as JSON and apply the JSON reply (see [linepick.vim](linepick.vim)).
- **`linepick`** finds the link under the cursor, parses out `type`, dispatches,
  and splices the result back in.
- **`linepick-<type>`** is a small executable that shows a menu and prints the
  chosen value. `linepick-session` ships as an example.

## Install

`linepick` is a single Python 3 script (stdlib only); the handlers are tiny
shell scripts. Put this directory on your `PATH` so `linepick` and its handlers
are found:

```sh
ln -s "$PWD/linepick/linepick"         ~/.local/bin/linepick
ln -s "$PWD/linepick/linepick-session" ~/.local/bin/linepick-session
```

Then source the Vim glue from your `vimrc` (after any `let mapleader=...`):

```vim
source /path/to/linepick/linepick.vim
```

That maps `<Leader>f`. To choose your own key, bind `<Plug>(LinePick)`:

```vim
nmap <silent> <F4> <Plug>(LinePick)
```

Requirements: `fzf` for the default file picker; whatever each type handler
needs (e.g. `linepick-session` calls [`tmgr`](../tmgr) and `fzf`).

## Extending it: add a new type

A type `foo` is handled by an executable named **`linepick-foo`**. `linepick`
looks for it in `$LINEPICK_HANDLER_DIR`, then next to the `linepick` script,
then on `$PATH`. The contract is tiny:

- **Input:** the link's current target value is passed as **`$1`** (e.g. `?` for
  a fresh `[[foo:?]]`, or the existing value when re-picking). Use it to
  pre-seed your menu, or ignore it.
- **Output:** print the chosen value to **stdout**. It replaces the part after
  `foo:`, so `[[foo:$1]]` becomes `[[foo:<stdout>]]`.
- **Cancel:** exit non-zero or print nothing — `linepick` then leaves the line
  unchanged.
- **UI:** draw your menu on `/dev/tty` (fzf does this automatically). Only
  stdout carries the result.

Example — a `ticket` type backed by a fictional `issues` CLI:

```sh
#!/usr/bin/env bash
# linepick-ticket — pick an issue id for [[ticket:...]] links.
issues list --format='%id\t%title' | fzf --with-nth=2.. | cut -f1
```

```sh
chmod +x linepick-ticket && ln -s "$PWD/linepick-ticket" ~/.local/bin/
```

Now `[[ticket:?]]` under the cursor opens that menu and fills in the chosen id.
The shipped `linepick-session` is a one-liner that delegates to `tmgr pick`, and
forwards `$1` as `--query` so re-picking an existing `[[session:name]]` starts
with that session selected — a good template to copy.

### The default (typeless) picker

Untyped targets (`[[name|path]]`, `[[name]]`) and unknown types fall back to the
command in **`$LINEPICK_PICKER`** (default `fzf`), whose stdout fills the target.

## Tests

```sh
python3 test_linepick.py     # unit tests for parsing, cursor math, dispatch
./test_vim.sh                # end-to-end through headless Vim (compatible + nocompatible)
```

`test_vim.sh` and the CLI tests stub the menu (via `$LINEPICK_PICKER` /
`$LINEPICK_HANDLER_DIR`), so they run without a terminal or `fzf`.
