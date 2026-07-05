# impgraph — analyze the Lean 4 module import graph

`impgraph` answers questions about how Lean 4 modules import one another,
straight from the source tree — no build required. It was written to vet the
cost of adding an `import` to a low-level module: how much does that module's
own dependency closure grow, does the new import create a cycle, and which
downstream modules end up depending on the newcomer?

A *module* is a dotted name like `Lean.AddDecl`, mapped to the file
`<root>/Lean/AddDecl.lean`. The root defaults to `./src` when it exists (the
layout of a lean4 checkout), otherwise to `.`; override it with `--root`.

Imports are parsed syntactically, tolerating `public` / `meta` modifiers and
`import all`. Text inside block comments and ```-fenced docstring examples is
ignored, so a `public import Lean` shown in a docstring is not mistaken for a
real edge.

## Public vs. build edges

Every command takes a global `--public` flag:

- **default (build):** follow *every* import. This is the build-order
  dependency graph — a module cannot compile until each module it imports is
  built.
- **`--public`:** follow only `public import` edges. This is the transitive
  *visibility* graph — what a downstream module actually sees (and depends on
  for its interface) through a module. A plain private `import` is invisible
  here.

The gap between the two is exactly the footprint that private imports keep
contained.

## Commands

### `impgraph impact <module> --add MODS [--remove MODS]`

The headline command. Models adding (and/or removing) imports on `<module>`
without touching the file, and reports:

- **closure before/after** and the **new modules** pulled into `<module>`'s own
  dependency closure;
- a **CYCLE** warning, with the offending path, if any added import already
  (transitively) imports `<module>`;
- the **downstream** footprint: of all modules that import `<module>`, how many
  already reached each added module, and how many *newly gain* it because of the
  change.

`--add`/`--remove` accept comma- or space-separated lists and may be repeated.
An added import is treated as a private `import` by default; prefix it with
`public:` (e.g. `--add public:Lean.Foo`) to model a `public import`.

```
$ impgraph impact Lean.AddDecl --add Lean.Meta.Check,Lean.Meta.Instances
module: Lean.AddDecl
  mode:   build (all imports)
  add:    Lean.Meta.Check, Lean.Meta.Instances

closure before: 515
closure after:  538
new in closure: 23
  + Lean.Meta.Check
  + Lean.Meta.Instances
  ...

downstream: 773 modules transitively import Lean.AddDecl
  Lean.Meta.Check: already had 699/773, 74 newly gain it
  Lean.Meta.Instances: already had 753/773, 20 newly gain it
```

Run it again with `--public` to see how much of that is real interface
footprint: with private adds, the downstream `newly gain` columns drop to 0.

Exit status is `1` when a cycle is detected, else `0`.

### `impgraph closure <module> [--count]`

The transitive import closure of `<module>` (one module per line, or just the
count with `--count`).

### `impgraph path <from> <to>`

A shortest import path `from -> ... -> to`, or a notice that none exists. Handy
for cycle-checking by hand: `impgraph path A B` and `impgraph path B A`. Exit
status is `1` when there is no path.

### `impgraph importers <module> [--count]`

Every module that transitively imports `<module>`.

All commands also accept `--json` for scripting.

## Install

```sh
./install.sh    # appends this directory to PATH in ~/.bashrc
```

Requires Python 3 (stdlib only).

## Tests

```sh
python3 test_impgraph.py
```

The tests build a small fake source tree in a temp dir, so they run offline and
touch no real checkout.
