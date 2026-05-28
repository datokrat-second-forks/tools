#!/usr/bin/env bash
# Put leansnip on your PATH by appending a line to ~/.bashrc — but only once.
set -euo pipefail

# Directory holding this script (and the leansnip executable next to it).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="${HOME}/.bashrc"
LINE="export PATH=\"\$PATH:${DIR}\""

if [ -f "$BASHRC" ] && grep -qF "$DIR" "$BASHRC"; then
    echo "leansnip already on your PATH via $BASHRC — nothing to do."
    exit 0
fi

printf '\n# Added by leansnip install.sh\n%s\n' "$LINE" >> "$BASHRC"
echo "Added leansnip to your PATH in $BASHRC."
echo "Run 'source $BASHRC' (or open a new shell), then try: leansnip --help"
echo "Next: point it at your snippets repo, e.g.  leansnip repo /configs"
