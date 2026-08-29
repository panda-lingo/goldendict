cmake_minimum_required(VERSION 3.25)

project(goldendict-native-worker LANGUAGES C CXX)

include(CTest)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

set(GOLDENDICT_NG_SOURCE "" CACHE PATH "Path to a pinned GoldenDict-ng source checkout")
set(GOLDENDICT_NG_COMMIT "" CACHE STRING "Pinned GoldenDict-ng commit from upstream.lock")
set(GOLDENDICT_NG_DIRTY "" CACHE STRING "Whether relevant upstream sources differ from the pinned commit")
set(GOLDENDICT_NG_DIFF_SHA256 "" CACHE STRING "SHA-256 of the relevant upstream source diff")
option(GOLDENDICT_NG_REQUIRE_CLEAN "Reject locally modified GoldenDict-ng sources" OFF)
if(NOT IS_DIRECTORY "${GOLDENDICT_NG_SOURCE}/src/dict")
  message(FATAL_ERROR "GOLDENDICT_NG_SOURCE must point to a GoldenDict-ng checkout")
endif()

# Verify provenance before probing dependencies or compiling any upstream file.
# The explicit source list below is the API compatibility check; any upstream
# interface drift then fails during compilation instead of changing behavior
# silently.
set(GOLDENDICT_NG_LOCK "${CMAKE_CURRENT_SOURCE_DIR}/upstream.lock")
include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/verify_upstream.cmake")

find_package(Qt6 6.2 REQUIRED COMPONENTS Concurrent Core Gui Svg Widgets Xml)
find_package(BZip2 REQUIRED)
find_package(fmt REQUIRED)
find_package(LibLZMA REQUIRED)
find_package(ZLIB REQUIRED)
find_package(Iconv REQUIRED)
find_library(LZO2_LIBRARY NAMES lzo2 REQUIRED)

set(GD_SRC "${GOLDENDICT_NG_SOURCE}/src")
include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/prepare_mdx_source.cmake")

# These files are compiled directly from the pinned upstream checkout.  The
# list is deliberately explicit: an upstream refactor becomes a compile-time
# compatibility failure instead of silently changing the worker's behavior.
set(GOLDENDICT_MDX_SOURCES
  "${GOLDENDICT_PATCHED_MDX_SOURCE}"
  "${GD_SRC}/dict/mdictparser.cc"
  "${GD_SRC}/dict/btreeidx.cc"
  "${GD_SRC}/dict/chunkedstorage.cc"
  "${GD_SRC}/dict/dictionary.cc"
  "${GD_SRC}/dict/utils/decompress.cc"
  "${GD_SRC}/dict/utils/dictfile.cc"
  "${GD_SRC}/dict/utils/ripemd.cc"
  "${GD_SRC}/dict/utils/splitfile.cc"
  "${GD_SRC}/dict/utils/zipfile.cc"
  "${GD_SRC}/common/filetype.cc"
  "${GD_SRC}/common/folding.cc"
  "${GD_SRC}/common/globalregex.cc"
  "${GD_SRC}/common/htmlescape.cc"
  "${GD_SRC}/common/iconv.cc"
  "${GD_SRC}/common/text.cc"
  "${GD_SRC}/common/utils.cc"
  "${GD_SRC}/common/wildcard.cc"
  "${GD_SRC}/langcoder.cc"
  "${GD_SRC}/language.cc"
)

# Phase-one local formats use the same Dictionary::Class interface and index
# primitives. These are also compiled in place from the pinned checkout.
set(GOLDENDICT_DSL_STARDICT_SOURCES
  "${GD_SRC}/dict/dsl.cc"
  "${GD_SRC}/dict/dsl_details.cc"
  "${GD_SRC}/dict/stardict.cc"
  "${GD_SRC}/dict/xdxf2html.cc"
  "${GD_SRC}/dict/utils/dictzip.c"
  "${GD_SRC}/dict/utils/indexedzip.cc"
  "${GD_SRC}/dict/utils/ufile.cc"
)

add_executable(goldendict-native-worker
  src/main.cc
  src/headless_shims.cc
  ${GOLDENDICT_MDX_SOURCES}
  ${GOLDENDICT_DSL_STARDICT_SOURCES}
  # QObject types declared by the upstream public dictionary interface.
  "${GD_SRC}/dict/dictionary.hh"
)

add_executable(resource-guard-test tests/resource_guard_test.cc)
target_include_directories(resource-guard-test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(resource-guard-test PRIVATE Qt6::Core)
add_test(NAME resource-guard COMMAND resource-guard-test)

# Shims precede upstream includes only for desktop-only service boundaries.
# Dictionary/parser implementation files themselves always come from upstream.
target_include_directories(goldendict-native-worker PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}/shims"
  "${CMAKE_CURRENT_SOURCE_DIR}/src"
  "${GD_SRC}"
  "${GD_SRC}/common"
  "${GD_SRC}/dict"
  "${GD_SRC}/dict/utils"
)

target_compile_definitions(goldendict-native-worker PRIVATE
  GOLDENDICT_NG_COMMIT="${GOLDENDICT_NG_COMMIT}"
  GOLDENDICT_NG_DIRTY="${GOLDENDICT_NG_DIRTY}"
  GOLDENDICT_NG_DIFF_SHA256="${GOLDENDICT_NG_DIFF_SHA256}"
)

target_compile_options(goldendict-native-worker PRIVATE
  -ffunction-sections
  -fdata-sections
  -Wall
  -Wextra
  -Wpedantic
)

target_link_options(goldendict-native-worker PRIVATE -Wl,--gc-sections)

target_link_libraries(goldendict-native-worker PRIVATE
  Qt6::Concurrent
  Qt6::Core
  Qt6::Gui
  Qt6::Svg
  Qt6::Widgets
  Qt6::Xml
  BZip2::BZip2
  fmt::fmt
  LibLZMA::LibLZMA
  ZLIB::ZLIB
  Iconv::Iconv
  "${LZO2_LIBRARY}"
)

install(TARGETS goldendict-native-worker RUNTIME DESTINATION bin)
