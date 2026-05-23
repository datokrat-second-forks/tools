"""Shared code for the diffkit tools (structured-diff, filter-diff, render-diff).

Holds the JSON diff *schema*, a parser that turns `git diff` text into that
schema, and a few small stdin/stdout helpers. Not meant to be run directly; the
three scripts add their own directory to ``sys.path`` and ``import _diffcommon``
(this keeps working when the scripts are symlinked onto ``$PATH``).

The schema is a single JSON object:

    {
      "schema": "diffkit.diff/v1",
      "old": <str|null>,            # label for the "old" side (e.g. a branch)
      "new": <str|null>,            # label for the "new" side
      "files": [
        {
          "old_path": <str|null>,   # null for an added file (/dev/null)
          "new_path": <str|null>,   # null for a deleted file (/dev/null)
          "status": "added"|"deleted"|"modified"|"renamed"|"copied"|"mode",
          "old_mode": <str|null>,
          "new_mode": <str|null>,
          "similarity": <int|null>, # percent, for renamed/copied
          "binary": <bool>,
          "hunks": [
            {
              "old_start": <int>, "old_count": <int>,
              "new_start": <int>, "new_count": <int>,
              "section": <str>,     # text after the second "@@"
              "lines": [
                {
                  "kind": "context"|"add"|"del",
                  "text": <str>,            # line content, no leading +/-/space
                  "old_lineno": <int|null>,
                  "new_lineno": <int|null>,
                  "no_newline": true        # present only when the file lacks a
                                            # trailing newline at this line
                }
              ]
            }
          ]
        }
      ]
    }
"""

import json
import re
import sys

SCHEMA = "diffkit.diff/v1"

HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: (.*))?$"
)


# --------------------------------------------------------------------------- #
# stdin / stdout / errors
# --------------------------------------------------------------------------- #
def die(prog, msg, code=1):
    print(f"{prog}: {msg}", file=sys.stderr)
    sys.exit(code)


def read_doc(prog):
    """Read and parse a diffkit JSON document from stdin."""
    data = sys.stdin.read()
    if not data.strip():
        die(prog, "no input on stdin (pipe in `structured-diff` output)")
    try:
        doc = json.loads(data)
    except json.JSONDecodeError as e:
        die(prog, f"stdin is not valid JSON: {e}")
    if not isinstance(doc, dict) or "files" not in doc:
        die(prog, "stdin is not a diffkit diff document (no `files` key)")
    schema = doc.get("schema")
    if schema and not str(schema).startswith("diffkit.diff/"):
        print(f"{prog}: warning: unexpected schema {schema!r}", file=sys.stderr)
    return doc


def write_doc(doc, stream=None, pretty=False):
    stream = stream or sys.stdout
    if pretty:
        json.dump(doc, stream, indent=2, ensure_ascii=False)
    else:
        json.dump(doc, stream, separators=(",", ":"), ensure_ascii=False)
    stream.write("\n")


