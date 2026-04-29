#!/usr/bin/env bash
set -u

usage() {
  cat <<'EOF'
Usage: tests/e2e.sh [-d _test_playground]

Runs a manual end-to-end PennyParse check with the chosen directory as both
HOME and CWD. Console output is structured for copy/paste debugging.
EOF
}

PLAYGROUND="_test_playground"
while getopts ":d:h" opt; do
  case "$opt" in
    d) PLAYGROUND="$OPTARG" ;;
    h)
      usage
      exit 0
      ;;
    \?)
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLAYGROUND_DIR="$PLAYGROUND"
if [[ "$PLAYGROUND_DIR" != /* ]]; then
  PLAYGROUND_DIR="$REPO_DIR/$PLAYGROUND_DIR"
fi

RUN_ID="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="pennyparse_results_e2e_${RUN_ID}"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
PP_CMD=(uv --project "$REPO_DIR" --cache-dir "$UV_CACHE_DIR" run --extra pdf pennyparse)

section() {
  printf '\n========== %s ==========\n' "$1"
}

show_file() {
  local path="$1"
  local lines="${2:-120}"
  if [[ -f "$path" ]]; then
    printf -- '--- %s (first %s lines) ---\n' "$path" "$lines"
    sed -n "1,${lines}p" "$path"
  else
    printf -- '--- %s missing ---\n' "$path"
  fi
}

run_step() {
  local name="$1"
  shift
  section "$name"
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  "$@"
  local status=$?
  printf '\n[exit_code] %s\n' "$status"
  return "$status"
}

copy_if_exists() {
  local src="$1"
  local dest="$2"
  if [[ -f "$src" ]]; then
    cp "$src" "$dest"
    printf 'copied %s -> %s\n' "$src" "$dest"
  else
    printf 'missing optional file: %s\n' "$src"
  fi
}

section "E2E Context"
printf 'repo=%s\n' "$REPO_DIR"
printf 'playground=%s\n' "$PLAYGROUND_DIR"
printf 'home=%s\n' "$PLAYGROUND_DIR"
printf 'cwd=%s\n' "$PLAYGROUND_DIR"
printf 'out_dir=%s\n' "$OUT_DIR"
printf 'uv_cache=%s\n' "$UV_CACHE_DIR"
printf 'date=%s\n' "$(date -Is)"
printf 'uname=%s\n' "$(uname -a)"
printf 'python='
python --version 2>&1 || true
printf 'uv='
uv --version 2>&1 || true

section "Prepare Playground"
mkdir -p "$PLAYGROUND_DIR/docs" "$PLAYGROUND_DIR/.pennyparse"
copy_if_exists "$REPO_DIR/.env" "$PLAYGROUND_DIR/.env"
copy_if_exists "$REPO_DIR/pennyparse.toolbox_user.txt" "$PLAYGROUND_DIR/pennyparse.toolbox_user.txt"
if [[ ! -f "$PLAYGROUND_DIR/pennyparse.toolbox_user.txt" ]]; then
  copy_if_exists "$REPO_DIR/src/pennyparse/pennyparse.toolbox_user.txt" "$PLAYGROUND_DIR/pennyparse.toolbox_user.txt"
fi
copy_if_exists "$REPO_DIR/demo_assets/3small.pdf" "$PLAYGROUND_DIR/docs/3small.pdf"
copy_if_exists "$REPO_DIR/demo_assets/image1170x530cropped.jpg" "$PLAYGROUND_DIR/docs/image1170x530cropped.jpg"

section "Sanitized Config Presence"
if [[ -f "$PLAYGROUND_DIR/.env" ]]; then
  sed -E 's/(PENNYPARSE_CHAT_AUTHKEY|OPENAI_API_KEY|.*API_KEY|.*TOKEN|.*SECRET)=.*/\1=***MASKED***/; s/(PENNYPARSE_CHAT_BASE)=([^[:space:]]{0,32}).*/\1=\2.../; s/(PENNYPARSE_CHAT_MODEL)=.*/\1=***SET***/' "$PLAYGROUND_DIR/.env"
else
  printf '.env missing in playground\n'
fi

cd "$PLAYGROUND_DIR" || exit 1
export HOME="$PLAYGROUND_DIR"

INIT_STATUS=0
RUN_STATUS=0

run_step "pennyparse tool --list before init" "${PP_CMD[@]}" tool --list || true
run_step "pennyparse init" "${PP_CMD[@]}" init --force --from pennyparse.toolbox_user.txt
INIT_STATUS=$?

run_step "pennyparse tool --list after init" "${PP_CMD[@]}" tool --list || true

if [[ "$INIT_STATUS" -eq 0 ]]; then
  run_step "pennyparse run" "${PP_CMD[@]}" run docs --out-dir "$OUT_DIR"
  RUN_STATUS=$?
else
  section "pennyparse run skipped"
  printf 'init failed, so run was skipped\n'
  RUN_STATUS=1
fi

section "Generated Files"
find . -maxdepth 5 -type f \
  ! -path './.env' \
  ! -path './.pennyparse/__pycache__/*' \
  -printf '%p\t%k KiB\n' | sort

section "Memory"
show_file ".pennyparse_memory.txt" 160

section "Generated User Toolbox"
show_file ".pennyparse/user_toolbox.py" 220

section "Result Previews"
if [[ -d "$OUT_DIR" ]]; then
  while IFS= read -r file; do
    show_file "$file" 80
  done < <(find "$OUT_DIR" -type f | sort)
else
  printf '%s missing\n' "$OUT_DIR"
fi

section "PennyParse Log Tail"
if [[ -f pennyparse.log ]]; then
  tail -n 220 pennyparse.log
else
  printf 'pennyparse.log missing\n'
fi

section "Summary"
printf 'init_exit=%s\n' "$INIT_STATUS"
printf 'run_exit=%s\n' "$RUN_STATUS"
if [[ "$INIT_STATUS" -eq 0 && "$RUN_STATUS" -eq 0 ]]; then
  printf 'e2e_status=PASS\n'
  exit 0
fi
printf 'e2e_status=FAIL\n'
exit 1
