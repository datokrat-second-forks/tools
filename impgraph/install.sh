#!/usr/bin/env bash
# Put impgraph on your PATH by appending a line to ~/.bashrc — but only once.
set -euo pipefail

# Directory holding this script (and the impgraph executable next to it).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="${HOME}/.bashrc"
LINE="export PATH=\"\$PATH:${DIR}\""

if [ -f "$BASHRC" ] && grep -qF "$DIR" "$BASHRC"; then
    echo "impgraph already on your PATH via $BASHRC — nothing to do."
    exit 0
fi

printf '\n# Added by impgraph install.sh\n%s\n' "$LINE" >> "$BASHRC"
echo "Added impgraph to your PATH in $BASHRC."
echo "Run 'source $BASHRC' (or open a new shell), then try: impgraph --help"
