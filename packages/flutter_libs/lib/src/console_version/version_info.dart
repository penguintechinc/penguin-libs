/// Parsed version information.
///
/// Supports formats: "vX.Y.Z.epoch", "X.Y.Z.epoch", "X.Y.Z"
class VersionInfo {
  const VersionInfo({
    required this.full,
    required this.major,
    required this.minor,
    required this.patch,
    this.buildEpoch,
    this.buildDate,
  });

  final String full;
  final int major;
  final int minor;
  final int patch;
  final int? buildEpoch;
  final String? buildDate;

  /// Semantic version string (e.g., "1.0.0").
  String get semver => '$major.$minor.$patch';
}

/// Parse a version string into [VersionInfo].
///
/// Supports formats:
/// - "vX.Y.Z.epoch" or "X.Y.Z.epoch"
/// - "X.Y.Z"
/// - Optionally provide [buildEpoch] to override the epoch from the string.
VersionInfo parseVersion(String version, {int? buildEpoch}) {
  final cleaned = version.startsWith('v') ? version.substring(1) : version;
  final parts = cleaned.split('.');

  final major = int.tryParse(parts.isNotEmpty ? parts[0] : '0') ?? 0;
  final minor = int.tryParse(parts.length > 1 ? parts[1] : '0') ?? 0;
  final patch = int.tryParse(parts.length > 2 ? parts[2] : '0') ?? 0;
  final epoch = buildEpoch ??
      (parts.length > 3 ? int.tryParse(parts[3]) : null);

  String? buildDate;
  if (epoch != null) {
    buildDate = DateTime.fromMillisecondsSinceEpoch(
      epoch * 1000,
      isUtc: true,
    ).toIso8601String();
  }

  return VersionInfo(
    full: version,
    major: major,
    minor: minor,
    patch: patch,
    buildEpoch: epoch,
    buildDate: buildDate,
  );
}
