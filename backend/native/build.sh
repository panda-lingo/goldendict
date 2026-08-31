#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
upstream_dir=${1:-/home/ubuntu/goldendict-ng}
expected_commit=$(sed -n 's/^commit=//p' "$script_dir/upstream.lock")
provenance=$(sh "$script_dir/provenance.sh" "$upstream_dir")
actual_commit=$(printf '%s\n' "$provenance" | sed -n 's/^commit=//p')
upstream_dirty=$(printf '%s\n' "$provenance" | sed -n 's/^dirty=//p')
diff_sha256=$(printf '%s\n' "$provenance" | sed -n 's/^diff_sha256=//p')
require_clean=${GOLDENDICT_NG_REQUIRE_CLEAN:-OFF}
dockerfile=${GOLDENDICT_NATIVE_DOCKERFILE:-$script_dir/Dockerfile}
build_context=${GOLDENDICT_NATIVE_BUILD_CONTEXT:-$script_dir}
build_target=${GOLDENDICT_NATIVE_TARGET:-}
image=${GOLDENDICT_NATIVE_IMAGE:-goldendict-native-worker:dev}

if [ "$actual_commit" != "$expected_commit" ]; then
  echo "GoldenDict-ng commit mismatch: expected $expected_commit, got $actual_commit" >&2
  echo "Update upstream.lock only after the native compatibility build and fixture test pass." >&2
  exit 1
fi

# The worker consumes only src/ and icons/. Stage those attested inputs in a
# disposable named context so Docker does not copy a checkout's potentially
# large .git object database into every build.
upstream_context=$(mktemp -d)
cleanup() {
  rm -rf -- "$upstream_context"
}
trap cleanup EXIT HUP INT TERM
cp -a "$upstream_dir/src" "$upstream_dir/icons" "$upstream_context/"

set -- docker build \
  --file "$dockerfile" \
  --build-context "goldendict-ng=$upstream_context" \
  --build-arg "GOLDENDICT_NG_COMMIT=$expected_commit" \
  --build-arg "GOLDENDICT_NG_DIRTY=$upstream_dirty" \
  --build-arg "GOLDENDICT_NG_DIFF_SHA256=$diff_sha256" \
  --build-arg "GOLDENDICT_NG_REQUIRE_CLEAN=$require_clean"
if [ -n "$build_target" ]; then
  set -- "$@" --target "$build_target"
fi
set -- "$@" --tag "$image" "$build_context"
"$@"
