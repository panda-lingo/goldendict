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
temporary_objects="$temporary_dir/objects"
diff_file="$temporary_dir/relevant-source.diff"
cleanup() {
  rm -rf -- "$temporary_dir"
}
trap cleanup EXIT HUP INT TERM

# A read-only BuildKit source mount also makes its Git object database
# read-only.  Point writes from `git add` at the disposable directory while
# retaining the checkout's object database as a read-only alternate.
source_objects=$(git -C "$upstream_dir" \
  rev-parse --path-format=absolute --git-path objects)
mkdir -p "$temporary_objects"

# Construct a disposable index for every upstream input compiled or embedded
# by the worker. Compared with HEAD, this captures tracked modifications,
# deletions, and untracked generated sources/assets without modifying the
# developer's real Git index.
GIT_INDEX_FILE="$temporary_index" \
GIT_OBJECT_DIRECTORY="$temporary_objects" \
GIT_ALTERNATE_OBJECT_DIRECTORIES="$source_objects" \
  git -C "$upstream_dir" read-tree HEAD
GIT_INDEX_FILE="$temporary_index" \
GIT_OBJECT_DIRECTORY="$temporary_objects" \
GIT_ALTERNATE_OBJECT_DIRECTORIES="$source_objects" \
  git -C "$upstream_dir" add -A -f -- \
  src icons
LC_ALL=C \
GIT_INDEX_FILE="$temporary_index" \
GIT_OBJECT_DIRECTORY="$temporary_objects" \
GIT_ALTERNATE_OBJECT_DIRECTORIES="$source_objects" \
  git -C "$upstream_dir" \
  -c core.quotepath=false \
  diff --cached --binary --full-index --no-ext-diff --no-textconv --no-renames \
  --src-prefix=a/ --dst-prefix=b/ HEAD -- \
  src icons > "$diff_file"

diff_sha256=$(sha256sum "$diff_file" | awk '{print $1}')
if [ -s "$diff_file" ]; then
  dirty=true
else
  dirty=false
fi

printf 'commit=%s\n' "$actual_commit"
printf 'dirty=%s\n' "$dirty"
printf 'diff_sha256=%s\n' "$diff_sha256"
