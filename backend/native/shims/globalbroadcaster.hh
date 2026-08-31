#pragma once

#include "config.hh"
#include "common/dictionary_icon_name.hh"
#include "dict/dictionary.hh"

#include <QDir>
#include <QHash>
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

  QString getAbbrName( const QString & text, const QString & key = {} );

  void indexingDictionary( const QString & ) {}

  void addLsaDictMapping( const QString & dictionaryId, const QString & path )
  {
    const QString nativePath = QDir::toNativeSeparators( path );
    lsaIdToPath.insert( dictionaryId, nativePath );
    lsaPathToId.insert( nativePath, dictionaryId );
  }

  QString getLsaIdFromPath( const QString & path ) const
  {
    return lsaPathToId.value( QDir::toNativeSeparators( path ) );
  }

  QString getLsaPathFromId( const QString & dictionaryId ) const
  {
    return lsaIdToPath.value( dictionaryId );
  }

  void setAllDictionaries( std::vector< sptr< Dictionary::Class > > * values )
  {
    dictionaries = values;
  }

  sptr< Dictionary::Class > getDictionaryById( const QString & dictionaryId ) const
  {
    if ( dictionaries == nullptr ) {
      return {};
    }
    for ( const auto & dictionary : *dictionaries ) {
      if ( QString::fromStdString( dictionary->getId() ) == dictionaryId ) {
        return dictionary;
      }
    }
    return {};
  }

private:
  Config::Preferences preferences;
  Icons::DictionaryIconName iconNames;
  QHash< QString, QString > lsaIdToPath;
  QHash< QString, QString > lsaPathToId;
  std::vector< sptr< Dictionary::Class > > * dictionaries = nullptr;
};
