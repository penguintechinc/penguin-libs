import 'package:flutter/foundation.dart';

/// State controller for [FormBuilder], replacing the React useFormBuilder hook.
///
/// Manages form values, errors, touched state, and validation.
class FormBuilderController extends ChangeNotifier {
  FormBuilderController({
    Map<String, dynamic>? initialValues,
    this.validateOnChange = false,
    this.validateOnBlur = true,
    this.onValidate,
  }) : _values = Map<String, dynamic>.from(initialValues ?? {});

  final bool validateOnChange;
  final bool validateOnBlur;
  final Map<String, String? Function(dynamic value)>? onValidate;

  Map<String, dynamic> _values;
  final Map<String, String> _errors = {};
  final Map<String, bool> _touched = {};
  bool _isSubmitting = false;

  /// Current form values.
  Map<String, dynamic> get values => Map.unmodifiable(_values);

  /// Current validation errors keyed by field name.
  Map<String, String> get errors => Map.unmodifiable(_errors);

  /// Fields that have been interacted with.
  Map<String, bool> get touched => Map.unmodifiable(_touched);

  /// Whether the form is currently submitting.
  bool get isSubmitting => _isSubmitting;

  /// Whether any values differ from the initial values.
  bool get isDirty => _values.isNotEmpty;

  /// Whether the form has no validation errors.
  bool get isValid => _errors.isEmpty;

  /// Update a field value.
  void setValue(String name, dynamic value) {
    _values[name] = value;
    if (validateOnChange) {
      _validateField(name);
    }
    notifyListeners();
  }

  /// Mark a field as touched (blurred).
  void setTouched(String name) {
    _touched[name] = true;
    if (validateOnBlur) {
      _validateField(name);
    }
    notifyListeners();
  }

  /// Set an error for a specific field.
  void setError(String name, String? error) {
    if (error == null) {
      _errors.remove(name);
    } else {
      _errors[name] = error;
    }
    notifyListeners();
  }

  /// Validate all fields. Returns true if valid.
  bool validateAll() {
    _errors.clear();
    if (onValidate != null) {
      for (final entry in onValidate!.entries) {
        final error = entry.value(_values[entry.key]);
        if (error != null) {
          _errors[entry.key] = error;
        }
      }
    }
    notifyListeners();
    return _errors.isEmpty;
  }

  /// Start the submit process.
  void setSubmitting(bool submitting) {
    _isSubmitting = submitting;
    notifyListeners();
  }

  /// Reset the form to initial state.
  void reset([Map<String, dynamic>? newValues]) {
    _values = Map<String, dynamic>.from(newValues ?? {});
    _errors.clear();
    _touched.clear();
    _isSubmitting = false;
    notifyListeners();
  }

  void _validateField(String name) {
    final validator = onValidate?[name];
    if (validator != null) {
      final error = validator(_values[name]);
      if (error != null) {
        _errors[name] = error;
      } else {
        _errors.remove(name);
      }
    }
  }
}
