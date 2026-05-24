# tools

A personal collection of small command-line tools. Each tool lives in its own
directory with its own `README.md`.

Note: I'm using these inside a heavily restrained sandbox, and they were developed using an LLM. Use at your own risk.

## Tools

| Tool | Description |
| --- | --- |
| [`tmgr`](tmgr/) | A small tmux session manager: fuzzy-switch between sessions with `fzf` (most-recently-used first), attach by name, and remove stale ones; tracks each with a `.session` file (creation time + description) and an optional `.sessionlog`. |
| [`diffkit`](diffkit/) | Three composable tools for Git diffs: `structured-diff` emits a diff as JSON, `filter-diff` keeps/drops changed lines by pattern, and `render-diff` turns the result into a unified-view HTML page. |
| [`floodgate`](floodgate/) | Review a branch diff in the browser: serves an HTML diff with per-hunk accept/reject/skip buttons, persists marks to a `.review` file so reviews are resumable, and supports bulk-marking via diffkit's `filter-diff`. |

## Layout

```
tools/
├── README.md        # this file
└── <tool>/          # one directory per tool
    ├── README.md     # how to install and use that tool
    └── ...           # the tool's script(s)
```

## Adding a tool

Create a new directory named after the tool, drop the script(s) in it, and add a
`README.md` describing how to install and use it. Then list it in the **Tools**
table above.
