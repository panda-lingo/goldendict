#include "audiolink.hh"
#include "globalbroadcaster.hh"
#include "dict/xdxf.hh"
#include "langcoder.hh"
#include "tiff.hh"

#include <QBuffer>
#include <QImage>

#include <cstring>

GlobalBroadcaster * GlobalBroadcaster::instance()
{
  static GlobalBroadcaster broadcaster;
  return &broadcaster;
}

std::string addAudioLink( const std::string &, const std::string & )
{
  return {};
}

std::string addAudioLink( const QString &, const std::string & )
{
  return {};
}

namespace GdTiff {

// Upstream sizes TIFF images against QApplication::primaryScreen(), which is
// unavailable under this QCoreApplication worker. Preserve its decode/convert
// behavior using QtGui only and a deterministic, lossless PNG representation.
void tiff2img( std::vector< char > & data )
{
  if ( data.empty() ) {
    return;
  }
  const QImage image = QImage::fromData( reinterpret_cast< const uchar * >( data.data() ), data.size() );
  if ( image.isNull() ) {
    return;
  }
  QByteArray encoded;
  QBuffer buffer( &encoded );
  if ( !buffer.open( QIODevice::WriteOnly ) || !image.save( &buffer, "PNG" ) ) {
    return;
  }
  data.resize( encoded.size() );
  std::memcpy( data.data(), encoded.constData(), encoded.size() );
}

} // namespace GdTiff

namespace Xdxf {

// StarDict's upstream XDXF article renderer shares this tiny language-code
// helper with the full XDXF reader. Keeping the boundary here avoids linking
// an unused fourth dictionary factory into the phase-one worker.
quint32 getLanguageId( const QString & language )
{
  QString code = language.left( 3 );
  if ( code.endsWith( '-' ) ) {
    code.chop( 1 );
  }
  if ( code.size() == 2 ) {
    return LangCoder::code2toInt( code.toLatin1().constData() );
  }
  if ( code.size() == 3 ) {
    return LangCoder::findIdForLanguageCode3( code.toStdString() );
  }
  return 0;
}

} // namespace Xdxf
