#pragma once

#include <QSet>
#include <QString>
#include <QtGlobal>

// GoldenDict-ng's dictionary interface currently includes the full desktop
// configuration header.  The local dictionary core needs only these fields.
// Keeping this shim intentionally small makes upstream interface drift fail at
// compile time and documents the desired future upstream library boundary.
namespace Config {

struct FullTextSearch
{
  bool enabled = false;
  quint32 maxDictionarySize = 0;
  QString disabledTypes;
};

struct Preferences
{
  bool ignorePunctuation = true;
};

struct Class
{
  Preferences preferences;
  QSet< QString > dictionariesToReindex;
};

inline bool isPortableVersion() noexcept
{
  return false;
}

inline QString getPortableVersionDictionaryDir() noexcept
{
  return {};
}

} // namespace Config
