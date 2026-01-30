import 'package:flutter/material.dart';

/// Field types for [FormBuilder].
enum FieldType {
  text,
  email,
  password,
  number,
  textarea,
  select,
  checkbox,
  radio,
  date,
  time,
  datetimeLocal,
  tel,
  url,
}

/// Option for select/radio fields.
class SelectOption {
  const SelectOption({
    required this.value,
    required this.label,
  });

  final String value;
  final String label;
}

/// Configuration for a single field in [FormBuilder].
class FieldConfig {
  const FieldConfig({
    required this.name,
    required this.label,
    required this.type,
    this.placeholder,
    this.required = false,
    this.disabled = false,
    this.autoFocus = false,
    this.min,
    this.max,
    this.minLength,
    this.maxLength,
    this.pattern,
    this.step,
    this.rows,
    this.options,
    this.helperText,
    this.validate,
    this.onChange,
  });

  final String name;
  final String label;
  final FieldType type;
  final String? placeholder;
  final bool required;
  final bool disabled;
  final bool autoFocus;
  final num? min;
  final num? max;
  final int? minLength;
  final int? maxLength;
  final String? pattern;
  final num? step;
  final int? rows;
  final List<SelectOption>? options;
  final String? helperText;
  final String? Function(dynamic value)? validate;
  final void Function(dynamic value)? onChange;
}

/// Configuration for the entire [FormBuilder].
class FormConfig {
  const FormConfig({
    required this.fields,
    this.title,
    this.submitLabel = 'Submit',
    this.cancelLabel = 'Cancel',
    this.validateOnChange = false,
    this.validateOnBlur = true,
  });

  final List<FieldConfig> fields;
  final String? title;
  final String submitLabel;
  final String cancelLabel;
  final bool validateOnChange;
  final bool validateOnBlur;
}
