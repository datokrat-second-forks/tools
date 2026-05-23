# tools

A personal collection of small command-line tools. Each tool lives in its own
directory with its own `README.md`.

## Tools

| Tool | Description |
| --- | --- |
| [`tmgr`](tmgr/) | A small tmux session manager: fuzzy-switch between sessions with `fzf`, and track each one with a `.session` file (creation time + description). |

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
