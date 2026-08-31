# Create the one patched upstream translation unit used by the headless worker.
#
# GoldenDict-ng's desktop process trusts dictionary directories. Its MDX local
# resource path consequently concatenates the requested name and follows
# MDD @@@LINK redirects without a canonical-path boundary. That trust model is
# not suitable for a network resource endpoint. Keep this hardening as an exact
# source transformation: an upstream edit to the affected function fails at
# configure time and must be deliberately rebased during an upgrade.

set(_mdx_input "${GD_SRC}/dict/mdx.cc")
set(_mdx_output_dir "${CMAKE_CURRENT_BINARY_DIR}/patched-upstream/dict")
set(GOLDENDICT_PATCHED_MDX_SOURCE "${_mdx_output_dir}/mdx.cc")

file(READ "${_mdx_input}" _mdx_source)

set(_include_before [=[#include <QDir>
]=])
set(_include_after [=[#include "resource_guard.hh"
#include <QDir>
]=])

set(_function_before [=[void MdxDictionary::loadResourceFile( const std::u32string & resourceName, vector< char > & data )
{
  std::u32string newResourceName = resourceName;
  string u8ResourceName          = Text::toUtf8( resourceName );

  // Convert to the Windows separator
  std::replace( newResourceName.begin(), newResourceName.end(), '/', '\\' );
  if ( newResourceName[ 0 ] == '.' ) {
    newResourceName.erase( 0, 1 );
  }
  if ( newResourceName[ 0 ] != '\\' ) {
    newResourceName.insert( 0, 1, '\\' );
  }
  // local file takes precedence
  if ( string fn = getContainingFolder().toStdString() + Utils::Fs::separator() + u8ResourceName;
       Utils::Fs::exists( fn ) ) {
    File::loadFromFile( fn, data );
    return;
  }
  for ( const auto & mddResource : mddResources ) {
    if ( mddResource->loadFile( newResourceName, data ) ) {
      break;
    }
  }
}
]=])

set(_function_after [=[void MdxDictionary::loadResourceFile( const std::u32string & resourceName, vector< char > & data )
{
  if ( resourceName.empty() ) {
    return;
  }

  std::u32string newResourceName = resourceName;
  string u8ResourceName          = Text::toUtf8( resourceName );

  // Convert to the Windows separator
  std::replace( newResourceName.begin(), newResourceName.end(), '/', '\\' );
  if ( newResourceName[ 0 ] == '.' ) {
    newResourceName.erase( 0, 1 );
  }
  if ( newResourceName.empty() ) {
    return;
  }
  if ( newResourceName[ 0 ] != '\\' ) {
    newResourceName.insert( 0, 1, '\\' );
  }

  // Local sidecars take precedence, but unlike the desktop application this
  // worker exposes resources over HTTP. Resolve the final target after every
  // MDD redirect and require it to remain inside the dictionary directory.
  const auto localResource = HeadlessResourceGuard::resolveLocalResource(
    getContainingFolder(), QString::fromUtf8( u8ResourceName ) );
  if ( localResource.status == HeadlessResourceGuard::Status::Allowed ) {
    File::loadFromFile( localResource.canonicalPath.toStdString(), data );
    return;
  }
  if ( localResource.status == HeadlessResourceGuard::Status::Blocked ) {
    qWarning( "Mdx: blocked resource outside dictionary directory: %s", u8ResourceName.c_str() );
    return;
  }

  for ( const auto & mddResource : mddResources ) {
    if ( mddResource->loadFile( newResourceName, data ) ) {
      break;
    }
  }
}
]=])

foreach(_needle IN ITEMS _include_before _function_before)
  string(FIND "${_mdx_source}" "${${_needle}}" _first_match)
  if(_first_match EQUAL -1)
    message(FATAL_ERROR
      "GoldenDict-ng MDX resource hardening no longer applies at ${GOLDENDICT_NG_COMMIT}; "
      "rebase cmake/prepare_mdx_source.cmake before upgrading")
  endif()
  string(LENGTH "${${_needle}}" _needle_length)
  math(EXPR _tail_start "${_first_match} + ${_needle_length}")
  string(SUBSTRING "${_mdx_source}" ${_tail_start} -1 _tail)
  string(FIND "${_tail}" "${${_needle}}" _second_match)
  if(NOT _second_match EQUAL -1)
    message(FATAL_ERROR "GoldenDict-ng MDX resource hardening anchor is ambiguous")
  endif()
endforeach()

string(REPLACE "${_include_before}" "${_include_after}" _mdx_source "${_mdx_source}")
string(REPLACE "${_function_before}" "${_function_after}" _mdx_source "${_mdx_source}")
file(MAKE_DIRECTORY "${_mdx_output_dir}")
file(WRITE "${GOLDENDICT_PATCHED_MDX_SOURCE}" "${_mdx_source}")
