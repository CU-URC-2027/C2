#!/bin/zsh
set -e
cd -- "${0:A:h}"
if command -v uv >/dev/null 2>&1; then
  c2_uv="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  c2_uv="$HOME/.local/bin/uv"
else
  print "Install uv from https://docs.astral.sh/uv/ then reopen this launcher."
  read -k 1
  exit 1
fi
"$c2_uv" sync --frozen
"$c2_uv" run python scripts/dev.py --open
