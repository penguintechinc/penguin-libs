import 'dart:developer' as developer;
import 'version_info.dart';

/// Log version info to the developer console with ASCII banner.
///
/// Outputs a formatted banner with app name, version, and build info.
void logVersionToConsole(
  String appName,
  VersionInfo versionInfo, {
  String? environment,
  Map<String, String>? metadata,
}) {
  final buffer = StringBuffer();

  buffer.writeln('');
  buffer.writeln('╔══════════════════════════════════════╗');
  buffer.writeln('║  🐧 $appName');
  buffer.writeln('║  Version: ${versionInfo.semver}');
  if (versionInfo.buildDate != null) {
    buffer.writeln('║  Build: ${versionInfo.buildDate}');
  }
  if (versionInfo.buildEpoch != null) {
    buffer.writeln('║  Epoch: ${versionInfo.buildEpoch}');
  }
  if (environment != null) {
    buffer.writeln('║  Environment: $environment');
  }
  if (metadata != null) {
    for (final entry in metadata.entries) {
      buffer.writeln('║  ${entry.key}: ${entry.value}');
    }
  }
  buffer.writeln('╚══════════════════════════════════════╝');
  buffer.writeln('');

  developer.log(buffer.toString(), name: appName);
}
