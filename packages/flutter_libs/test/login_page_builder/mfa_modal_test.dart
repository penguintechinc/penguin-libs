import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('MFAModal', () {
    testWidgets('renders title, code input, and disabled Verify button',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAModal(onVerify: (_, __) {}),
          ),
        ),
      );

      expect(find.text('Two-Factor Authentication'), findsOneWidget);
      expect(find.text('Verify'), findsOneWidget);

      final verifyButton = tester.widget<ElevatedButton>(
        find.widgetWithText(ElevatedButton, 'Verify'),
      );
      expect(verifyButton.onPressed, isNull);
    });

    testWidgets('Verify becomes enabled once the code is fully entered',
        (tester) async {
      String? verifiedCode;
      bool? verifiedRememberDevice;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAModal(
              codeLength: 4,
              onVerify: (code, rememberDevice) {
                verifiedCode = code;
                verifiedRememberDevice = rememberDevice;
              },
            ),
          ),
        ),
      );

      final fields = find.byType(TextField);
      for (var i = 0; i < 4; i++) {
        await tester.enterText(fields.at(i), '$i');
        await tester.pump();
      }

      final verifyButton = tester.widget<ElevatedButton>(
        find.widgetWithText(ElevatedButton, 'Verify'),
      );
      expect(verifyButton.onPressed, isNotNull);

      await tester.tap(find.widgetWithText(ElevatedButton, 'Verify'));
      await tester.pump();

      expect(verifiedCode, '0123');
      expect(verifiedRememberDevice, isFalse);
    });

    testWidgets('Cancel invokes onCancel', (tester) async {
      var cancelled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAModal(
              onVerify: (_, __) {},
              onCancel: () => cancelled = true,
            ),
          ),
        ),
      );

      await tester.tap(find.widgetWithText(OutlinedButton, 'Cancel'));
      await tester.pump();

      expect(cancelled, isTrue);
    });
  });
}
