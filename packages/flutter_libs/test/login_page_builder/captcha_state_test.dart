import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('CaptchaNotifier', () {
    late CaptchaNotifier notifier;

    setUp(() {
      notifier = CaptchaNotifier(threshold: 3);
    });

    tearDown(() {
      notifier.dispose();
    });

    test('starts with zero failed attempts', () {
      expect(notifier.failedAttempts, 0);
    });

    test('does not show captcha initially', () {
      expect(notifier.showCaptcha, isFalse);
    });

    test('shows captcha after threshold', () {
      notifier.recordFailure();
      notifier.recordFailure();
      notifier.recordFailure();
      expect(notifier.showCaptcha, isTrue);
    });

    test('does not show before threshold', () {
      notifier.recordFailure();
      notifier.recordFailure();
      expect(notifier.showCaptcha, isFalse);
    });

    test('setCaptchaToken marks as verified', () {
      notifier.setCaptchaToken('token123');
      expect(notifier.isVerified, isTrue);
      expect(notifier.captchaToken, 'token123');
    });

    test('reset clears state', () {
      notifier.recordFailure();
      notifier.recordFailure();
      notifier.recordFailure();
      notifier.setCaptchaToken('token');
      notifier.reset();
      expect(notifier.failedAttempts, 0);
      expect(notifier.showCaptcha, isFalse);
      expect(notifier.isVerified, isFalse);
      expect(notifier.captchaToken, isNull);
    });
  });
}
