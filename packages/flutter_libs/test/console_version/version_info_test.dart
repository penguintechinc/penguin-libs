import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('parseVersion', () {
    test('parses full version string', () {
      final v = parseVersion('v1.2.3.1234567890');
      expect(v.major, 1);
      expect(v.minor, 2);
      expect(v.patch, 3);
      expect(v.buildEpoch, '1234567890');
      expect(v.semver, '1.2.3');
    });

    test('parses version without v prefix', () {
      final v = parseVersion('2.0.1.999');
      expect(v.major, 2);
      expect(v.minor, 0);
      expect(v.patch, 1);
    });

    test('parses version without build epoch', () {
      final v = parseVersion('v3.1.0');
      expect(v.major, 3);
      expect(v.minor, 1);
      expect(v.patch, 0);
      expect(v.buildEpoch, isNull);
    });

    test('handles simple version', () {
      final v = parseVersion('1.0.0');
      expect(v.full, '1.0.0');
      expect(v.semver, '1.0.0');
    });
  });

  group('VersionInfo', () {
    test('buildDate returns DateTime for epoch', () {
      final v = VersionInfo(
        full: 'v1.0.0.1700000000',
        major: 1,
        minor: 0,
        patch: 0,
        buildEpoch: '1700000000',
      );
      expect(v.buildDate, isA<DateTime>());
    });

    test('buildDate returns null for missing epoch', () {
      final v = VersionInfo(
        full: 'v1.0.0',
        major: 1,
        minor: 0,
        patch: 0,
      );
      expect(v.buildDate, isNull);
    });
  });
}
