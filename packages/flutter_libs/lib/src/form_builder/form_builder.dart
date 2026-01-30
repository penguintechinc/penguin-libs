import 'package:flutter/material.dart';
import 'form_builder_types.dart';
import 'form_builder_field.dart';
import 'form_builder_modal.dart';
import 'form_builder_controller.dart';

/// A form widget supporting both inline and modal display modes.
///
/// Uses [FormBuilderController] for state management.
class FormBuilder extends StatefulWidget {
  const FormBuilder({
    super.key,
    required this.config,
    required this.onSubmit,
    this.onCancel,
    this.initialValues = const {},
    this.modal = false,
  });

  final FormConfig config;
  final Future<void> Function(Map<String, dynamic> values) onSubmit;
  final VoidCallback? onCancel;
  final Map<String, dynamic> initialValues;
  final bool modal;

  @override
  State<FormBuilder> createState() => _FormBuilderState();
}

class _FormBuilderState extends State<FormBuilder> {
  late final FormBuilderController _controller;

  @override
  void initState() {
    super.initState();
    _controller = FormBuilderController(
      initialValues: widget.initialValues,
      validateOnChange: widget.config.validateOnChange,
      validateOnBlur: widget.config.validateOnBlur,
    );
    _controller.addListener(_onControllerChanged);
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    _controller.dispose();
    super.dispose();
  }

  void _onControllerChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _handleSubmit() async {
    _controller.setSubmitting(true);
    try {
      await widget.onSubmit(_controller.values);
    } finally {
      if (mounted) {
        _controller.setSubmitting(false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final formContent = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final field in widget.config.fields)
          FormBuilderField(
            config: field,
            value: _controller.values[field.name],
            errorText: _controller.errors[field.name],
            onChanged: (v) => _controller.setValue(field.name, v),
            onBlur: () => _controller.setTouched(field.name),
          ),
      ],
    );

    if (widget.modal) {
      return FormBuilderModal(
        title: widget.config.title ?? 'Form',
        onCancel: widget.onCancel ??
            () => Navigator.of(context).pop(),
        onSubmit: _handleSubmit,
        submitLabel: widget.config.submitLabel,
        cancelLabel: widget.config.cancelLabel,
        isSubmitting: _controller.isSubmitting,
        child: formContent,
      );
    }

    return formContent;
  }
}
