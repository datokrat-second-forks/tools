# leansnip

Manage your VSCode **Lean 4 snippets** from a single git repo.

Your snippets live in one file, `lean4.json`, inside a git repo you own. Because
the file is named `lean4.json`, VSCode treats it as a *language-scoped* user
snippet for the Lean 4 extension's `lean4` language id — it applies to every
`.lean` file, in every workspace, with no per-snippet `scope` needed.

`leansnip` wires that repo into VSCode by **symlinking** it into each installed
editor's user-snippets directory:

```
<editor>/User/snippets/lean4.json  ->  <repo>/lean4.json
```

Since it's a symlink, editing snippets through VSCode's built-in **Configure
Snippets** UI writes *straight back* into the git-tracked file. The repo is the
single source of truth no matter how you edit; `leansnip add` / `rm` just give
you a command-line way to do the same edits.

## Install

```sh
./install.sh                 # adds this dir to your PATH in ~/.bashrc
source ~/.bashrc
```

Requires Python 3 (stdlib only) and `git`. The snippets repo is separate from
this tool — create it (or use an existing one) yourself; `leansnip` only points
at it.

## Quick start

```sh
leansnip repo /configs       # remember which repo holds lean4.json
leansnip link                # symlink it into every installed editor
leansnip add "Sorry" --prefix sry --body sorry --desc "leave a hole"
leansnip ls                  # list what you have
leansnip sync                # git pull --rebase --autostash && git push
```

A multi-line body — type the snippet, end with Ctrl-D (tab stops `$1`, `$0` and
placeholders `${1:foo}` work as in any VSCode snippet):

```sh
leansnip add "Lemma" --prefix lem <<'EOF'
lemma $1 : $2 := by
  $0
EOF
```

## Commands

| Command | What it does |
| --- | --- |
| `leansnip repo [PATH]` | Show, or set, the snippets repo path (saved in `~/.tools/leansnip/config`, matching `tmgr`). |
| `leansnip link` | Symlink `lean4.json` into every installed VSCode-family editor. Backs up any real file already there; creates an empty `lean4.json` if the repo has none yet. |
| `leansnip unlink` | Remove leansnip's symlinks (never deletes a real file). |
| `leansnip status` | Repo path, snippet count, git state, and per-editor link state. |
| `leansnip ls` | List snippets as name / prefix / description. |
| `leansnip add NAME [--prefix P] [--desc D] [--body LINE ...]` | Add a snippet. Body comes from repeated `--body` lines or from stdin. `--prefix` defaults to the name. |
| `leansnip rm NAME` | Remove a snippet by name. |
| `leansnip edit` | Open `lean4.json` in `$EDITOR`, then validate it's still JSON. |
| `leansnip sync` | `git pull --rebase --autostash` then `git push` in the repo. |

`add` / `rm` parse and rewrite `lean4.json` as **strict JSON** (no comments or
trailing commas). Edit by hand or via VSCode if you want full control.

### Editors and overrides

`link` / `unlink` / `status` auto-detect installed editors by looking for a
`User` directory under the platform config root:

- Linux: `~/.config/<editor>/User` (honours `$XDG_CONFIG_HOME`)
- macOS: `~/Library/Application Support/<editor>/User`
- Windows: `%APPDATA%\<editor>\User`

…for `Code`, `Code - Insiders`, `Code - OSS`, `VSCodium`, `Cursor`, and
`Windsurf`. Pass `--dir <snippets-dir>` to target an explicit location instead.

The repo can also be overridden ad hoc with `--repo PATH` or the
`$LEANSNIP_REPO` environment variable, which take precedence over the saved
config.

## Tests

```sh
python3 test_leansnip.py
```

Stdlib `unittest` only.
