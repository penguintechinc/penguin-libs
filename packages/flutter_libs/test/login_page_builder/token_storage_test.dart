import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';
import 'package:mocktail/mocktail.dart';

class MockFlutterSecureStorage extends Mock implements FlutterSecureStorage {}

void main() {
  group('TokenStorage', () {
    late MockFlutterSecureStorage mockStorage;
    late TokenStorage tokenStorage;

    setUpAll(() {
      registerFallbackValue('');
    });

    setUp(() {
      mockStorage = MockFlutterSecureStorage();
      tokenStorage = TokenStorage(storage: mockStorage);
      when(() => mockStorage.write(
            key: any(named: 'key'),
            value: any(named: 'value'),
          )).thenAnswer((_) async {});
      when(() => mockStorage.delete(key: any(named: 'key')))
          .thenAnswer((_) async {});
    });

    test('saveTokens writes the access token', () async {
      await tokenStorage.saveTokens(accessToken: 'access-123');
      verify(() => mockStorage.write(
            key: 'flutter_libs.auth.access_token',
            value: 'access-123',
          )).called(1);
      verifyNever(() => mockStorage.write(
            key: 'flutter_libs.auth.refresh_token',
            value: any(named: 'value'),
          ));
    });

    test('saveTokens writes the refresh token when provided', () async {
      await tokenStorage.saveTokens(
        accessToken: 'access-123',
        refreshToken: 'refresh-456',
      );
      verify(() => mockStorage.write(
            key: 'flutter_libs.auth.access_token',
            value: 'access-123',
          )).called(1);
      verify(() => mockStorage.write(
            key: 'flutter_libs.auth.refresh_token',
            value: 'refresh-456',
          )).called(1);
    });

    test(
        'saveTokens deletes a previously stored refresh token when refreshToken is omitted',
        () async {
      // regression: a login response without `refreshToken` (e.g. an
      // access-token-only refresh) must not leave a stale refresh token
      // behind from a prior login.
      await tokenStorage.saveTokens(accessToken: 'access-123');
      verify(() => mockStorage.delete(key: 'flutter_libs.auth.refresh_token'))
          .called(1);
      verifyNever(() => mockStorage.write(
            key: 'flutter_libs.auth.refresh_token',
            value: any(named: 'value'),
          ));
    });

    test('clear deletes both tokens', () async {
      await tokenStorage.clear();
      verify(() => mockStorage.delete(key: 'flutter_libs.auth.access_token'))
          .called(1);
      verify(() => mockStorage.delete(key: 'flutter_libs.auth.refresh_token'))
          .called(1);
    });

    test('readAccessToken delegates to storage.read', () async {
      when(() => mockStorage.read(key: 'flutter_libs.auth.access_token'))
          .thenAnswer((_) async => 'stored-access');
      final result = await tokenStorage.readAccessToken();
      expect(result, 'stored-access');
    });
  });
}
