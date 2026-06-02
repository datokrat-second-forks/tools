#!/usr/bin/env bash
# End-to-end: drive LinePick() in headless vim against the real linepick tool,
# with $LINEPICK_PICKER stubbing fzf (so no terminal is needed). Asserts the
# wiki-link path is filled in and the cursor moves just past the link.
#
# Runs under both 'nocompatible' AND 'compatible' — the latter is how the file
# is sourced from a --cmd before the vimrc, where '\' line continuations break.
set -euo pipefail
cd "$(dirname "$0")"

export LINEPICK_PICKER="printf 'notes/foo.md'"

check() { # $1 = label, rest = extra vim args establishing the mode
  local label="$1"; shift
  local out; out=$(mktemp)
  vim -es -u NONE "$@" \
    --cmd 'source linepick.vim' \
    -c 'call setline(1, "see [[note|?]] here")' \
    -c 'call cursor(1, 8)' \
    -c 'call LinePick()' \
    -c "call writefile([getline(1), string(col('.'))], '$out')" \
    -c 'qa!' </dev/null
  local got; mapfile -t got < "$out"; rm -f "$out"
  [ "${got[0]}" = "see [[note|notes/foo.md]] here" ] \
    || { echo "FAIL [$label] line: '${got[0]}'"; exit 1; }
  [ "${got[1]}" = "26" ] \
    || { echo "FAIL [$label] col: '${got[1]}' (want 26, the space after ]])"; exit 1; }
  echo "ok [$label]: path filled, cursor past link"
}

check nocompatible -N
check compatible   --cmd 'set compatible'

# The default <Leader>f (\f) mapping must actually fire — including in
# compatible mode, where <>-notation needs the 'cpo' guard to be interpreted.
check_map() { # $1 = label, rest = extra vim args establishing the mode
  local label="$1"; shift
  local out; out=$(mktemp)
  vim -es -u NONE "$@" \
    --cmd 'source linepick.vim' \
    -c 'call setline(1, "see [[note|?]] here")' \
    -c 'call cursor(1, 8)' \
    -c 'call feedkeys("\\f", "x")' \
    -c "call writefile([getline(1)], '$out')" \
    -c 'qa!' </dev/null
  local got; got=$(cat "$out"); rm -f "$out"
  [ "$got" = "see [[note|notes/foo.md]] here" ] \
    || { echo "FAIL [$label] \\f mapping: '$got'"; exit 1; }
  echo "ok [$label]: \\f mapping fires"
}

check_map nocompatible -N
check_map compatible   --cmd 'set compatible'
echo "ALL PASS"
