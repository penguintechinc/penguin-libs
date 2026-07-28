import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mocktail/mocktail.dart';

class _MockFlutterSecureStorage extends Mock implements FlutterSecureStorage {}

Widget _wrap(Widget child) => MaterialApp(home: child);

void main() {
  setUpAll(() {
    registerFallbackValue('');
  });

  group('LoginPageBuilder', () {
    testWidgets('renders email, password fields and a sign-in button',
        (tester) async {
      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
          ),
        ),
      );

      expect(find.text('Test App'), findsOneWidget);
      expect(find.text('Email'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
      expect(find.text('Sign In'), findsOneWidget);
    });

    testWidgets('shows validation errors when submitting empty fields',
        (tester) async {
      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
          ),
        ),
      );

      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Email is required'), findsOneWidget);
      expect(find.text('Password is required'), findsOneWidget);
    });

    testWidgets('shows an error message on a failed (401) login',
        (tester) async {
      final client = MockClient((request) async {
        return http.Response(
          json.encode({'success': false, 'error': 'Invalid credentials'}),
          401,
        );
      });

      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
            httpClient: client,
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextFormField).at(0), 'user@example.com');
      await tester.enterText(find.byType(TextFormField).at(1), 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Invalid credentials'), findsOneWidget);
    });

    testWidgets('shows the MFA modal when the server requests it',
        (tester) async {
      final client = MockClient((request) async {
        return http.Response(
          json.encode({'success': false, 'mfaRequired': true}),
          200,
        );
      });

      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
            mfaConfig: const MFAConfig(enabled: true),
            httpClient: client,
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextFormField).at(0), 'user@example.com');
      await tester.enterText(find.byType(TextFormField).at(1), 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Two-Factor Authentication'), findsOneWidget);
    });

    testWidgets(
        'shows a distinct error for a 500 server error without triggering CAPTCHA logic',
        (tester) async {
      final client = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
            captchaConfig: const CaptchaConfig(
              enabled: true,
              failedAttemptsThreshold: 1,
              challengeUrl: 'https://api.example.com/altcha',
            ),
            httpClient: client,
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextFormField).at(0), 'user@example.com');
      await tester.enterText(find.byType(TextFormField).at(1), 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(
          find.text('Server error. Please try again later.'), findsOneWidget);
      // A single 500 must not have tripped the CAPTCHA threshold of 1.
      expect(find.byType(CaptchaWidget), findsNothing);
    });

    testWidgets('calls onLoginSuccess on a successful login', (tester) async {
      LoginResponse? successResponse;
      final client = MockClient((request) async {
        return http.Response(
          json.encode({
            'success': true,
            'token': 'access-token',
            'user': {'id': '1', 'email': 'user@example.com'},
          }),
          200,
        );
      });

      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
            httpClient: client,
            onLoginSuccess: (response) => successResponse = response,
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextFormField).at(0), 'user@example.com');
      await tester.enterText(find.byType(TextFormField).at(1), 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      expect(successResponse, isNotNull);
      expect(successResponse!.success, isTrue);
    });

    testWidgets('persists tokens via tokenStorage on a successful login',
        (tester) async {
      final mockStorage = _MockFlutterSecureStorage();
      when(() => mockStorage.write(
            key: any(named: 'key'),
            value: any(named: 'value'),
          )).thenAnswer((_) async {});
      when(() => mockStorage.delete(key: any(named: 'key')))
          .thenAnswer((_) async {});
      final tokenStorage = TokenStorage(storage: mockStorage);

      final client = MockClient((request) async {
        return http.Response(
          json.encode({
            'success': true,
            'token': 'access-token',
            'refreshToken': 'refresh-token',
            'user': {'id': '1', 'email': 'user@example.com'},
          }),
          200,
        );
      });

      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
            httpClient: client,
            tokenStorage: tokenStorage,
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextFormField).at(0), 'user@example.com');
      await tester.enterText(find.byType(TextFormField).at(1), 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      verify(() => mockStorage.write(
            key: 'flutter_libs.auth.access_token',
            value: 'access-token',
          )).called(1);
      verify(() => mockStorage.write(
            key: 'flutter_libs.auth.refresh_token',
            value: 'refresh-token',
          )).called(1);

      // This widget has no logout UI of its own — verify the documented
      // caller-driven logout path (tokenStorage.clear()) actually clears
      // what was just persisted.
      await tokenStorage.clear();
      verify(() => mockStorage.delete(key: 'flutter_libs.auth.access_token'))
          .called(1);
      verify(() => mockStorage.delete(key: 'flutter_libs.auth.refresh_token'))
          .called(1);
    });

    testWidgets('does not touch tokenStorage on a failed login',
        (tester) async {
      final mockStorage = _MockFlutterSecureStorage();
      when(() => mockStorage.write(
            key: any(named: 'key'),
            value: any(named: 'value'),
          )).thenAnswer((_) async {});
      final tokenStorage = TokenStorage(storage: mockStorage);

      final client = MockClient((request) async {
        return http.Response(
          json.encode({'success': false, 'error': 'Invalid credentials'}),
          401,
        );
      });

      await tester.pumpWidget(
        _wrap(
          LoginPageBuilder(
            apiConfig:
                LoginApiConfig(loginUrl: 'https://api.example.com/login'),
            branding: const BrandingConfig(appName: 'Test App'),
            httpClient: client,
            tokenStorage: tokenStorage,
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextFormField).at(0), 'user@example.com');
      await tester.enterText(find.byType(TextFormField).at(1), 'password123');
      await tester.tap(find.text('Sign In'));
      await tester.pumpAndSettle();

      verifyNever(() => mockStorage.write(
            key: any(named: 'key'),
            value: any(named: 'value'),
          ));
    });
  });
}
