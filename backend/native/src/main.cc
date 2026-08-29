#include "dict/dictionary.hh"
#include "dict/dsl.hh"
#include "dict/mdx.hh"
#include "dict/stardict.hh"
#include "langcoder.hh"
#include "text.hh"

#include <QCoreApplication>
#include <QDir>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMimeDatabase>
#include <QStandardPaths>
#include <QTextStream>
#include <QTimer>

#include <algorithm>
#include <iostream>
#include <iterator>
#include <optional>
#include <string>
#include <vector>

namespace {

using DictionaryPtr = sptr< Dictionary::Class >;

class Initializing final: public Dictionary::Initializing
{
public:
  void indexingDictionary( const std::string & name ) noexcept override
  {
    std::cerr << "indexing " << name << '\n';
  }

  void loadingDictionary( const std::string & name ) noexcept override
  {
    std::cerr << "loading " << name << '\n';
  }
};

QString languageCode( quint32 value )
{
  const QString code = LangCoder::intToCode2( value );
  return code.isEmpty() ? QString{} : code;
}

QJsonValue nullableString( const QString & value )
{
  return value.isEmpty() ? QJsonValue( QJsonValue::Null ) : QJsonValue( value );
}

QString dictionaryMainPath( const DictionaryPtr & dictionary )
{
  QString mainPath = dictionary->getMainFilename();
  const auto & filenames = dictionary->getDictionaryFilenames();
  if ( mainPath.isEmpty() && !filenames.empty() ) {
    mainPath = QString::fromUtf8( filenames.front() );
  }
  return mainPath;
}

QString dictionaryFormat( const DictionaryPtr & dictionary )
{
  const QString lowered = dictionaryMainPath( dictionary ).toLower();
  return lowered.endsWith( ".dsl" ) || lowered.endsWith( ".dsl.dz" ) ? "dsl" :
    lowered.endsWith( ".ifo" )                                       ? "stardict" :
                                                                       "mdx";
}

QJsonObject dictionaryInfo( const DictionaryPtr & dictionary )
{
  const QString id = QString::fromStdString( dictionary->getId() );
  const QString mainPath = dictionaryMainPath( dictionary );
  return {
    { "id", id },
    { "name", QString::fromStdString( dictionary->getName() ) },
    { "format", dictionaryFormat( dictionary ) },
    { "wordCount", static_cast< qint64 >( dictionary->getWordCount() ) },
    { "sourceLanguage", nullableString( languageCode( dictionary->getLangFrom() ) ) },
    { "targetLanguage", nullableString( languageCode( dictionary->getLangTo() ) ) },
    { "iconUrl", QJsonValue( QJsonValue::Null ) },
    { "resourceBaseUrl", "/api/v1/dictionaries/" + id + "/resources/" },
    { "mainPath", mainPath },
  };
}

bool waitFor( Dictionary::Request & request, int timeoutMs, QString & error )
{
  if ( !request.isFinished() ) {
    QEventLoop loop;
    QTimer timer;
    timer.setSingleShot( true );
    QObject::connect( &request, &Dictionary::Request::finished, &loop, &QEventLoop::quit );
    QObject::connect( &timer, &QTimer::timeout, &loop, &QEventLoop::quit );
    timer.start( timeoutMs );
    // The request may complete between the first check and connecting the
    // signal. Recheck after both connections so a fast cached result cannot
    // leave us sleeping until the timeout with an already-finished request.
    if ( !request.isFinished() ) {
      loop.exec();
    }
    if ( !request.isFinished() ) {
      request.cancel();
      error = "GoldenDict-ng request timed out";
      return false;
    }
  }
  error = request.getErrorString();
  return error.isEmpty();
}

QJsonObject failure( const QJsonValue & id, const QString & code, const QString & message )
{
  return {
    { "id", id },
    { "ok", false },
    { "error", QJsonObject{ { "code", code }, { "message", message } } },
  };
}

QJsonObject success( const QJsonValue & id, const QJsonValue & result )
{
  return { { "id", id }, { "ok", true }, { "result", result } };
}

bool isSafeResourcePath( QString path )
{
  path.replace( '\\', '/' );
  while ( path.startsWith( '/' ) ) {
    path.remove( 0, 1 );
  }
  if ( path.isEmpty() ) {
    return false;
  }
  const QStringList parts = path.split( '/', Qt::KeepEmptyParts );
  if ( parts.front().contains( ':' ) ) {
    return false;
  }
  for ( const QString & part : parts ) {
    if ( part.isEmpty() || part == "." || part == ".." ) {
      return false;
    }
    for ( const QChar character : part ) {
      if ( character.unicode() < 0x20 || character.unicode() == 0x7f ) {
        return false;
      }
    }
  }
  return true;
}

std::vector< DictionaryPtr > selectDictionaries( const std::vector< DictionaryPtr > & dictionaries,
                                                 const QJsonArray & requested )
{
  if ( requested.isEmpty() ) {
    return dictionaries;
  }
  std::vector< DictionaryPtr > selected;
  for ( const auto & dictionary : dictionaries ) {
    const QString id = QString::fromStdString( dictionary->getId() );
    if ( std::any_of( requested.begin(), requested.end(), [ & ]( const QJsonValue & value ) {
           return value.toString() == id;
         } ) ) {
      selected.push_back( dictionary );
    }
  }
  return selected;
}

QJsonObject lookup( const QJsonValue & id,
                    const QJsonObject & input,
                    const std::vector< DictionaryPtr > & allDictionaries,
                    int timeoutMs )
{
  const QString word = input.value( "word" ).toString();
  if ( word.isEmpty() ) {
    return failure( id, "validationFailed", "word must be a non-empty string" );
  }

  QElapsedTimer elapsed;
  elapsed.start();
  QJsonArray articles;
  const auto dictionaries = selectDictionaries( allDictionaries, input.value( "dictionaryIds" ).toArray() );
  for ( const auto & dictionary : dictionaries ) {
    auto request = dictionary->getArticle( Text::toUtf32( word.toUtf8().toStdString() ), {} );
    QString error;
    if ( !waitFor( *request, timeoutMs, error ) ) {
      return failure( id, "upstreamRequestFailed", error );
    }
    if ( request->dataSize() <= 0 ) {
      continue;
    }
    const auto & data = request->getFullData();
    const QString dictionaryId = QString::fromStdString( dictionary->getId() );
    articles.append( QJsonObject{
      { "dictionaryId", dictionaryId },
      { "dictionaryName", QString::fromStdString( dictionary->getName() ) },
      { "format", dictionaryFormat( dictionary ) },
      { "html", QString::fromUtf8( data.data(), static_cast< qsizetype >( data.size() ) ) },
      { "sourceLanguage", nullableString( languageCode( dictionary->getLangFrom() ) ) },
      { "targetLanguage", nullableString( languageCode( dictionary->getLangTo() ) ) },
      { "iconUrl", QJsonValue( QJsonValue::Null ) },
      { "resourceBaseUrl", "/api/v1/dictionaries/" + dictionaryId + "/resources/" },
    } );
  }

  return success( id,
                  QJsonObject{
                    { "word", word },
                    { "articles", articles },
                    { "suggestions", QJsonArray{} },
                    { "lookupTimeMs", elapsed.elapsed() },
                  } );
}

QJsonObject suggestions( const QJsonValue & id,
                         const QJsonObject & input,
                         const std::vector< DictionaryPtr > & allDictionaries,
                         int timeoutMs )
{
  const QString prefix = input.value( "prefix" ).toString();
  const int limit = std::clamp( input.value( "limit" ).toInt( 20 ), 1, 100 );
  if ( prefix.isEmpty() ) {
    return failure( id, "validationFailed", "prefix must be a non-empty string" );
  }

  QElapsedTimer elapsed;
  elapsed.start();
  QStringList unique;
  const auto dictionaries = selectDictionaries( allDictionaries, input.value( "dictionaryIds" ).toArray() );
  for ( const auto & dictionary : dictionaries ) {
    auto request = dictionary->prefixMatch( Text::toUtf32( prefix.toUtf8().toStdString() ), limit );
    QString error;
    if ( !waitFor( *request, timeoutMs, error ) ) {
      return failure( id, "upstreamRequestFailed", error );
    }
    for ( const auto & match : request->getAllMatches() ) {
      const QString value = QString::fromUtf8( Text::toUtf8( match.word ) );
      if ( !unique.contains( value, Qt::CaseInsensitive ) ) {
        unique.append( value );
      }
      if ( unique.size() >= limit ) {
        break;
      }
    }
    if ( unique.size() >= limit ) {
      break;
    }
  }

  QJsonArray values;
  for ( const auto & value : unique ) {
    values.append( value );
  }
  return success( id,
                  QJsonObject{
                    { "prefix", prefix },
                    { "suggestions", values },
                    { "lookupTimeMs", elapsed.elapsed() },
                  } );
}

QJsonObject resource( const QJsonValue & id,
                      const QJsonObject & input,
                      const std::vector< DictionaryPtr > & dictionaries,
                      int timeoutMs )
{
  const QString dictionaryId = input.value( "dictionaryId" ).toString();
  const QString path = input.value( "path" ).toString();
  if ( dictionaryId.isEmpty() || path.isEmpty() ) {
    return failure( id, "validationFailed", "dictionaryId and path are required" );
  }
  if ( !isSafeResourcePath( path ) ) {
    return failure( id, "validationFailed", "resource path is unsafe" );
  }

  const auto found = std::find_if( dictionaries.begin(), dictionaries.end(), [ & ]( const DictionaryPtr & value ) {
    return QString::fromStdString( value->getId() ) == dictionaryId;
  } );
  if ( found == dictionaries.end() ) {
    return failure( id, "dictionaryNotFound", "Dictionary was not loaded" );
  }

  auto request = ( *found )->getResource( path.toUtf8().toStdString() );
  QString error;
  if ( !waitFor( *request, timeoutMs, error ) ) {
    return failure( id, "upstreamRequestFailed", error );
  }
  if ( request->dataSize() < 0 ) {
    return failure( id, "resourceNotFound", "Dictionary resource was not found" );
  }

  const auto & data = request->getFullData();
  const QByteArray bytes( data.data(), static_cast< qsizetype >( data.size() ) );
  const QString lowerPath = path.toLower();
  const QString mime = lowerPath.endsWith( ".tif" ) || lowerPath.endsWith( ".tiff" ) ? "image/png" :
    QMimeDatabase{}.mimeTypeForFile( path, QMimeDatabase::MatchExtension ).name();
  return success( id,
                  QJsonObject{
                    { "dictionaryId", dictionaryId },
                    { "path", path },
                    { "mediaType", mime.isEmpty() ? "application/octet-stream" : mime },
                    { "bodyBase64", QString::fromLatin1( bytes.toBase64() ) },
                  } );
}

void writeJson( const QJsonObject & value )
{
  std::cout << QJsonDocument( value ).toJson( QJsonDocument::Compact ).constData() << '\n' << std::flush;
}

} // namespace

