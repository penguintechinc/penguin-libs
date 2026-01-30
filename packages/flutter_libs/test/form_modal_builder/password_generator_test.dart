import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('generatePassword', () {
    test('generates password of default length', () {
      final pw = generatePassword();
      expect(pw.length, 14);
    });

    test('generates password of custom length', () {
      final pw = generatePassword(length: 20);
      expect(pw.length, 20);
    });

    test('generates different passwords', () {
      final pw1 = generatePassword();
      final pw2 = generatePassword();
      expect(pw1, isNot(equals(pw2)));
    });

    test('contains only valid characters', () {
      final pw = generatePassword(length: 100);
      expect(pw, matches(RegExp(r'^[A-Za-z0-9]+$')));
    });
  });
}
