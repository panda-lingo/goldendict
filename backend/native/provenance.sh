#!/bin/sh
set -eu

upstream_dir=${1:?usage: provenance.sh GOLDENDICT_NG_CHECKOUT}
if ! inside_work_tree=$(git -C "$upstream_dir" rev-parse --is-inside-work-tree 2>/dev/null) \
   || [ "$inside_work_tree" != true ]; then
  echo "GoldenDict-ng provenance cannot be verified: $upstream_dir is not a Git worktree" >&2
  echo "Supply a Git checkout, not an unversioned source export." >&2
  exit 1
fi

actual_commit=$(git -C "$upstream_dir" rev-parse --verify HEAD)
temporary_dir=$(mktemp -d)
temporary_index="$temporary_dir/index"
diff_file="$temporary_dir/relevant-source.diff"
cleanup() {
  rm -rf -- "$temporary_dir"
}
trap cleanup EXIT HUP INT TERM

# Construct a disposable index for the effective src/ working tree. Compared
# with HEAD, this captures tracked modifications/deletions and every untracked
# source file (including ignored generated headers) without modifying the
# developer's real Git index.
GIT_INDEX_FILE="$temporary_index" git -C "$upstream_dir" read-tree HEAD
GIT_INDEX_FILE="$temporary_index" git -C "$upstream_dir" add -A -f -- src
LC_ALL=C GIT_INDEX_FILE="$temporary_index" git -C "$upstream_dir" \
  -c core.quotepath=false \
  diff --cached --binary --full-index --no-ext-diff --no-textconv --no-renames \
  --src-prefix=a/ --dst-prefix=b/ HEAD -- src > "$diff_file"

diff_sha256=$(sha256sum "$diff_file" | awk '{print $1}')
if [ -s "$diff_file" ]; then
  dirty=true
else
  dirty=false
fi

printf 'commit=%s\n' "$actual_commit"
printf 'dirty=%s\n' "$dirty"
printf 'diff_sha256=%s\n' "$diff_sha256"
