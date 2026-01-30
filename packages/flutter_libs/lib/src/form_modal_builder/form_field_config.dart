import 'package:flutter/material.dart';

/// Field types supported by [FormModalBuilder].
enum FormFieldType {
  text,
  email,
  password,
  passwordGenerate,
  number,
  tel,
  url,
  textarea,
  multiline,
  select,
  checkbox,
  checkboxMulti,
  radio,
  date,
  time,
  datetimeLocal,
  file,
  fileMultiple,
}

/// Option for select, radio, and checkbox_multi fields.
class FormFieldOption {
  const FormFieldOption({
    required this.value,
    required this.label,
  });

  final dynamic value;
  final String label;
}

/// Configuration for a single form field in [FormModalBuilder].
class FormFieldConfig {
  const FormFieldConfig({
    required this.name,
    required this.type,
    required this.label,
    this.description,
    this.helpText,
    this.defaultValue,
    this.placeholder,
    this.required = false,
    this.disabled = false,
    this.hidden = false,
    this.options,
    this.min,
    this.max,
    this.pattern,
    this.accept,
    this.rows,
    this.triggerField,
    this.showWhen,
    this.onPasswordGenerated,
    this.maxFileSize,
    this.maxFiles,
    this.tab,
  });

  final String name;
  final FormFieldType type;
  final String label;
  final String? description;
  final String? helpText;
  final dynamic defaultValue;
  final String? placeholder;
  final bool required;
  final bool disabled;
  final bool hidden;
  final List<FormFieldOption>? options;
  final num? min;
  final num? max;
  final String? pattern;
  final String? accept;
  final int? rows;
  final String? triggerField;
  final bool Function(Map<String, dynamic> values)? showWhen;
  final void Function(String password)? onPasswordGenerated;
  final int? maxFileSize;
  final int? maxFiles;
  final String? tab;
}
