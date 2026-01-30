import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import '../theme/elder_colors.dart';
import 'form_field_config.dart';
import 'form_color_config.dart';
import 'password_generator.dart';

/// Renders a single form field based on [FormFieldConfig].
///
/// Supports all 18 [FormFieldType] values with Elder theme styling.
class FormFieldBuilder extends StatelessWidget {
  const FormFieldBuilder({
    super.key,
    required this.field,
    required this.value,
    required this.onChanged,
    this.errorText,
    this.colorConfig = FormColorConfig.elder,
  });

  final FormFieldConfig field;
  final dynamic value;
  final ValueChanged<dynamic> onChanged;
  final String? errorText;
  final FormColorConfig colorConfig;

  @override
  Widget build(BuildContext context) {
    if (field.hidden) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Label row
          if (field.type != FormFieldType.checkbox)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                children: [
                  Text(
                    field.label,
                    style: TextStyle(
                      color: colorConfig.labelText,
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  if (field.required)
                    Text(
                      ' *',
                      style: TextStyle(color: colorConfig.errorText),
                    ),
                ],
              ),
            ),

          // Description
          if (field.description != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                field.description!,
                style: TextStyle(
                  color: colorConfig.descriptionText,
                  fontSize: 12,
                ),
              ),
            ),

          // Field widget
          _buildField(context),

