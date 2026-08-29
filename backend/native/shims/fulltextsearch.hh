#pragma once

// globalregex.cc only needs this constant.  The REST lookup service does not
// build GoldenDict's optional Xapian full-text index.
namespace FTS {
enum {
  MinimumWordSize = 4,
};
} // namespace FTS
