#!/usr/bin/env bash
# Attack the verify script.
#
# A verify command that passes on a broken implementation is worse than no verify at all, so
# this breaks the two things the project's claims rest on and confirms that verify notices.
# Each attack runs in a throwaway copy of the tree, so the working directory is never modified.
#
#   1  replace real text measurement with len(text) * 8, the estimate the brief forbids
#   2  disable the collision-avoidance pass, so stacked lines are free to overlap
#   3  round measured widths down instead of up, a one-line rounding change
#   4  make the renderer emit a constant, which a weak determinism test would accept
#
# Every attack must make verify exit non-zero. Anything that still passes is a hole in verify.

set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PWCORE="${PLAYWRIGHT_CORE:-$ROOT/../a11y-sweep/node_modules/playwright-core}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

results=()

run_attack() {
  local name="$1"; shift
  local dir="$WORK/$1"; shift
  echo
  echo "############################################################"
  echo "# ATTACK: $name"
  echo "############################################################"
  rm -rf "$dir"
  mkdir -p "$dir"
  # Copy only the source. out/ and docs/ are regenerated, .git is irrelevant here.
  tar -C "$ROOT" --exclude='.git' --exclude='out' --exclude='__pycache__' -cf - . | tar -C "$dir" -xf -
  ( cd "$dir" && "$@" )
  local patched=$?
  if [ "$patched" -ne 0 ]; then
    echo "  attack could not be applied (patch step exited $patched)"
    results+=("$name|patch-failed|$patched")
    return
  fi
  set +e
  ( cd "$dir" && PLAYWRIGHT_CORE="$PWCORE" bash scripts/verify.sh > "$dir/verify.log" 2>&1 )
  local code=$?
  set -e
  echo "  verify exit code: $code"
  echo "  --- first failure reported ---"
  grep -m 6 -E "FAIL|AssertionError|Error|does not|overflow|collid|intersect|differ" "$dir/verify.log" \
    | sed 's/^/  /' | head -n 10 || true
  results+=("$name|$code")
}

patch_estimate() {
  python3 - <<'PY'
import pathlib, sys
p = pathlib.Path("engine/fontmetrics.py")
s = p.read_text()
old = """        for ch in text:
            total += self.advance_units(ch)
        return total * size / self.units_per_em"""
new = """        for ch in text:
            total += self.advance_units(ch)
        return len(text) * 8.0  # ATTACK: the estimate the brief forbids"""
if old not in s:
    sys.exit("could not find the measurement body to replace")
p.write_text(s.replace(old, new))
print("  patched Font.measure to len(text) * 8.0")
PY
}

patch_no_collision_pass() {
  python3 - <<'PY'
import pathlib, sys
p = pathlib.Path("engine/layout.py")
s = p.read_text()
old = "    lh = _r2(max(size * LINE_RATIO, a + d + MIN_LEADING))"
new = "    lh = _r2(size * 0.62)  # ATTACK: no separation pass, lines may overlap"
if old not in s:
    sys.exit("could not find the line-height rule to disable")
p.write_text(s.replace(old, new))
print("  patched metrics_for so line height ignores the em box: lines may overlap")
PY
}

patch_round_down() {
  python3 - <<'PY'
import pathlib, sys
p = pathlib.Path("engine/layout.py")
s = p.read_text()
old = "    return math.ceil(round(v, 6) * 100.0) / 100.0 + 0.0"
new = "    return math.floor(round(v, 6) * 100.0) / 100.0 + 0.0  # ATTACK: round measurements down"
if old not in s:
    sys.exit("could not find _ceil2 to invert")
p.write_text(s.replace(old, new))
print("  patched _ceil2 to floor, so containers can be a hair narrower than their content")
PY
}

patch_constant_output() {
  python3 - <<'PY'
import pathlib, sys
p = pathlib.Path("engine/render.py")
s = p.read_text()
old = "def render(lay: Layout) -> str:"
new = """def render(lay: Layout) -> str:
    return _constant()  # ATTACK: ignore the input entirely


def _constant() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10" '
        'data-engine="svg-infographic" data-spec-id="x" data-theme="light" data-font="DejaVu Sans" '
        'id="ig-x"><title>x</title></svg>\\n'
    )


def _real_render(lay: Layout) -> str:"""
if old not in s:
    sys.exit("could not find render() to stub")
p.write_text(s.replace(old, new, 1))
print("  patched render() to return a constant regardless of the spec")
PY
}

run_attack "text measurement replaced with len(text) * 8" a1 patch_estimate
run_attack "collision-avoidance pass disabled" a2 patch_no_collision_pass
run_attack "measured widths rounded down instead of up" a3 patch_round_down
run_attack "renderer emits a constant" a4 patch_constant_output

echo
echo "############################################################"
echo "# RESULT"
echo "############################################################"
fail=0
for r in "${results[@]}"; do
  name="${r%%|*}"
  code="${r##*|}"
  if [ "$code" = "0" ]; then
    echo "  HOLE IN VERIFY: '$name' passed verify (exit 0)"
    fail=1
  else
    echo "  verify correctly failed on '$name' (exit $code)"
  fi
done
if [ "$fail" -ne 0 ]; then
  echo
  echo "verify has a hole and needs fixing"
  exit 1
fi
echo
echo "every attack was caught"
