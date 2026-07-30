#!/usr/bin/env bash
# Verify every claim this project makes, from a clean shell.
#
# Exits 0 only when all of these hold:
#   the test suite passes, including the negative controls that prove each detector can fire
#   no text element in the corpus escapes the container the solver assigned it
#   no two labels intersect
#   the same spec renders byte-identically, and different specs render differently
#   unsatisfiable specs raise with a description of the conflict
#   the parsed font metrics match fontTools over every codepoint
#   a real browser, measuring the published page, agrees on all of the above
#
# The browser stage is not optional. If Node or Chromium is unavailable this script fails,
# because a skipped check is "could not verify" and never "verified".

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PRETTY="${ROOT/#$HOME/\~}"

echo "svg-infographic verify"
echo "project: $PRETTY"
echo

echo "=== 1. python: what is available ==="
python3 --version
python3 - <<'PY'
import fontTools
print("fontTools", fontTools.version, "(the independent parser the checks compare against)")
PY
echo

echo "=== 2. fonts the engine will measure ==="
python3 - <<'PY'
import os
from engine.fontmetrics import SUPPORTED_FONTS, get_font, resolve_font_path
home = os.environ.get("HOME", "")
for name in SUPPORTED_FONTS:
    p = str(resolve_font_path(name))
    f = get_font(name)
    if home and p.startswith(home):
        p = "~" + p[len(home):]
    print(f"  {name:<22} {len(f.cmap):>6} codepoints  upem {f.units_per_em:<5} {p}")
PY
echo

echo "=== 3. test suite ==="
python3 -m unittest discover -s tests -t . -v 2>&1 | tail -n 40
echo

echo "=== 4. measured claims ==="
python3 tools/measure.py
echo

echo "=== 5. build the page ==="
python3 tools/build_docs.py | grep -v '^ ' | head -n 4
DOCS="$ROOT/docs/index.html"
test -s "$DOCS"
echo "page: ${DOCS/#$HOME/\~} ($(wc -c < "$DOCS") bytes)"
grep -q 'data-engine="svg-infographic"' "$DOCS"
grep -q 'prefers-color-scheme: dark' "$DOCS"
grep -q ':root\[data-theme="dark"\]' "$DOCS"
grep -q ':root\[data-theme="light"\]' "$DOCS"
if grep -qE 'src="https?://|href="https?://|@import url\(https?://' "$DOCS"; then
  echo "FAIL: the page references a remote asset"
  exit 1
fi
echo "page self-check: engine marker, both theme mechanisms, no remote assets"
echo

echo "=== 6. real browser measurement ==="
command -v node >/dev/null || { echo "FAIL: node is required and was not found"; exit 1; }
PWCORE="${PLAYWRIGHT_CORE:-$ROOT/../a11y-sweep/node_modules/playwright-core}"
test -d "$PWCORE" || { echo "FAIL: playwright-core not found at ${PWCORE/#$HOME/\~}"; exit 1; }
PLAYWRIGHT_CORE="$PWCORE" node tools/browser_check.js
echo

echo "=== 7. determinism across two fresh processes ==="
A=$(PYTHONHASHSEED=0 python3 -c "
import hashlib,sys;sys.path.insert(0,'.')
from corpus.specs import CORPUS
from engine.render import render_spec
print(hashlib.sha256(''.join(render_spec(s) for s in CORPUS).encode()).hexdigest())")
B=$(PYTHONHASHSEED=99991 python3 -c "
import hashlib,sys;sys.path.insert(0,'.')
from corpus.specs import CORPUS
from engine.render import render_spec
print(hashlib.sha256(''.join(render_spec(s) for s in CORPUS).encode()).hexdigest())")
echo "PYTHONHASHSEED=0      $A"
echo "PYTHONHASHSEED=99991  $B"
test "$A" = "$B" || { echo "FAIL: output depends on the hash seed"; exit 1; }
echo "byte-identical across processes"
echo

echo "=== 8. no secrets, no absolute home paths in committed files ==="
python3 - <<'PY'
import os, pathlib, re, sys
root = pathlib.Path(".").resolve()
home = os.environ.get("HOME", "/home/nobody")
skip = {".git", "__pycache__", "out", "node_modules"}
patterns = [
    ("absolute home path", re.compile(re.escape(home))),
    ("openrouter key", re.compile(r"sk-or-v1-[A-Za-z0-9]{32,}")),
    ("openai key", re.compile(r"sk-[A-Za-z0-9]{40,}")),
    ("aws key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("private key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]
bad = []
for p in sorted(root.rglob("*")):
    if not p.is_file() or any(part in skip for part in p.parts):
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for label, rx in patterns:
        m = rx.search(text)
        if m:
            bad.append(f"{p.relative_to(root)}: {label} at offset {m.start()}")
print(f"scanned files under {root.name}/, findings: {len(bad)}")
for b in bad[:10]:
    print("  " + b)
sys.exit(1 if bad else 0)
PY
echo

echo "=== VERIFIED ==="
python3 tools/measure.py | grep -E "^CLAIM"
echo
echo "All claims measured and holding. Page: ${DOCS/#$HOME/\~}"
