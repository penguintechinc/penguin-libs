import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('AltchaChallenge.fromJson', () {
    test('parses fields, defaulting algorithm and maxnumber', () {
      final challenge = AltchaChallenge.fromJson({
        'challenge': 'abc',
        'salt': 'xyz',
        'signature': 'sig',
      });
      expect(challenge.algorithm, 'SHA-256');
      expect(challenge.challenge, 'abc');
      expect(challenge.salt, 'xyz');
      expect(challenge.signature, 'sig');
      expect(challenge.maxNumber, 1000000);
    });

    test('honors an explicit algorithm and maxnumber', () {
      final challenge = AltchaChallenge.fromJson({
        'algorithm': 'SHA-512',
        'challenge': 'abc',
        'salt': 'xyz',
        'signature': 'sig',
        'maxnumber': 500,
      });
      expect(challenge.algorithm, 'SHA-512');
      expect(challenge.maxNumber, 500);
    });

    test('throws FormatException when challenge is missing', () {
      expect(
        () => AltchaChallenge.fromJson({'salt': 'xyz', 'signature': 'sig'}),
        throwsA(isA<FormatException>()),
      );
    });

    test('throws FormatException when salt is missing', () {
      expect(
        () => AltchaChallenge.fromJson({
          'challenge': 'abc',
          'signature': 'sig',
        }),
        throwsA(isA<FormatException>()),
      );
    });
  });

  group('solveAltchaSync', () {
    test('finds the correct number for a locally generated SHA-256 challenge',
        () {
      const salt = 'test-salt';
      const secretNumber = 42;
      final challengeHex =
          sha256.convert(utf8.encode('$salt$secretNumber')).toString();

      final found = solveAltchaSync({
        'algorithm': 'SHA-256',
        'challenge': challengeHex,
        'salt': salt,
        'maxnumber': 1000,
      });

      expect(found, secretNumber);
    });

    test('matches case-insensitively against an uppercase challenge hex', () {
      const salt = 'salt';
      const secretNumber = 7;
      final challengeHex = sha256
          .convert(utf8.encode('$salt$secretNumber'))
          .toString()
          .toUpperCase();

      final found = solveAltchaSync({
        'algorithm': 'sha-256',
        'challenge': challengeHex,
        'salt': salt,
        'maxnumber': 100,
      });

      expect(found, secretNumber);
    });

    test('supports the SHA-512 algorithm', () {
      const salt = 'salt-512';
      const secretNumber = 3;
      final challengeHex =
          sha512.convert(utf8.encode('$salt$secretNumber')).toString();

      final found = solveAltchaSync({
        'algorithm': 'SHA-512',
        'challenge': challengeHex,
        'salt': salt,
        'maxnumber': 10,
      });

      expect(found, secretNumber);
    });

    test(
        'throws StateError when no solution exists within maxnumber (fail closed)',
        () {
      expect(
        () => solveAltchaSync({
          'algorithm': 'SHA-256',
          'challenge':
              '0000000000000000000000000000000000000000000000000000000000000000',
          'salt': 'salt',
          'maxnumber': 10,
        }),
        throwsA(isA<StateError>()),
      );
    });

    test('throws UnsupportedError for an unknown algorithm (fail closed)', () {
      expect(
        () => solveAltchaSync({
          'algorithm': 'MD5',
          'challenge': 'x',
          'salt': 'salt',
          'maxnumber': 10,
        }),
        throwsA(isA<UnsupportedError>()),
      );
    });
  });

  group('buildAltchaPayload', () {
    test('encodes a valid base64 JSON payload', () {
      const challenge = AltchaChallenge(
        algorithm: 'SHA-256',
        challenge: 'abc',
        salt: 'xyz',
        signature: 'sig',
        maxNumber: 100,
      );
      final payload = buildAltchaPayload(challenge, 7);
      final decoded = json.decode(utf8.decode(base64.decode(payload)))
          as Map<String, dynamic>;
      expect(decoded['number'], 7);
      expect(decoded['challenge'], 'abc');
      expect(decoded['salt'], 'xyz');
      expect(decoded['signature'], 'sig');
      expect(decoded['algorithm'], 'SHA-256');
    });
  });
}
