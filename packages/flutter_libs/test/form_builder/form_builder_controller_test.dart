import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  group('FormBuilderController', () {
    late FormBuilderController controller;

    setUp(() {
      controller = FormBuilderController();
    });

    tearDown(() {
      controller.dispose();
    });

    test('starts with empty values', () {
      expect(controller.values, isEmpty);
    });

    test('starts not dirty', () {
      expect(controller.isDirty, isFalse);
    });

    test('starts not submitting', () {
      expect(controller.isSubmitting, isFalse);
    });

    test('setValue updates values and marks dirty', () {
      controller.setValue('name', 'John');
      expect(controller.values['name'], 'John');
      expect(controller.isDirty, isTrue);
    });

    test('setError sets field error', () {
      controller.setError('email', 'Required');
      expect(controller.errors['email'], 'Required');
    });

    test('isValid returns true when no errors', () {
      expect(controller.isValid, isTrue);
    });

    test('isValid returns false with errors', () {
      controller.setError('field', 'Error');
      expect(controller.isValid, isFalse);
    });

    test('setTouched marks field as touched', () {
      controller.setTouched('name');
      expect(controller.touched.contains('name'), isTrue);
    });

    test('setSubmitting toggles submitting state', () {
      controller.setSubmitting(true);
      expect(controller.isSubmitting, isTrue);
      controller.setSubmitting(false);
      expect(controller.isSubmitting, isFalse);
    });

    test('reset clears all state', () {
      controller.setValue('name', 'John');
      controller.setError('email', 'Required');
      controller.setTouched('name');
      controller.reset();
      expect(controller.values, isEmpty);
      expect(controller.errors, isEmpty);
      expect(controller.touched, isEmpty);
      expect(controller.isDirty, isFalse);
    });
  });
}
