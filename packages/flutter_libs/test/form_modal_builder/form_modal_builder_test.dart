import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('FormModalBuilder', () {
    testWidgets('renders title and fields', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: FormModalBuilder(
            title: 'Create Item',
            fields: const [
              FormFieldConfig(
                name: 'name',
                label: 'Name',
                type: FormFieldType.text,
                required: true,
              ),
            ],
            onSubmit: (values) async {},
          ),
        ),
      );

      expect(find.text('Create Item'), findsOneWidget);
      expect(find.text('Name'), findsOneWidget);
    });

    testWidgets('shows a validation error for a required empty field on submit',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: FormModalBuilder(
            title: 'Create Item',
            fields: const [
              FormFieldConfig(
                name: 'name',
                label: 'Name',
                type: FormFieldType.text,
                required: true,
              ),
            ],
            onSubmit: (values) async {},
          ),
        ),
      );

      await tester.tap(find.text('Submit'));
      await tester.pumpAndSettle();

      expect(find.text('Name is required'), findsOneWidget);
    });

    testWidgets('cancel invokes onCancel', (tester) async {
      var cancelled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: FormModalBuilder(
            title: 'Create Item',
            fields: const [
              FormFieldConfig(
                name: 'name',
                label: 'Name',
                type: FormFieldType.text,
              ),
            ],
            onSubmit: (values) async {},
            onCancel: () => cancelled = true,
          ),
        ),
      );

      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(cancelled, isTrue);
    });

    testWidgets(
        'submits values and shows a generic error (not the raw exception) on failure',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: FormModalBuilder(
            title: 'Create Item',
            fields: const [
              FormFieldConfig(
                name: 'name',
                label: 'Name',
                type: FormFieldType.text,
              ),
            ],
            onSubmit: (values) async {
              throw Exception('token=super-secret-leaked-detail');
            },
          ),
        ),
      );

      await tester.tap(find.text('Submit'));
      await tester.pumpAndSettle();

      expect(
          find.text('Something went wrong. Please try again.'), findsOneWidget);
      expect(find.textContaining('super-secret-leaked-detail'), findsNothing);
    });

    testWidgets('successful submit passes entered values', (tester) async {
      Map<String, dynamic>? submitted;

      await tester.pumpWidget(
        MaterialApp(
          home: FormModalBuilder(
            title: 'Create Item',
            fields: const [
              FormFieldConfig(
                name: 'name',
                label: 'Name',
                type: FormFieldType.text,
              ),
            ],
            onSubmit: (values) async {
              submitted = values;
            },
          ),
        ),
      );

      await tester.enterText(find.byType(TextFormField), 'Widget');
      await tester.tap(find.text('Submit'));
      await tester.pumpAndSettle();

      expect(submitted?['name'], 'Widget');
    });
  });
}
