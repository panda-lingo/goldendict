#include "resource_guard.hh"

#include <QDir>
#include <QFile>
#include <QTemporaryDir>

#include <filesystem>
#include <iostream>

namespace {

bool require( bool condition, const char * message )
{
  if ( !condition ) {
    std::cerr << message << '\n';
  }
  return condition;
}

bool writeFile( const QString & path, const QByteArray & body )
{
  QFile file( path );
  return file.open( QIODevice::WriteOnly ) && file.write( body ) == body.size();
}

} // namespace

int main()
{
  QTemporaryDir temporary;
  if ( !require( temporary.isValid(), "could not create temporary directory" ) ) {
    return 1;
  }

  const QString root = temporary.filePath( "dictionary" );
  const QString nested = root + "/scripts";
  if ( !require( QDir().mkpath( nested ), "could not create dictionary directory" ) ) {
    return 1;
  }
  const QString sidecar = nested + "/Dictionary-UI.js";
  const QString outside = temporary.filePath( "outside.js" );
  if ( !require( writeFile( sidecar, "sidecar" ) && writeFile( outside, "secret" ), "could not write fixtures" ) ) {
    return 1;
  }

  const auto allowed = HeadlessResourceGuard::resolveLocalResource( root, "scripts/Dictionary-UI.js" );
  if ( !require( allowed.status == HeadlessResourceGuard::Status::Allowed, "nested sidecar was rejected" )
       || !require( allowed.canonicalPath == QFileInfo( sidecar ).canonicalFilePath(),
                    "sidecar canonical path changed" ) ) {
    return 1;
  }

  const auto traversal = HeadlessResourceGuard::resolveLocalResource( root, "../outside.js" );
  if ( !require( traversal.status == HeadlessResourceGuard::Status::Blocked, "dot traversal was allowed" ) ) {
    return 1;
  }

  const QString link = root + "/leak.js";
  std::filesystem::create_symlink( outside.toStdString(), link.toStdString() );
  const auto symlink = HeadlessResourceGuard::resolveLocalResource( root, "leak.js" );
  if ( !require( symlink.status == HeadlessResourceGuard::Status::Blocked, "escaping symlink was allowed" ) ) {
    return 1;
  }

  const auto missing = HeadlessResourceGuard::resolveLocalResource( root, "from-mdd.js" );
  if ( !require( missing.status == HeadlessResourceGuard::Status::Missing,
                 "missing sidecar did not fall through to MDD lookup" ) ) {
    return 1;
  }
  return 0;
}
