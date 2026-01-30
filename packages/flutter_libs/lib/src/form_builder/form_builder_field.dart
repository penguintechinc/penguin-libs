import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';
import 'form_builder_types.dart';

/// Renders a single form field based on [FieldConfig].
class FormBuilderField extends StatelessWidget {
  const FormBuilderField({
    super.key,
    required this.config,
    required this.value,
    required this.onChanged,
    this.errorText,
    this.onBlur,
  });

  final FieldConfig config;
  final dynamic value;
  final ValueChanged<dynamic> onChanged;
  final String? errorText;
  final VoidCallback? onBlur;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Label
          Row(
            children: [
              Text(
                config.label,
                style: const TextStyle(
                  color: ElderColors.amber300,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
              if (config.required)
                const Text(
                  ' *',
                  style: TextStyle(color: ElderColors.red400),
                ),
            ],
          ),
          const SizedBox(height: 6),

          // Field
          _buildField(context),

          // Helper text
          if (config.helperText != null && errorText == null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                config.helperText!,
                style: const TextStyle(
                  color: ElderColors.slate400,
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
                style: const TextStyle(
                  color: ElderColors.red400,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildField(BuildContext context) {
    switch (config.type) {
      case FieldType.textarea:
        return _buildTextArea();
      case FieldType.select:
        return _buildDropdown();
      case FieldType.checkbox:
        return _buildCheckbox();
      case FieldType.radio:
        return _buildRadioGroup();
      case FieldType.date:
        return _buildDateField(context);
      case FieldType.time:
        return _buildTimeField(context);
      default:
        return _buildTextField();
    }
  }

  Widget _buildTextField() {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !config.disabled,
      autofocus: config.autoFocus,
      keyboardType: _keyboardType,
      obscureText: config.type == FieldType.password,
      decoration: _inputDecoration,
      onChanged: (v) => onChanged(v),
      onEditingComplete: onBlur,
    );
  }

  Widget _buildTextArea() {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !config.disabled,
      maxLines: config.rows ?? 4,
      decoration: _inputDecoration,
      onChanged: (v) => onChanged(v),
      onEditingComplete: onBlur,
    );
  }

  Widget _buildDropdown() {
    return DropdownButtonFormField<String>(
      value: value?.toString(),
      decoration: _inputDecoration,
      dropdownColor: ElderColors.slate800,
      style: const TextStyle(color: ElderColors.white),
      items: config.options?.map((opt) {
        return DropdownMenuItem<String>(
          value: opt.value,
          child: Text(opt.label),
        );
      }).toList(),
      onChanged: config.disabled ? null : (v) => onChanged(v),
    );
  }

  Widget _buildCheckbox() {
    return Row(
      children: [
        Checkbox(
          value: value == true,
          activeColor: ElderColors.amber500,
          checkColor: ElderColors.slate900,
          onChanged: config.disabled
              ? null
              : (v) => onChanged(v ?? false),
        ),
        Expanded(
          child: Text(
            config.label,
            style: const TextStyle(
              color: ElderColors.slate300,
              fontSize: 14,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildRadioGroup() {
    return Column(
      children: config.options?.map((opt) {
        return RadioListTile<String>(
          title: Text(
            opt.label,
            style: const TextStyle(
              color: ElderColors.slate300,
              fontSize: 14,
            ),
          ),
          value: opt.value,
          groupValue: value?.toString(),
          activeColor: ElderColors.amber500,
          contentPadding: EdgeInsets.zero,
          dense: true,
          onChanged: config.disabled
              ? null
              : (v) => onChanged(v),
        );
      }).toList() ?? [],
    );
  }

  Widget _buildDateField(BuildContext context) {
    return TextFormField(
      initialValue: value?.toString(),
      enabled: !config.disabled,
      decoration: _inputDecoration.copyWith(
        suffixIcon: IconButton(
          icon: const Icon(Icons.calendar_today, size: 18),
          color: ElderColors.slate400,
          onPressed: () async {
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
      enabled: !config.disabled,
      decoration: _inputDecoration.copyWith(
        suffixIcon: IconButton(
          icon: const Icon(Icons.access_time, size: 18),
          color: ElderColors.slate400,
          onPressed: () async {
            final time = await showTimePicker(
              context: context,
              initialTime: TimeOfDay.now(),
            );
            if (time != null) {
              final hour = time.hour.toString().padLeft(2, '0');
              final minute = time.minute.toString().padLeft(2, '0');
              onChanged('$hour:$minute');
            }
          },
        ),
      ),
      onChanged: (v) => onChanged(v),
    );
  }

  TextInputType get _keyboardType {
    switch (config.type) {
      case FieldType.email:
        return TextInputType.emailAddress;
      case FieldType.number:
        return TextInputType.number;
      case FieldType.tel:
        return TextInputType.phone;
      case FieldType.url:
        return TextInputType.url;
      default:
        return TextInputType.text;
    }
  }

  InputDecoration get _inputDecoration {
    return InputDecoration(
      hintText: config.placeholder,
      hintStyle: const TextStyle(color: ElderColors.slate500),
      filled: true,
      fillColor: ElderColors.slate900,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: ElderColors.slate600),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: ElderColors.slate600),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(
          color: ElderColors.amber500,
          width: 2,
        ),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: ElderColors.red400),
      ),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: 12,
        vertical: 12,
      ),
    );
  }
}
