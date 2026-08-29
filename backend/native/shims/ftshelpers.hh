#pragma once

#include "dict/btreeidx.hh"
#include <QtConcurrentRun>

// MDX exposes full-text-search virtual methods because the desktop app offers
// them.  Headword lookup does not use that subsystem, so keep its ABI surface
// while avoiding Xapian and UI-generated fulltextsearch headers.
namespace FtsHelpers {

inline bool ftsIndexIsOldOrBad( BtreeIndexing::BtreeDictionary * )
{
  return false;
}

inline void makeFTSIndex( BtreeIndexing::BtreeDictionary *, QAtomicInt & ) {}

class FTSResultsRequest: public Dictionary::DataRequest
{
public:
  FTSResultsRequest( BtreeIndexing::BtreeDictionary &, const QString &, int, bool, bool )
  {
    finish();
  }

  void cancel() override {}
};

} // namespace FtsHelpers
