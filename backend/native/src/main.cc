#include "dict/dictionary.hh"
#include "dict/aard.hh"
#include "dict/bgl.hh"
#include "dict/dictdfiles.hh"
#include "dict/dsl.hh"
#include "dict/epwing.hh"
#include "dict/gls.hh"
#include "dict/lsa.hh"
#include "dict/mdx.hh"
#include "dict/sdict.hh"
#include "dict/slob.hh"
#include "dict/stardict.hh"
#include "dict/xdxf.hh"
#include "dict/zim.hh"
#include "dict/zipsounds.hh"
#include "globalbroadcaster.hh"
#include "langcoder.hh"
#include "metadata.hh"
#include "text.hh"

#include <QBuffer>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileInfo>
#include <QGuiApplication>
#include <QHash>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMimeDatabase>
#include <QSet>
#include <QStandardPaths>
#include <QTextStream>
#include <QTimer>

#include <algorithm>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace {

using DictionaryPtr = sptr< Dictionary::Class >;
using DictionaryIcons = std::map< std::string, QByteArray >;

constexpr auto DictionaryIconResourcePath = ".goldendict-ng/dicticon.png";

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
  QStringList filenames{ dictionaryMainPath( dictionary ).toLower() };
  for ( const auto & filename : dictionary->getDictionaryFilenames() ) {
    const QString lowered = QString::fromUtf8( filename ).toLower();
    if ( !filenames.contains( lowered ) ) {
      filenames.append( lowered );
    }
  }
  const auto hasSuffix = [ &filenames ]( const QString & suffix ) {
    return std::any_of( filenames.cbegin(), filenames.cend(), [ &suffix ]( const QString & filename ) {
      return filename.endsWith( suffix );
    } );
  };
  if ( hasSuffix( ".bgl" ) ) {
    return "bgl";
  }
  if ( hasSuffix( ".ifo" ) ) {
    return "stardict";
  }
  if ( hasSuffix( ".lsa" ) ) {
    return "lsa";
  }
  if ( hasSuffix( ".dsl" ) || hasSuffix( ".dsl.dz" ) ) {
    return "dsl";
  }
  if ( hasSuffix( ".index" ) ) {
    return "dictd";
  }
  if ( hasSuffix( ".xdxf" ) || hasSuffix( ".xdxf.dz" ) ) {
    return "xdxf";
  }
  if ( hasSuffix( ".dct" ) ) {
    return "sdict";
  }
  if ( hasSuffix( ".aar" ) ) {
    return "aard";
  }
  if ( hasSuffix( ".zips" ) ) {
    return "zipsounds";
  }
  if ( hasSuffix( ".mdx" ) ) {
    return "mdx";
  }
  if ( hasSuffix( ".gls" ) || hasSuffix( ".gls.dz" ) ) {
    return "gls";
  }
  if ( hasSuffix( ".slob" ) ) {
    return "slob";
  }
  if ( hasSuffix( ".zim" ) || hasSuffix( ".zimaa" ) ) {
    return "zim";
  }
  if ( std::any_of( filenames.cbegin(), filenames.cend(), []( const QString & filename ) {
         return QFileInfo( filename ).fileName() == "catalogs";
       } ) ) {
    return "epwing";
  }
  return "unknown";
}

QJsonArray supportedFormats()
{
  return {
    "bgl",       "stardict", "lsa",  "dsl", "dictd", "xdxf", "sdict",
    "aard",      "zipsounds", "mdx", "gls", "slob",  "zim",  "epwing",
  };
}

QByteArray dictionaryIconPng( const DictionaryPtr & dictionary )
{
  QByteArray bytes;
  QBuffer buffer( &bytes );
  if ( !buffer.open( QIODevice::WriteOnly ) || !dictionary->getIcon().pixmap( 64 ).save( &buffer, "PNG" ) ) {
    return {};
  }
  return bytes;
}

QJsonObject dictionaryInfo( const DictionaryPtr & dictionary, bool hasIcon )
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
    { "iconResourcePath",
      hasIcon ? QJsonValue( DictionaryIconResourcePath ) : QJsonValue( QJsonValue::Null ) },
    { "resourceBaseUrl", "/api/v1/dictionaries/" + id + "/resources/" },
    { "mainPath", mainPath },
  };
}

bool waitUntilFinished( Dictionary::Request & request, int timeoutMs, QString & error )
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
  return true;
}

