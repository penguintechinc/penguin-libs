import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('MFAInput', () {
    testWidgets('renders the configured number of digit boxes', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAInput(length: 6, onCompleted: (_) {}),
          ),
        ),
      );

      expect(find.byType(TextField), findsNWidgets(6));
    });

    testWidgets(
        'auto-advances focus and calls onCompleted when all digits entered',
        (tester) async {
      String? completedCode;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAInput(
              length: 4,
              autoFocus: false,
              onCompleted: (code) => completedCode = code,
            ),
          ),
        ),
      );

      final fields = find.byType(TextField);
      for (var i = 0; i < 4; i++) {
        await tester.enterText(fields.at(i), '$i');
        await tester.pump();
      }

      expect(completedCode, '0123');
    });

    testWidgets('rejects a non-digit character typed into a box',
        (tester) async {
      // regression: L4 requires digit-only filtering on the *typed* path,
      // not just the paste path. FilteringTextInputFormatter.digitsOnly
      // applies to every EditableText value update (typed or pasted) before
      // onChanged ever sees it, so a non-digit keystroke must never reach
      // the controller or onChanged/onCompleted.
      String? changedCode;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAInput(
              length: 4,
              autoFocus: false,
              onChanged: (code) => changedCode = code,
              onCompleted: (_) {},
            ),
          ),
        ),
      );

      await tester.enterText(find.byType(TextField).first, 'a');
      await tester.pump();

      final firstField = tester.widget<TextField>(find.byType(TextField).first);
      expect(firstField.controller!.text, isEmpty);
      expect(changedCode, isNull);
    });

    testWidgets('pasting a full code fills every box', (tester) async {
      String? completedCode;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAInput(
              length: 6,
              autoFocus: false,
              onCompleted: (code) => completedCode = code,
            ),
          ),
        ),
      );

      // Simulate pasting "123456" into the first box.
      await tester.enterText(find.byType(TextField).first, '123456');
      await tester.pump();

      expect(completedCode, '123456');
    });

    testWidgets('pasting mixed alphanumeric content keeps only the digits',
        (tester) async {
      String? completedCode;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MFAInput(
              length: 4,
              autoFocus: false,
              onCompleted: (code) => completedCode = code,
            ),
          ),
        ),
      );

      // Simulate pasting "1a2b3c4d" — digits-only filtering (formatter and
      // _handlePaste's own defensive regex) must reduce this to "1234".
      await tester.enterText(find.byType(TextField).first, '1a2b3c4d');
      await tester.pump();

      expect(completedCode, '1234');
    });
  });
}
