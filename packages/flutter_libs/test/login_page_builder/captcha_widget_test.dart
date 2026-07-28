import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void _noopOnVerified(String _) {}

void main() {
  group('CaptchaWidget', () {
    test('defaults to the real isolate-based solver', () {
      const widget = CaptchaWidget(
        challengeUrl: 'https://example.com/altcha',
        onVerified: _noopOnVerified,
      );
      expect(widget.fetchChallenge, fetchAltchaChallenge);
      expect(widget.solveChallenge, solveAltchaChallenge);
    });

    testWidgets('fails closed when the challenge fetch errors', (tester) async {
      var verifiedCalled = false;
      String? capturedError;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CaptchaWidget(
              challengeUrl: 'https://example.com/altcha',
              fetchChallenge: (_) async {
                throw Exception('network down');
              },
              onVerified: (_) => verifiedCalled = true,
              onError: (e) => capturedError = e,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(GestureDetector));
      await tester.pumpAndSettle();

      expect(verifiedCalled, isFalse);
      expect(capturedError, isNotNull);
      expect(
          find.text('Verification failed. Please try again.'), findsOneWidget);
    });

    testWidgets(
        'fails closed when the challenge cannot be solved within maxnumber',
        (tester) async {
      var verifiedCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CaptchaWidget(
              challengeUrl: 'https://example.com/altcha',
              // A challenge hash that matches no number in [0, maxNumber]
              // — the solver must exhaust its search and fail closed
              // rather than emit a token.
              fetchChallenge: (_) async => const AltchaChallenge(
                algorithm: 'SHA-256',
                challenge: 'unsolvable-hash-for-this-salt',
                salt: 'fixed-salt',
                signature: 'sig',
                maxNumber: 5,
              ),
              // Solve synchronously (no compute()/isolate) — flutter_test's
              // fake-clock pump loop can't reliably wait on a real
              // background isolate.
              solveChallenge: (c) async => solveAltchaSync({
                'algorithm': c.algorithm,
                'challenge': c.challenge,
                'salt': c.salt,
                'maxnumber': c.maxNumber,
              }),
              onVerified: (_) => verifiedCalled = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(GestureDetector));
      await tester.pumpAndSettle();

      expect(verifiedCalled, isFalse);
      expect(
          find.text('Verification failed. Please try again.'), findsOneWidget);
    });

    testWidgets('calls onVerified with a solved payload on success',
        (tester) async {
      String? verifiedToken;
      const salt = 'fixed-salt';
      const secretNumber = 3;
      final challengeHex =
          sha256.convert(utf8.encode('$salt$secretNumber')).toString();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CaptchaWidget(
              challengeUrl: 'https://example.com/altcha',
              fetchChallenge: (_) async => AltchaChallenge(
                algorithm: 'SHA-256',
                challenge: challengeHex,
                salt: salt,
                signature: 'sig',
                maxNumber: 10,
              ),
              // Solve synchronously (no compute()/isolate) — flutter_test's
              // fake-clock pump loop can't reliably wait on a real
              // background isolate.
              solveChallenge: (c) async => solveAltchaSync({
                'algorithm': c.algorithm,
                'challenge': c.challenge,
                'salt': c.salt,
                'maxnumber': c.maxNumber,
              }),
              onVerified: (token) => verifiedToken = token,
            ),
          ),
        ),
      );

      await tester.tap(find.byType(GestureDetector));
      await tester.pumpAndSettle();

      expect(verifiedToken, isNotNull);
      final decoded = json.decode(utf8.decode(base64.decode(verifiedToken!)))
          as Map<String, dynamic>;
      expect(decoded['number'], secretNumber);
      expect(decoded['salt'], salt);
      expect(find.text('Verified'), findsOneWidget);
    });
  });
}