          // Help text
          if (field.helpText != null && errorText == null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                field.helpText!,
                style: TextStyle(
                  color: colorConfig.descriptionText,
                  fontSize: 12,
                ),
              ),
            ),

          // Error text
          if (errorText != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                errorText!,
                style: TextStyle(
                  color: colorConfig.errorText,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildField(BuildContext context) {
    switch (field.type) {
      case FormFieldType.text:
      case FormFieldType.email:
      case FormFieldType.tel:
      case FormFieldType.url:
      case FormFieldType.number:
        return _buildTextField();

      case FormFieldType.password:
        return _buildPasswordField();

      case FormFieldType.passwordGenerate:
        return _buildPasswordGenerateField();

      case FormFieldType.textarea:
      case FormFieldType.multiline:
        return _buildTextArea();

      case FormFieldType.select:
        return _buildDropdown();

      case FormFieldType.checkbox:
        return _buildCheckbox();

      case FormFieldType.checkboxMulti:
        return _buildCheckboxMulti();

      case FormFieldType.radio:
        return _buildRadioGroup();

      case FormFieldType.date:
        return _buildDateField(context);

      case FormFieldType.time:
        return _buildTimeField(context);

      case FormFieldType.datetimeLocal:
        return _buildDateTimeField(context);

      case FormFieldType.file:
        return _buildFileField(multiple: false);

      case FormFieldType.fileMultiple:
        return _buildFileField(multiple: true);
    }
  }

  InputDecoration get _inputDecoration {
    return InputDecoration(
      hintText: field.placeholder,
      hintStyle: TextStyle(color: colorConfig.fieldPlaceholder),
      filled: true,
      fillColor: colorConfig.fieldBackground,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colorConfig.fieldBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colorConfig.fieldBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(
          color: colorConfig.focusBorder,
          width: 2,
        ),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colorConfig.errorText),
      ),
      disabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colorConfig.disabledBackground),
      ),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: 12,
        vertical: 12,
      ),
    );
  }

  TextInputType get _keyboardType {
    switch (field.type) {
      case FormFieldType.email:
        return TextInputType.emailAddress;
      case FormFieldType.number:
        return TextInputType.number;
      case FormFieldType.tel:
        return TextInputType.phone;
      case FormFieldType.url:
        return TextInputType.url;
      default:
        return TextInputType.text;
    }
  }

  Widget _buildTextField() {
    return TextFormField(
      initialValue: value?.toString() ?? field.defaultValue?.toString(),
      enabled: !field.disabled,
      keyboardType: _keyboardType,
      style: TextStyle(color: colorConfig.fieldText),
      decoration: _inputDecoration,
      inputFormatters: field.type == FormFieldType.number
          ? [FilteringTextInputFormatter.allow(RegExp(r'[\d.\-]'))]
          : null,
      onChanged: (v) => onChanged(v),
    );
  }

  Widget _buildPasswordField() {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !field.disabled,
      obscureText: true,
      style: TextStyle(color: colorConfig.fieldText),
      decoration: _inputDecoration,
      onChanged: (v) => onChanged(v),
    );
  }

  Widget _buildPasswordGenerateField() {
    return Row(
      children: [
        Expanded(
          child: TextFormField(
            initialValue: value?.toString(),
            enabled: !field.disabled,
            obscureText: true,
            style: TextStyle(color: colorConfig.fieldText),
            decoration: _inputDecoration,
            onChanged: (v) => onChanged(v),
          ),
        ),
        const SizedBox(width: 8),
        IconButton(
          icon: const Icon(Icons.refresh),
          color: colorConfig.primaryButton,
          tooltip: 'Generate password',
          onPressed: field.disabled
              ? null
              : () {
                  final pw = generatePassword();
                  onChanged(pw);
                  field.onPasswordGenerated?.call(pw);
                },
        ),
      ],
    );
  }

  Widget _buildTextArea() {
    return TextFormField(
      initialValue: value?.toString() ?? field.defaultValue?.toString(),
      enabled: !field.disabled,
      maxLines: field.rows ?? 4,
      style: TextStyle(color: colorConfig.fieldText),
      decoration: _inputDecoration,
      onChanged: (v) {
        if (field.type == FormFieldType.multiline) {
          onChanged(v.split('\n').where((s) => s.isNotEmpty).toList());
        } else {
          onChanged(v);
        }
      },
    );
  }

  Widget _buildDropdown() {
    return DropdownButtonFormField<dynamic>(
      value: value ?? field.defaultValue,
      decoration: _inputDecoration,
      dropdownColor: ElderColors.slate800,
      style: TextStyle(color: colorConfig.fieldText),
      items: field.options?.map((opt) {
        return DropdownMenuItem<dynamic>(
          value: opt.value,
          child: Text(opt.label),
        );
      }).toList(),
      onChanged: field.disabled ? null : (v) => onChanged(v),
    );
  }

  Widget _buildCheckbox() {
    return Row(
      children: [
        Checkbox(
          value: value == true || value == 'true',
          activeColor: colorConfig.checkboxActive,
          checkColor: colorConfig.buttonText,
          onChanged: field.disabled
              ? null
              : (v) => onChanged(v ?? false),
        ),
        Expanded(
          child: Text(
            field.label,
            style: TextStyle(
              color: colorConfig.labelText,
              fontSize: 14,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildCheckboxMulti() {
    final selected = (value is List) ? List<dynamic>.from(value) : <dynamic>[];

    return Column(
      children: field.options?.map((opt) {
        final isChecked = selected.contains(opt.value);
        return CheckboxListTile(
          title: Text(
            opt.label,
            style: TextStyle(
              color: colorConfig.labelText,
              fontSize: 14,
            ),
          ),
          value: isChecked,
          activeColor: colorConfig.checkboxActive,
          checkColor: colorConfig.buttonText,
          contentPadding: EdgeInsets.zero,
          dense: true,
          controlAffinity: ListTileControlAffinity.leading,
          onChanged: field.disabled
              ? null
              : (checked) {
                  final newSelected = List<dynamic>.from(selected);
                  if (checked == true) {
                    newSelected.add(opt.value);
                  } else {
                    newSelected.remove(opt.value);
                  }
                  onChanged(newSelected);
                },
        );
      }).toList() ?? [],
    );
  }

  Widget _buildRadioGroup() {
    return Column(
      children: field.options?.map((opt) {
        return RadioListTile<dynamic>(
          title: Text(
            opt.label,
            style: TextStyle(
              color: colorConfig.labelText,
              fontSize: 14,
            ),
          ),
          value: opt.value,
          groupValue: value,
          activeColor: colorConfig.radioActive,
          contentPadding: EdgeInsets.zero,
          dense: true,
          onChanged: field.disabled
              ? null
              : (v) => onChanged(v),
        );
      }).toList() ?? [],
    );
  }

  Widget _buildDateField(BuildContext context) {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !field.disabled,
      style: TextStyle(color: colorConfig.fieldText),
      decoration: _inputDecoration.copyWith(
        suffixIcon: IconButton(
          icon: const Icon(Icons.calendar_today, size: 18),
          color: colorConfig.descriptionText,
          onPressed: field.disabled
              ? null
              : () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: DateTime.now(),
                    firstDate: DateTime(1900),
                    lastDate: DateTime(2100),
                  );
                  if (date != null) {
                    onChanged(date.toIso8601String().split('T').first);
                  }
                },
        ),
      ),
      onChanged: (v) => onChanged(v),
    );
  }

  Widget _buildTimeField(BuildContext context) {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !field.disabled,
      style: TextStyle(color: colorConfig.fieldText),
      decoration: _inputDecoration.copyWith(
        suffixIcon: IconButton(
          icon: const Icon(Icons.access_time, size: 18),
          color: colorConfig.descriptionText,
          onPressed: field.disabled
              ? null
              : () async {
                  final time = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay.now(),
                  );
                  if (time != null) {
                    final h = time.hour.toString().padLeft(2, '0');
                    final m = time.minute.toString().padLeft(2, '0');
                    onChanged('$h:$m');
                  }
                },
        ),
      ),
      onChanged: (v) => onChanged(v),
    );
  }

  Widget _buildDateTimeField(BuildContext context) {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !field.disabled,
      style: TextStyle(color: colorConfig.fieldText),
      decoration: _inputDecoration.copyWith(
        suffixIcon: IconButton(
          icon: const Icon(Icons.event, size: 18),
          color: colorConfig.descriptionText,
          onPressed: field.disabled
              ? null
              : () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: DateTime.now(),
                    firstDate: DateTime(1900),
                    lastDate: DateTime(2100),
                  );
                  if (date == null) return;
                  if (!context.mounted) return;
                  final time = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay.now(),
                  );
                  if (time != null) {
                    final dt = DateTime(
                      date.year, date.month, date.day,
                      time.hour, time.minute,
                    );
                    onChanged(dt.toIso8601String());
                  }
                },
        ),
      ),
      onChanged: (v) => onChanged(v),
    );
  }

  Widget _buildFileField({required bool multiple}) {
    final files = value is List<String> ? value as List<String> : <String>[];
    final singleFile = value is String ? value as String : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        OutlinedButton.icon(
          onPressed: field.disabled
              ? null
              : () async {
                  final result = await FilePicker.platform.pickFiles(
                    allowMultiple: multiple,
                    type: field.accept != null
                        ? FileType.custom
                        : FileType.any,
                    allowedExtensions: field.accept
                        ?.split(',')
                        .map((e) => e.trim().replaceAll('.', ''))
                        .toList(),
                  );
                  if (result != null) {
                    if (multiple) {
                      onChanged(
                        result.files.map((f) => f.name).toList(),
                      );
                    } else {
                      onChanged(result.files.first.name);
                    }
                  }
                },
          icon: const Icon(Icons.upload_file, size: 18),
          label: Text(multiple ? 'Choose Files' : 'Choose File'),
          style: OutlinedButton.styleFrom(
            foregroundColor: colorConfig.secondaryButtonText,
            side: BorderSide(color: colorConfig.secondaryButtonBorder),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        ),
        if (singleFile != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              singleFile,
              style: TextStyle(
                color: colorConfig.descriptionText,
                fontSize: 12,
              ),
            ),
          ),
        if (files.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: files
                  .map((f) => Text(
                        f,
                        style: TextStyle(
                          color: colorConfig.descriptionText,
                          fontSize: 12,
                        ),
                      ))
                  .toList(),
            ),
          ),
      ],
    );
  }
}