# --------------------------------------------------------------------------- #
# git diff parsing
# --------------------------------------------------------------------------- #
def _unquote(s):
    """Undo git's C-style path quoting (best effort)."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        try:
            return inner.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception:
            return (inner.replace('\\"', '"').replace("\\t", "\t")
                         .replace("\\n", "\n").replace("\\\\", "\\"))
    return s


def _hdr_path(s):
    """Path from a `--- ` / `+++ ` line: strip a/ b/ prefix, handle /dev/null."""
    if "\t" in s:                       # git may append a tab + timestamp
        s = s.split("\t", 1)[0]
    s = _unquote(s.rstrip())
    if s == "/dev/null":
        return None
    if s.startswith("a/") or s.startswith("b/"):
        s = s[2:]
    return s


def _split_diff_git(header):
    """Fallback path extraction from a `diff --git a/old b/new` line."""
    rest = header[len("diff --git "):]
    if rest.startswith("a/"):
        idx = rest.find(" b/")
        if idx != -1:
            return _unquote(rest[2:idx]), _unquote(rest[idx + 3:])
    return rest, rest


def _parse_hunk(lines, i):
    m = HUNK_RE.match(lines[i])
    hunk = {
        "old_start": int(m.group(1)),
        "old_count": int(m.group(2)) if m.group(2) is not None else 1,
        "new_start": int(m.group(3)),
        "new_count": int(m.group(4)) if m.group(4) is not None else 1,
        "section": m.group(5) or "",
        "lines": [],
    }
    old_no, new_no = hunk["old_start"], hunk["new_start"]
    i += 1
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line or line.startswith("@@") or line.startswith("diff --git "):
            break
        tag, text = line[0], line[1:]
        if tag == "+":
            hunk["lines"].append({"kind": "add", "text": text,
                                  "old_lineno": None, "new_lineno": new_no})
            new_no += 1
        elif tag == "-":
            hunk["lines"].append({"kind": "del", "text": text,
                                  "old_lineno": old_no, "new_lineno": None})
            old_no += 1
        elif tag == " ":
            hunk["lines"].append({"kind": "context", "text": text,
                                  "old_lineno": old_no, "new_lineno": new_no})
            old_no += 1
            new_no += 1
        elif tag == "\\":               # "\ No newline at end of file"
            if hunk["lines"]:
                hunk["lines"][-1]["no_newline"] = True
        else:
            break
        i += 1
    return hunk, i


def _parse_file(lines, i):
    f = {"old_path": None, "new_path": None, "status": "modified",
         "old_mode": None, "new_mode": None, "similarity": None,
         "binary": False, "hunks": []}
    header = lines[i]
    i += 1
    n = len(lines)
    is_new = is_deleted = is_rename = is_copy = False

    # Extended headers, until the body (---/+++/@@) or the next file.
    while i < n:
        line = lines[i]
        if line.startswith("diff --git ") or line.startswith("@@"):
            break
        if line.startswith("--- "):
            f["old_path"] = _hdr_path(line[4:])
        elif line.startswith("+++ "):
            f["new_path"] = _hdr_path(line[4:])
        elif line.startswith("new file mode "):
            is_new = True
            f["new_mode"] = line[len("new file mode "):].strip()
        elif line.startswith("deleted file mode "):
            is_deleted = True
            f["old_mode"] = line[len("deleted file mode "):].strip()
        elif line.startswith("old mode "):
            f["old_mode"] = line[len("old mode "):].strip()
        elif line.startswith("new mode "):
            f["new_mode"] = line[len("new mode "):].strip()
        elif line.startswith("rename from "):
            is_rename = True
            f["old_path"] = _unquote(line[len("rename from "):])
        elif line.startswith("rename to "):
            is_rename = True
            f["new_path"] = _unquote(line[len("rename to "):])
        elif line.startswith("copy from "):
            is_copy = True
            f["old_path"] = _unquote(line[len("copy from "):])
        elif line.startswith("copy to "):
            is_copy = True
            f["new_path"] = _unquote(line[len("copy to "):])
        elif line.startswith("similarity index "):
            mm = re.search(r"(\d+)", line)
            if mm:
                f["similarity"] = int(mm.group(1))
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            f["binary"] = True
        i += 1

    while i < n and lines[i].startswith("@@"):
        hunk, i = _parse_hunk(lines, i)
        f["hunks"].append(hunk)

    if f["old_path"] is None and f["new_path"] is None and not (is_new or is_deleted):
        f["old_path"], f["new_path"] = _split_diff_git(header)

    if is_rename:
        f["status"] = "renamed"
    elif is_copy:
        f["status"] = "copied"
    elif is_new:
        f["status"] = "added"
    elif is_deleted:
        f["status"] = "deleted"
    elif f["old_mode"] and f["new_mode"] and not f["hunks"]:
        f["status"] = "mode"
    else:
        f["status"] = "modified"
    return f, i


def parse_git_diff(text):
    """Parse the text of `git diff` into a list of file records (see SCHEMA)."""
    lines = text.split("\n")
    files = []
    i, n = 0, len(lines)
    while i < n:
        if lines[i].startswith("diff --git "):
            f, i = _parse_file(lines, i)
            files.append(f)
        else:
            i += 1
    return files


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def count_changes(doc):
    """Return (n_files, n_additions, n_deletions) over the whole document."""
    adds = dels = 0
    for f in doc.get("files", []):
        for h in f.get("hunks", []):
            for ln in h.get("lines", []):
                if ln["kind"] == "add":
                    adds += 1
                elif ln["kind"] == "del":
                    dels += 1
    return len(doc.get("files", [])), adds, dels
