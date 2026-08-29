#pragma once

#include "config.hh"
#include "dict/dictionary.hh"

#include <QString>

// Headless projection of the process-wide desktop service used by a few base
// dictionary helpers.  It intentionally contains no QObject/UI/network state.
class GlobalBroadcaster
{
public:
  static GlobalBroadcaster * instance();

  Config::Class * getConfig() const
  {
    return nullptr;
  }

  Config::Preferences * getPreference()
  {
    return &preferences;
  }

  QString getAbbrName( const QString & text, const QString & = {} )
  {
    const QString simplified = text.simplified();
    return simplified.isEmpty() ? QString{} : simplified.left( 1 ).toUpper();
  }

  void indexingDictionary( const QString & ) {}

  QString getLsaIdFromPath( const QString & ) const
  {
    return {};
  }

  sptr< Dictionary::Class > getDictionaryById( const QString & ) const
  {
    // Cross-dictionary DSL -> LSA resource fallback belongs to the complete
    // desktop catalog. The headless phase-one worker does not load LSA yet.
    return {};
  }

private:
  Config::Preferences preferences;
};
