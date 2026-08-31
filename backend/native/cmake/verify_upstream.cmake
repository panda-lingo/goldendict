if(NOT DEFINED GOLDENDICT_NG_LOCK OR NOT EXISTS "${GOLDENDICT_NG_LOCK}")
  message(FATAL_ERROR "GOLDENDICT_NG_LOCK must name an existing upstream.lock file")
endif()

file(STRINGS "${GOLDENDICT_NG_LOCK}" _commit_lines REGEX "^commit=")
list(LENGTH _commit_lines _commit_line_count)
if(NOT _commit_line_count EQUAL 1)
  message(FATAL_ERROR
    "${GOLDENDICT_NG_LOCK} must contain exactly one commit=<40 lowercase hex characters> line")
endif()
list(GET _commit_lines 0 _commit_line)
string(REGEX REPLACE "^commit=" "" _locked_commit "${_commit_line}")
string(STRIP "${_locked_commit}" _locked_commit)
string(LENGTH "${_locked_commit}" _locked_commit_length)
if(NOT _locked_commit_length EQUAL 40 OR NOT _locked_commit MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR "Invalid GoldenDict-ng commit in ${GOLDENDICT_NG_LOCK}: '${_locked_commit}'")
endif()

if(NOT DEFINED GOLDENDICT_NG_COMMIT OR GOLDENDICT_NG_COMMIT STREQUAL "")
  message(FATAL_ERROR
    "GOLDENDICT_NG_COMMIT is required; pass the commit recorded in ${GOLDENDICT_NG_LOCK}")
endif()
if(NOT GOLDENDICT_NG_COMMIT STREQUAL _locked_commit)
  message(FATAL_ERROR
    "GoldenDict-ng build argument mismatch: upstream.lock pins ${_locked_commit}, "
    "but GOLDENDICT_NG_COMMIT is ${GOLDENDICT_NG_COMMIT}")
endif()

if(NOT DEFINED GOLDENDICT_NG_SOURCE OR NOT IS_DIRECTORY "${GOLDENDICT_NG_SOURCE}")
  message(FATAL_ERROR
    "GOLDENDICT_NG_SOURCE must point to a GoldenDict-ng source directory")
endif()

set(_provenance_script "${CMAKE_CURRENT_LIST_DIR}/../provenance.sh")
execute_process(
  COMMAND sh "${_provenance_script}" "${GOLDENDICT_NG_SOURCE}"
  RESULT_VARIABLE _provenance_result
  OUTPUT_VARIABLE _provenance
  ERROR_VARIABLE _provenance_error
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(_provenance_result EQUAL 0)
  string(REGEX MATCH "(^|\n)commit=([^\n]+)" _commit_match "${_provenance}")
  set(_actual_commit "${CMAKE_MATCH_2}")
  string(REGEX MATCH "(^|\n)dirty=([^\n]+)" _dirty_match "${_provenance}")
  set(_actual_dirty "${CMAKE_MATCH_2}")
  string(REGEX MATCH "(^|\n)diff_sha256=([^\n]+)" _digest_match "${_provenance}")
  set(_actual_diff_sha256 "${CMAKE_MATCH_2}")
else()
  string(STRIP "${_provenance_error}" _provenance_error)
  if(DEFINED GOLDENDICT_NG_DIRTY
     AND NOT GOLDENDICT_NG_DIRTY STREQUAL ""
     AND DEFINED GOLDENDICT_NG_DIFF_SHA256
     AND NOT GOLDENDICT_NG_DIFF_SHA256 STREQUAL "")
    # A staged context intentionally omits Git metadata, and a linked
    # worktree's .git file can refer outside a Docker named context. build.sh
    # computed these values against the live worktree immediately before
    # staging the exact src/ and icons/ inputs.
    set(_actual_commit "${GOLDENDICT_NG_COMMIT}")
    set(_actual_dirty "${GOLDENDICT_NG_DIRTY}")
    set(_actual_diff_sha256 "${GOLDENDICT_NG_DIFF_SHA256}")
    message(STATUS
      "Using caller-attested GoldenDict-ng source provenance because Git metadata "
      "is unavailable in the build context: ${_provenance_error}")
  else()
    message(FATAL_ERROR "Could not inspect GoldenDict-ng provenance: ${_provenance_error}")
  endif()
endif()

if(NOT _actual_commit STREQUAL _locked_commit)
  message(FATAL_ERROR
    "GoldenDict-ng checkout mismatch: upstream.lock pins ${_locked_commit}, "
    "but ${GOLDENDICT_NG_SOURCE} is at ${_actual_commit}")
endif()

if(NOT _actual_dirty STREQUAL "true" AND NOT _actual_dirty STREQUAL "false")
  message(FATAL_ERROR "Invalid dirty value returned by ${_provenance_script}: '${_actual_dirty}'")
endif()
string(LENGTH "${_actual_diff_sha256}" _digest_length)
if(NOT _digest_length EQUAL 64 OR NOT _actual_diff_sha256 MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR
    "Invalid source-diff SHA-256 returned by ${_provenance_script}: '${_actual_diff_sha256}'")
endif()

if(DEFINED GOLDENDICT_NG_DIRTY
   AND NOT GOLDENDICT_NG_DIRTY STREQUAL ""
   AND NOT GOLDENDICT_NG_DIRTY STREQUAL _actual_dirty)
  message(FATAL_ERROR
    "GoldenDict-ng dirty-state mismatch: caller supplied ${GOLDENDICT_NG_DIRTY}, "
    "but the build context is ${_actual_dirty}")
endif()
if(DEFINED GOLDENDICT_NG_DIFF_SHA256
   AND NOT GOLDENDICT_NG_DIFF_SHA256 STREQUAL ""
   AND NOT GOLDENDICT_NG_DIFF_SHA256 STREQUAL _actual_diff_sha256)
  message(FATAL_ERROR
    "GoldenDict-ng source-diff mismatch: caller supplied ${GOLDENDICT_NG_DIFF_SHA256}, "
    "but the build context has ${_actual_diff_sha256}")
endif()

set(GOLDENDICT_NG_DIRTY "${_actual_dirty}")
set(GOLDENDICT_NG_DIFF_SHA256 "${_actual_diff_sha256}")

if(GOLDENDICT_NG_REQUIRE_CLEAN AND GOLDENDICT_NG_DIRTY STREQUAL "true")
  message(FATAL_ERROR
    "GoldenDict-ng has local worker-input changes (${GOLDENDICT_NG_DIFF_SHA256}); "
    "GOLDENDICT_NG_REQUIRE_CLEAN is enabled")
endif()

message(STATUS
  "Verified GoldenDict-ng ${_locked_commit} "
  "(dirty=${GOLDENDICT_NG_DIRTY}, diff_sha256=${GOLDENDICT_NG_DIFF_SHA256})")
