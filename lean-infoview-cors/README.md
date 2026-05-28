# lean-infoview-cors

Patches the Lean 4 VS Code extension so its InfoView stylesheet loads under
code-server.

## Why

The Lean InfoView is rendered in an iframe whose `<link rel="stylesheet">`
points at a `vscode-cdn.net` URL derived from the host serving VS Code. When
you reach VS Code over the network (typically via code-server on a remote
machine), the browser refuses to apply that stylesheet without an explicit
`crossorigin` attribute on the link, and the InfoView shows up unstyled. The
fix is to add `crossorigin="anonymous"` to that one tag.

This tool does exactly that: it edits the bundled `extension.js` shipped by
the latest installed `leanprover.lean4` extension to insert the attribute.
The patch is idempotent — re-running is a no-op — but it must be reapplied
after every extension upgrade, since upgrades replace the bundled file.

## Install

```sh
./install.sh
source ~/.bashrc      # or open a new shell
```

This just appends an `export PATH=...` line to `~/.bashrc`.

## Use

```sh
lean-infoview-cors            # patch the newest installed version
lean-infoview-cors --status   # list installed versions and patch state
lean-infoview-cors --dir DIR  # override the extensions directory
```

The default extensions directory is `~/.local/share/code-server/extensions`.
For desktop VS Code, pass `--dir ~/.vscode/extensions`.

## Caveat

This edits a file inside the extension's install directory. The next time
the extension auto-updates, the file is overwritten and you need to run the
tool again. If your environment auto-updates extensions on launch, consider
wiring this into a post-launch hook.