bool waitFor( Dictionary::Request & request, int timeoutMs, QString & error )
{
  if ( !waitUntilFinished( request, timeoutMs, error ) ) {
    return false;
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

struct DictionaryFileCatalog
{
  std::vector< std::string > files;
  QHash< QString, int > folderOrder;
  QSet< QString > visitedFolders;
};

void collectDictionaryFiles( const QString & path, DictionaryFileCatalog & catalog )
{
  const QDir directory( path );
  const QString folder = directory.absolutePath();
  const QString canonicalFolder = QFileInfo( folder ).canonicalFilePath();
  const QString visitKey = canonicalFolder.isEmpty() ? folder : canonicalFolder;
  if ( catalog.visitedFolders.contains( visitKey ) ) {
    return;
  }
  catalog.visitedFolders.insert( visitKey );

  static const QStringList nameFilters{
    "*.bgl",  "*.ifo",     "*.lsa",     "*.dat",  "*.dsl",  "*.dsl.dz", "*.index",
    "*.xdxf", "*.xdxf.dz", "*.dct",     "*.aar",  "*.zips", "*.mdx",    "*.gls",
    "*.gls.dz", "*.slob",  "*.zim",     "*.zimaa", "*catalogs",
  };
  const QFileInfoList entries = directory.entryInfoList(
    nameFilters, QDir::AllDirs | QDir::Files | QDir::NoDotAndDotDot );
  std::vector< std::string > localFiles;
  for ( const QFileInfo & entry : entries ) {
    if ( entry.isDir() ) {
      const QString child = entry.absoluteFilePath();
      if ( !entry.isSymLink() && !child.endsWith( ".dsl.files", Qt::CaseInsensitive )
           && !child.endsWith( ".dsl.dz.files", Qt::CaseInsensitive ) ) {
        collectDictionaryFiles( child, catalog );
      }
    }
    else {
      localFiles.push_back( QDir::toNativeSeparators( entry.absoluteFilePath() ).toUtf8().toStdString() );
    }
  }
  if ( !localFiles.empty() ) {
    catalog.folderOrder.insert( folder, catalog.folderOrder.size() );
    catalog.files.insert(
      catalog.files.end(), std::make_move_iterator( localFiles.begin() ), std::make_move_iterator( localFiles.end() ) );
  }
}

std::vector< DictionaryPtr > selectDictionaries( const std::vector< DictionaryPtr > & dictionaries,
                                                 const QJsonArray & requested )
{
  if ( requested.isEmpty() ) {
    return dictionaries;
  }
  QSet< QString > requestedIds;
  requestedIds.reserve( requested.size() );
  for ( const QJsonValue & value : requested ) {
    if ( value.isString() ) {
      requestedIds.insert( value.toString() );
    }
  }
  std::vector< DictionaryPtr > selected;
  selected.reserve( std::min< qsizetype >( dictionaries.size(), requestedIds.size() ) );
  for ( const auto & dictionary : dictionaries ) {
    const QString id = QString::fromStdString( dictionary->getId() );
    if ( requestedIds.contains( id ) ) {
      selected.push_back( dictionary );
    }
  }
  return selected;
}

struct PendingArticle
{
  DictionaryPtr dictionary;
  sptr< Dictionary::DataRequest > request;
};

struct PendingWordSearch
{
  sptr< Dictionary::WordSearchRequest > request;
};

bool waitForUntil( Dictionary::Request & request,
                   int timeoutMs,
                   const QElapsedTimer & elapsed,
                   QString & error )
{
  if ( !request.isFinished() && elapsed.elapsed() >= timeoutMs ) {
    request.cancel();
    error = "GoldenDict-ng request timed out";
    return false;
  }
  return waitUntilFinished(
    request, std::max( 1, timeoutMs - static_cast< int >( elapsed.elapsed() ) ), error );
}

void cancelArticles( std::vector< PendingArticle > & articles )
{
  for ( auto & pending : articles ) {
    if ( !pending.request->isFinished() ) {
      pending.request->cancel();
    }
  }
}

void cancelWordSearches( std::vector< PendingWordSearch > & requests )
{
  for ( auto & pending : requests ) {
    if ( !pending.request->isFinished() ) {
      pending.request->cancel();
    }
  }
}

bool collectSynonyms( std::vector< PendingWordSearch > & pending,
                      int timeoutMs,
                      const QElapsedTimer & elapsed,
                      std::vector< std::u32string > & values,
                      QString & error )
{
  std::set< std::u32string > unique;
  for ( auto & item : pending ) {
    if ( !waitForUntil( *item.request, timeoutMs, elapsed, error ) ) {
      return false;
    }
    // ArticleMaker consumes any matches a completed synonym request exposes,
    // even if that request also carries a dictionary-local error.
    for ( const auto & match : item.request->getAllMatches() ) {
      unique.insert( match.word );
    }
  }
  values.assign( unique.cbegin(), unique.cend() );
  return true;
}

bool collectSuggestions( std::vector< PendingWordSearch > & pending,
                         int limit,
                         int timeoutMs,
                         const QElapsedTimer & elapsed,
                         QJsonArray & values,
                         QString & error )
{
  // std::u32string ordering matches Python's code-point ordering used by the
  // public API. Keep the first display spelling for each normalized key.
  std::map< std::u32string, QString > unique;
  for ( auto & item : pending ) {
    if ( !waitForUntil( *item.request, timeoutMs, elapsed, error ) ) {
      return false;
    }
    // GoldenDict-ng's WordFinder keeps matches from healthy dictionaries when
    // another prefix request reports a dictionary-local error.
    if ( !item.request->getErrorString().isEmpty() ) {
      continue;
    }
    for ( const auto & match : item.request->getAllMatches() ) {
      const QString value = QString::fromUtf8( Text::toUtf8( match.word ) );
      const QString normalized = value.normalized( QString::NormalizationForm_KC ).trimmed().toCaseFolded();
      if ( !normalized.isEmpty() ) {
        unique.emplace( Text::toUtf32( normalized.toUtf8().toStdString() ), value );
      }
    }
  }
  for ( const auto & item : unique ) {
    values.append( item.second );
    if ( values.size() >= limit ) {
      break;
    }
  }
  return true;
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
  const int suggestionLimit = std::clamp( input.value( "suggestionLimit" ).toInt( 0 ), 0, 100 );
  const std::u32string nativeWord = Text::toUtf32( word.toUtf8().toStdString() );
  std::vector< PendingArticle > pendingArticles;
  std::vector< PendingWordSearch > pendingSynonyms;
  std::vector< PendingWordSearch > pendingSuggestions;
  pendingArticles.reserve( dictionaries.size() );
  pendingSynonyms.reserve( dictionaries.size() );
  pendingSuggestions.reserve( suggestionLimit > 0 ? dictionaries.size() : 0 );

  // ArticleMaker resolves synonym headwords across the active catalog before
  // it asks each dictionary for an article. Start that phase together with
  // WordFinder-style prefix work so the two independent searches overlap.
  for ( const auto & dictionary : dictionaries ) {
    try {
      pendingSynonyms.push_back( { dictionary->findHeadwordsForSynonym( nativeWord ) } );
    }
    catch ( const std::exception & error ) {
      std::cerr << "synonym request error in " << dictionary->getName() << ": " << error.what() << '\n';
    }
    if ( suggestionLimit > 0 ) {
      try {
        pendingSuggestions.push_back( { dictionary->prefixMatch( nativeWord, suggestionLimit ) } );
      }
      catch ( const std::exception & error ) {
        // WordFinder keeps healthy dictionaries when one request cannot be
        // constructed, so a local failure must not reject the whole lookup.
        std::cerr << "prefix request error in " << dictionary->getName() << ": " << error.what() << '\n';
      }
    }
  }

  std::vector< std::u32string > alternateHeadwords;
  QString synonymError;
  if ( !collectSynonyms( pendingSynonyms, timeoutMs, elapsed, alternateHeadwords, synonymError ) ) {
    cancelWordSearches( pendingSynonyms );
    cancelWordSearches( pendingSuggestions );
    return failure( id, "upstreamRequestFailed", synonymError );
  }

  // Once the shared alternates are known, launch every article request before
  // waiting so parsing, index reads, and decompression overlap across formats.
  for ( const auto & dictionary : dictionaries ) {
    try {
      pendingArticles.push_back(
        { dictionary, dictionary->getArticle( nativeWord, alternateHeadwords ) } );
    }
    catch ( const std::exception & error ) {
      // ArticleMaker logs and skips a dictionary whose request construction
      // fails while allowing the remaining articles to render.
      std::cerr << "article request error in " << dictionary->getName() << ": " << error.what() << '\n';
    }
  }

  for ( auto & pending : pendingArticles ) {
    QString timeoutError;
    if ( !waitForUntil( *pending.request, timeoutMs, elapsed, timeoutError ) ) {
      cancelArticles( pendingArticles );
      cancelWordSearches( pendingSuggestions );
      return failure( id, "upstreamRequestFailed", timeoutError );
    }
    const QString requestError = pending.request->getErrorString();
    if ( pending.request->dataSize() < 0 && requestError.isEmpty() ) {
      continue;
    }
    QString html;
    if ( requestError.isEmpty() ) {
      if ( pending.request->dataSize() > 0 ) {
        try {
          const auto & data = pending.request->getFullData();
          html = QString::fromUtf8( data.data(), static_cast< qsizetype >( data.size() ) );
        }
        catch ( const std::exception & error ) {
          // ArticleMaker logs slice/materialization errors but retains the
          // dictionary header with an empty body.
          std::cerr << "getFullData error: " << error.what() << '\n';
        }
      }
      // A successful zero-byte request is still an article in ArticleMaker;
      // publish its empty fragment so the frontend retains the dictionary
      // header instead of inventing an error or treating it as no match.
    }
    else {
      // ArticleMaker renders a failed dictionary alongside successful ones;
      // preserve its canonical error fragment instead of failing the batch.
      html = QStringLiteral( "<div class=\"gderrordesc\">Query error: %1</div>" )
               .arg( requestError.toHtmlEscaped() );
    }
    const QString dictionaryId = QString::fromStdString( pending.dictionary->getId() );
    articles.append( QJsonObject{
      { "dictionaryId", dictionaryId },
      { "dictionaryName", QString::fromStdString( pending.dictionary->getName() ) },
      { "format", dictionaryFormat( pending.dictionary ) },
      { "html", html },
      { "sourceLanguage", nullableString( languageCode( pending.dictionary->getLangFrom() ) ) },
      { "targetLanguage", nullableString( languageCode( pending.dictionary->getLangTo() ) ) },
      { "iconUrl", QJsonValue( QJsonValue::Null ) },
      { "resourceBaseUrl", "/api/v1/dictionaries/" + dictionaryId + "/resources/" },
    } );
  }

  QJsonArray suggestionValues;
  QString suggestionError;
  if ( suggestionLimit > 0
       && !collectSuggestions(
         pendingSuggestions, suggestionLimit, timeoutMs, elapsed, suggestionValues, suggestionError ) ) {
    cancelArticles( pendingArticles );
    cancelWordSearches( pendingSuggestions );
    return failure( id, "upstreamRequestFailed", suggestionError );
  }

  return success( id,
                  QJsonObject{
                    { "word", word },
                    { "articles", articles },
                    { "suggestions", suggestionValues },
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
  const auto dictionaries = selectDictionaries( allDictionaries, input.value( "dictionaryIds" ).toArray() );
  const std::u32string nativePrefix = Text::toUtf32( prefix.toUtf8().toStdString() );
  std::vector< PendingWordSearch > pending;
  pending.reserve( dictionaries.size() );
  for ( const auto & dictionary : dictionaries ) {
    try {
      pending.push_back( { dictionary->prefixMatch( nativePrefix, limit ) } );
    }
    catch ( const std::exception & error ) {
      std::cerr << "prefix request error in " << dictionary->getName() << ": " << error.what() << '\n';
    }
  }

  QJsonArray values;
  QString error;
  if ( !collectSuggestions( pending, limit, timeoutMs, elapsed, values, error ) ) {
    cancelWordSearches( pending );
    return failure( id, "upstreamRequestFailed", error );
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
                      const DictionaryIcons & dictionaryIcons,
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

  const auto icon = dictionaryIcons.find( ( *found )->getId() );
  if ( path == DictionaryIconResourcePath && icon != dictionaryIcons.end() ) {
    return success( id,
                    QJsonObject{
                      { "dictionaryId", dictionaryId },
                      { "path", path },
                      { "mediaType", "image/png" },
                      { "bodyBase64", QString::fromLatin1( icon->second.toBase64() ) },
                    } );
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
  // QIcon/QPixmap need a GUI application even though this process has no
  // windows. The offscreen QPA backend preserves upstream custom/generated
  // dictionary icons in containers and other headless environments.
  if ( qEnvironmentVariableIsEmpty( "QT_QPA_PLATFORM" ) ) {
    qputenv( "QT_QPA_PLATFORM", "offscreen" );
  }
  QGuiApplication app( argc, argv );
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
  DictionaryFileCatalog fileCatalog;
  for ( const auto & root : roots ) {
    collectDictionaryFiles( root, fileCatalog );
  }

  Initializing initializing;
  std::vector< DictionaryPtr > dictionaries;
  try {
    const std::string nativeIndexDir = indexDir.toUtf8().toStdString();
    std::map< const Dictionary::Class *, int > factoryOrder;
    auto append = [ &dictionaries, &factoryOrder ]( std::vector< DictionaryPtr > && values, int rank ) {
      for ( const auto & dictionary : values ) {
        factoryOrder.emplace( dictionary.get(), rank );
      }
      dictionaries.insert( dictionaries.end(),
                           std::make_move_iterator( values.begin() ),
                           std::make_move_iterator( values.end() ) );
    };
    // Keep this order identical to GoldenDict-ng's
    // LoadDictionaries::handlePath() so ownership and companion-file
    // behavior remain upstream-compatible.
    append( Bgl::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 0 );
    append( Stardict::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing, 0 ), 1 );
    append( Lsa::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 2 );
    append( Dsl::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing, 256 ), 3 );
    append( DictdFiles::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 4 );
    append( Xdxf::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 5 );
    append( Sdict::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 6 );
    append( Aard::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing, 0 ), 7 );
    append( ZipSounds::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 8 );
    append( Mdx::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 9 );
    append( Gls::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 10 );
    append( Slob::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing, 0 ), 11 );
    append( Zim::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing, 0 ), 12 );
    append( Epwing::makeDictionaries( fileCatalog.files, nativeIndexDir, initializing ), 13 );
    // Factories are invoked once for startup efficiency, but GoldenDict-ng's
    // recursive handlePath() publishes every directory's factory results
    // before moving to its parent/next path. Restore that catalog order after
    // construction so article and generated-icon ordering remain identical.
    std::stable_sort( dictionaries.begin(), dictionaries.end(), [ & ]( const DictionaryPtr & left,
                                                                       const DictionaryPtr & right ) {
      const int unknownFolder = std::numeric_limits< int >::max();
      const int leftFolder = fileCatalog.folderOrder.value( left->getContainingFolder(), unknownFolder );
      const int rightFolder = fileCatalog.folderOrder.value( right->getContainingFolder(), unknownFolder );
      if ( leftFolder != rightFolder ) {
        return leftFolder < rightFolder;
      }
      return factoryOrder.at( left.get() ) < factoryOrder.at( right.get() );
    } );
    // Apply the same per-directory metadata.toml name and FTS overrides as
    // GoldenDict-ng's LoadDictionaries::load(). Categories belong to desktop
    // group configuration and have no catalog field in this service.
    for ( const auto & dictionary : dictionaries ) {
      const QString baseDir = dictionary->getContainingFolder();
      if ( baseDir.isEmpty() ) {
        continue;
      }
      const auto metadata = Metadata::load( QDir( baseDir ).filePath( "metadata.toml" ).toStdString() );
      if ( metadata && metadata->name ) {
        dictionary->setName( *metadata->name );
      }
      if ( metadata && metadata->fullindex ) {
        dictionary->setFtsEnabled( *metadata->fullindex );
      }
    }
    GlobalBroadcaster::instance()->setAllDictionaries( &dictionaries );
    for ( const auto & dictionary : dictionaries ) {
      // Match Config::Preferences' desktop default before any BGL, StarDict,
      // GLS, or EPWING synonym coordination can inspect this upstream field.
      dictionary->setSynonymSearchEnabled( true );
      dictionary->deferredInit();
    }
  }
  catch ( const std::exception & error ) {
    std::cerr << "failed to load dictionaries: " << error.what() << '\n';
    return 1;
  }

  QJsonArray metadata;
  DictionaryIcons dictionaryIcons;
  for ( const auto & dictionary : dictionaries ) {
    QByteArray icon = dictionaryIconPng( dictionary );
    const bool hasIcon = !icon.isEmpty();
    if ( hasIcon ) {
      dictionaryIcons.emplace( dictionary->getId(), std::move( icon ) );
    }
    metadata.append( dictionaryInfo( dictionary, hasIcon ) );
  }
  writeJson( QJsonObject{
    { "event", "ready" },
    { "upstreamCommit", GOLDENDICT_NG_COMMIT },
    { "upstreamDirty", QStringLiteral( GOLDENDICT_NG_DIRTY ) == "true" },
    { "upstreamDiffSha256", GOLDENDICT_NG_DIFF_SHA256 },
    { "supportedFormats", supportedFormats() },
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
    try {
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
        writeJson( resource( id, request, dictionaries, dictionaryIcons, timeoutMs ) );
      }
      else {
        writeJson(
          failure( id, "unsupportedOperation", "Supported operations: list, lookup, suggestions, resource" ) );
      }
    }
    catch ( const std::exception & error ) {
      writeJson( failure( id, "upstreamRequestFailed", QString::fromUtf8( error.what() ) ) );
    }
    catch ( ... ) {
      writeJson( failure( id, "upstreamRequestFailed", "GoldenDict-ng request failed" ) );
    }
  }

  return 0;
}
