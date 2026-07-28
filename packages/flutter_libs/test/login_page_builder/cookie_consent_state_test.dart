import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('CookieConsentNotifier', () {
    test('canInteract is true when disabled regardless of stored consent',
        () async {
      SharedPreferences.setMockInitialValues({});
      final notifier = CookieConsentNotifier(enabled: false);
      await notifier.load();
      expect(notifier.canInteract, isTrue);
      notifier.dispose();
    });

    test('loads a previously accepted consent from the current JSON format',
        () async {
      SharedPreferences.setMockInitialValues({
        'gdpr_consent': '{"accepted":true,"essential":true,"functional":true,'
            '"analytics":false,"marketing":false,"timestamp":1700000000000}',
      });
      final notifier = CookieConsentNotifier();
      await notifier.load();
      expect(notifier.canInteract, isTrue);
      expect(notifier.consent.functional, isTrue);
      expect(notifier.consent.analytics, isFalse);
      notifier.dispose();
    });

    test(
        'migrates a legacy comma/colon-encoded consent instead of resetting it',
        () async {
      // Pre-JSON-migration format written by an older version of this
      // package. Must still be honored — a user who previously accepted
      // must not silently be shown the consent banner again.
      SharedPreferences.setMockInitialValues({
        'gdpr_consent':
            'accepted:true,essential:true,functional:true,analytics:false,'
                'marketing:false,timestamp:1600000000000',
      });
      final notifier = CookieConsentNotifier();
      await notifier.load();
      expect(notifier.canInteract, isTrue);
      expect(notifier.consent.accepted, isTrue);
      expect(notifier.consent.functional, isTrue);
      expect(notifier.consent.timestamp, 1600000000000);
      notifier.dispose();
    });

    test('falls back to default (not accepted) for genuinely corrupt data',
        () async {
      SharedPreferences.setMockInitialValues(
          {'gdpr_consent': '!!! not parseable ???'});
      final notifier = CookieConsentNotifier();
      await notifier.load();
      expect(notifier.canInteract, isFalse);
      notifier.dispose();
    });

    test('acceptAll persists in the JSON format, re-loadable', () async {
      SharedPreferences.setMockInitialValues({});
      final notifier = CookieConsentNotifier();
      await notifier.load();
      await notifier.acceptAll();
      expect(notifier.canInteract, isTrue);

      final reloaded = CookieConsentNotifier();
      await reloaded.load();
      expect(reloaded.canInteract, isTrue);
      expect(reloaded.consent.analytics, isTrue);
      notifier.dispose();
      reloaded.dispose();
    });
  });
}
