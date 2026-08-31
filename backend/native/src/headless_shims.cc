#include "audiolink.hh"
#include "globalbroadcaster.hh"

#include <QRegularExpression>

GlobalBroadcaster * GlobalBroadcaster::instance()
{
  static GlobalBroadcaster broadcaster;
  return &broadcaster;
}

QString GlobalBroadcaster::getAbbrName( const QString & text, const QString & key )
{
  if ( text.isEmpty() ) {
    return {};
  }
  QString simplified = text;
  simplified.remove(
    QRegularExpression( R"([\p{Z}\p{N}\p{M}\p{P}\p{S}])", QRegularExpression::UseUnicodePropertiesOption ) );
  if ( simplified.isEmpty() ) {
    return {};
  }
  return iconNames.getIconName( key.isEmpty() ? simplified : key, simplified );
}

std::string addAudioLink( const std::string &, const std::string & )
{
  return {};
}

std::string addAudioLink( const QString &, const std::string & )
{
  return {};
}