int main( int argc, char ** argv )
{
  QCoreApplication app( argc, argv );
  QCoreApplication::setApplicationName( "goldendict-native-worker" );

  QStringList roots;
  QString indexDir = QStandardPaths::writableLocation( QStandardPaths::CacheLocation ) + "/indices";
  int timeoutMs = 30000;
  for ( int i = 1; i < argc; ++i ) {
    const QString arg = QString::fromLocal8Bit( argv[ i ] );
    if ( arg == "--dictionary-root" && i + 1 < argc ) {
      roots.append( QString::fromLocal8Bit( argv[ ++i ] ) );
    }
    else if ( arg == "--index-dir" && i + 1 < argc ) {
      indexDir = QString::fromLocal8Bit( argv[ ++i ] );
    }
    else if ( arg == "--timeout-ms" && i + 1 < argc ) {
      timeoutMs = QString::fromLocal8Bit( argv[ ++i ] ).toInt();
    }
    else {
      std::cerr << "usage: goldendict-native-worker --dictionary-root PATH [--dictionary-root PATH ...] "
                   "[--index-dir PATH] [--timeout-ms N]\n";
      return 2;
    }
  }
  if ( roots.isEmpty() ) {
    std::cerr << "at least one --dictionary-root is required\n";
    return 2;
  }

  QDir().mkpath( indexDir );
  indexDir = QDir( indexDir ).absolutePath() + QDir::separator();
  std::vector< std::string > dictionaryFiles;
  for ( const auto & root : roots ) {
    QDirIterator iterator( root, QDir::Files, QDirIterator::Subdirectories );
    while ( iterator.hasNext() ) {
      dictionaryFiles.push_back( QFileInfo( iterator.next() ).absoluteFilePath().toUtf8().toStdString() );
    }
  }
  std::sort( dictionaryFiles.begin(), dictionaryFiles.end() );
  dictionaryFiles.erase( std::unique( dictionaryFiles.begin(), dictionaryFiles.end() ), dictionaryFiles.end() );

  Initializing initializing;
  std::vector< DictionaryPtr > dictionaries;
  try {
    const std::string nativeIndexDir = indexDir.toUtf8().toStdString();
    auto append = [ &dictionaries ]( std::vector< DictionaryPtr > && values ) {
      dictionaries.insert( dictionaries.end(),
                           std::make_move_iterator( values.begin() ),
                           std::make_move_iterator( values.end() ) );
    };
    append( Mdx::makeDictionaries( dictionaryFiles, nativeIndexDir, initializing ) );
    append( Stardict::makeDictionaries( dictionaryFiles, nativeIndexDir, initializing, 0 ) );
    append( Dsl::makeDictionaries( dictionaryFiles, nativeIndexDir, initializing, 256 ) );
  }
  catch ( const std::exception & error ) {
    std::cerr << "failed to load dictionaries: " << error.what() << '\n';
    return 1;
  }

  QJsonArray metadata;
  for ( const auto & dictionary : dictionaries ) {
    metadata.append( dictionaryInfo( dictionary ) );
  }
  writeJson( QJsonObject{
    { "event", "ready" },
    { "upstreamCommit", GOLDENDICT_NG_COMMIT },
    { "upstreamDirty", QStringLiteral( GOLDENDICT_NG_DIRTY ) == "true" },
    { "upstreamDiffSha256", GOLDENDICT_NG_DIFF_SHA256 },
    { "dictionaries", metadata },
  } );

  QTextStream input( stdin, QIODevice::ReadOnly );
  while ( !input.atEnd() ) {
    const QString line = input.readLine();
    if ( line.trimmed().isEmpty() ) {
      continue;
    }
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson( line.toUtf8(), &parseError );
    if ( parseError.error != QJsonParseError::NoError || !document.isObject() ) {
      writeJson( failure( {}, "invalidJson", parseError.errorString() ) );
      continue;
    }
    const QJsonObject request = document.object();
    const QJsonValue id = request.value( "id" );
    const QString operation = request.value( "op" ).toString();
    if ( operation == "list" ) {
      writeJson( success( id, metadata ) );
    }
    else if ( operation == "lookup" ) {
      writeJson( lookup( id, request, dictionaries, timeoutMs ) );
    }
    else if ( operation == "suggestions" ) {
      writeJson( suggestions( id, request, dictionaries, timeoutMs ) );
    }
    else if ( operation == "resource" ) {
      writeJson( resource( id, request, dictionaries, timeoutMs ) );
    }
    else {
      writeJson( failure( id, "unsupportedOperation", "Supported operations: list, lookup, suggestions, resource" ) );
    }
  }

  return 0;
}
