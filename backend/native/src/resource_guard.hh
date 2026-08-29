#pragma once

#include <QDir>
#include <QFileInfo>
#include <QString>

namespace HeadlessResourceGuard {

enum class Status
{
  Missing,
  Allowed,
  Blocked,
};

struct Result
{
  Status status;
  QString canonicalPath;
};

inline Result resolveLocalResource( const QString & dictionaryFolder, const QString & resourceName )
{
  if ( resourceName.isEmpty() ) {
    return { Status::Blocked, {} };
  }

  const QDir rootDirectory( dictionaryFolder );
  const QFileInfo rootInfo( rootDirectory.absolutePath() );
  const QFileInfo candidateInfo( rootDirectory.absoluteFilePath( resourceName ) );
  if ( !candidateInfo.exists() ) {
    return { Status::Missing, {} };
  }

  const QString canonicalRoot      = rootInfo.canonicalFilePath();
  const QString canonicalCandidate = candidateInfo.canonicalFilePath();
  const QString rootPrefix         = canonicalRoot + QDir::separator();
  if ( canonicalRoot.isEmpty() || canonicalCandidate.isEmpty()
       || ( canonicalCandidate != canonicalRoot && !canonicalCandidate.startsWith( rootPrefix ) ) ) {
    return { Status::Blocked, {} };
  }
  return { Status::Allowed, canonicalCandidate };
}

} // namespace HeadlessResourceGuard
