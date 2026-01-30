import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';
import 'form_field_config.dart';
import 'form_field_builder.dart';
import 'form_tab.dart';
import 'form_color_config.dart';
import 'form_validators.dart';

/// A modal form dialog supporting tabbed layouts, validation, and the Elder theme.
///
/// Port of the React FormModalBuilder component.
///
/// Features:
/// - 18 field types
/// - Auto-tabbing when fields exceed threshold
/// - Manual tabs via [FormTab]
/// - Tab error indicators
/// - Conditional field visibility ([FormFieldConfig.showWhen])
/// - File upload
/// - Password generation
/// - Async submit with loading state
class FormModalBuilder extends StatefulWidget {
  const FormModalBuilder({
    super.key,
    required this.title,
    required this.fields,
    required this.onSubmit,
    this.onCancel,
    this.tabs,
    this.initialValues = const {},
    this.submitLabel = 'Submit',
    this.cancelLabel = 'Cancel',
    this.colorConfig = FormColorConfig.elder,
    this.autoTabThreshold = 8,
    this.fieldsPerTab = 6,
    this.maxWidth = 600,
  });

  final String title;
  final List<FormFieldConfig> fields;
  final Future<void> Function(Map<String, dynamic> values) onSubmit;
  final VoidCallback? onCancel;
  final List<FormTab>? tabs;
  final Map<String, dynamic> initialValues;
  final String submitLabel;
  final String cancelLabel;
  final FormColorConfig colorConfig;
  final int autoTabThreshold;
  final int fieldsPerTab;
  final double maxWidth;

  /// Show this form as a modal dialog.
  static Future<void> show({
    required BuildContext context,
    required String title,
    required List<FormFieldConfig> fields,
    required Future<void> Function(Map<String, dynamic> values) onSubmit,
    List<FormTab>? tabs,
    Map<String, dynamic> initialValues = const {},
    String submitLabel = 'Submit',
    String cancelLabel = 'Cancel',
    FormColorConfig colorConfig = FormColorConfig.elder,
  }) {
    return showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => FormModalBuilder(
        title: title,
        fields: fields,
        onSubmit: (values) async {
          await onSubmit(values);
          if (context.mounted) Navigator.of(context).pop();
        },
        onCancel: () => Navigator.of(context).pop(),
        tabs: tabs,
        initialValues: initialValues,
        submitLabel: submitLabel,
        cancelLabel: cancelLabel,
        colorConfig: colorConfig,
      ),
    );
  }

  @override
  State<FormModalBuilder> createState() => _FormModalBuilderState();
}

class _FormModalBuilderState extends State<FormModalBuilder>
    with SingleTickerProviderStateMixin {
  final _formKey = GlobalKey<FormState>();
  late Map<String, dynamic> _values;
  final Map<String, String> _errors = {};
  bool _isSubmitting = false;
  TabController? _tabController;
  List<_TabData> _tabData = [];

  @override
  void initState() {
    super.initState();
    _values = Map<String, dynamic>.from(widget.initialValues);

    // Set defaults for fields not in initialValues
    for (final field in widget.fields) {
      if (!_values.containsKey(field.name) && field.defaultValue != null) {
        _values[field.name] = field.defaultValue;
      }
    }

    _setupTabs();
  }

  void _setupTabs() {
    final visibleFields = _getVisibleFields();

    if (widget.tabs != null && widget.tabs!.isNotEmpty) {
      // Manual tabs
      _tabData = widget.tabs!.map((tab) {
        final tabFields = visibleFields
            .where((f) => f.tab == tab.id)
            .toList();
        return _TabData(id: tab.id, label: tab.label, fields: tabFields);
      }).toList();

      // Add fields without a tab assignment to the first tab
      final assignedFields =
          _tabData.expand((t) => t.fields).map((f) => f.name).toSet();
      final unassigned =
          visibleFields.where((f) => !assignedFields.contains(f.name)).toList();
      if (unassigned.isNotEmpty && _tabData.isNotEmpty) {
        _tabData.first.fields.insertAll(0, unassigned);
      }
    } else if (visibleFields.length > widget.autoTabThreshold) {
      // Auto-tab
      _tabData = [];
      for (var i = 0; i < visibleFields.length; i += widget.fieldsPerTab) {
        final end = (i + widget.fieldsPerTab > visibleFields.length)
            ? visibleFields.length
            : i + widget.fieldsPerTab;
        final chunk = visibleFields.sublist(i, end);
        _tabData.add(_TabData(
          id: 'tab_${_tabData.length}',
          label: 'Page ${_tabData.length + 1}',
          fields: chunk,
        ));
      }
    }

    if (_tabData.length > 1) {
      _tabController = TabController(
        length: _tabData.length,
        vsync: this,
      );
    }
  }

  List<FormFieldConfig> _getVisibleFields() {
    return widget.fields.where((f) {
      if (f.hidden) return false;
      if (f.showWhen != null) return f.showWhen!(_values);
      return true;
    }).toList();
  }

  bool _tabHasErrors(int index) {
    if (index >= _tabData.length) return false;
    return _tabData[index]
        .fields
        .any((f) => _errors.containsKey(f.name));
  }

  void _validateAll() {
    _errors.clear();
    for (final field in widget.fields) {
      final validator = FormValidators.buildValidator(
        type: field.type.name,
        required: field.required,
        min: field.min,
        max: field.max,
        pattern: field.pattern,
        label: field.label,
      );
      final error = validator(_values[field.name]);
      if (error != null) {
        _errors[field.name] = error;
      }
    }
  }

  Future<void> _handleSubmit() async {
    _validateAll();
    setState(() {});

    if (_errors.isNotEmpty) {
      // Switch to the first tab with errors
      if (_tabController != null) {
        for (var i = 0; i < _tabData.length; i++) {
          if (_tabHasErrors(i)) {
            _tabController!.animateTo(i);
            break;
          }
        }
      }
      return;
    }

    setState(() => _isSubmitting = true);
    try {
      await widget.onSubmit(_values);
    } catch (e) {
      if (mounted) {
        setState(() {
          _errors['_form'] = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  void dispose() {
    _tabController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = widget.colorConfig;

    return Dialog(
      backgroundColor: colors.modalBackground,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: ElderColors.slate700),
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: widget.maxWidth,
          maxHeight: MediaQuery.of(context).size.height * 0.85,
        ),
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header
              _buildHeader(colors),

              // Tab bar (if tabs)
              if (_tabController != null) _buildTabBar(colors),

              // Body
              Flexible(child: _buildBody(colors)),

              // Form-level error
              if (_errors.containsKey('_form'))
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 8,
                  ),
                  child: Text(
                    _errors['_form']!,
                    style: TextStyle(
                      color: colors.errorText,
                      fontSize: 13,
                    ),
                  ),
                ),

              // Footer
              _buildFooter(colors),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(FormColorConfig colors) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: colors.headerBackground,
        border: Border(
          bottom: BorderSide(color: ElderColors.slate700),
        ),
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(12),
          topRight: Radius.circular(12),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              widget.title,
              style: TextStyle(
                color: colors.titleText,
                fontSize: 18,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          if (widget.onCancel != null)
            IconButton(
              icon: Icon(Icons.close, color: colors.descriptionText),
              onPressed: _isSubmitting ? null : widget.onCancel,
              splashRadius: 18,
            ),
        ],
      ),
    );
  }

  Widget _buildTabBar(FormColorConfig colors) {
    return Container(
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(color: colors.tabBorder),
        ),
      ),
      child: TabBar(
        controller: _tabController,
        isScrollable: _tabData.length > 4,
        labelColor: colors.activeTab,
        unselectedLabelColor: colors.inactiveTab,
        indicatorColor: colors.activeTabBorder,
        tabs: _tabData.asMap().entries.map((entry) {
          final hasError = _tabHasErrors(entry.key);
          return Tab(
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(entry.value.label),
                if (hasError) ...[
                  const SizedBox(width: 6),
                  Icon(
                    Icons.error_outline,
                    size: 14,
                    color: colors.errorTabText,
                  ),
                ],
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildBody(FormColorConfig colors) {
    if (_tabController != null) {
      return TabBarView(
        controller: _tabController,
        children: _tabData.map((tab) {
          return SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: tab.fields
                  .map((f) => _buildFieldWidget(f, colors))
                  .toList(),
            ),
          );
        }).toList(),
      );
    }

    final visibleFields = _getVisibleFields();
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: visibleFields
            .map((f) => _buildFieldWidget(f, colors))
            .toList(),
      ),
    );
  }

  Widget _buildFieldWidget(FormFieldConfig field, FormColorConfig colors) {
    return FormFieldBuilder(
      field: field,
      value: _values[field.name],
      errorText: _errors[field.name],
      colorConfig: colors,
      onChanged: (v) {
        setState(() {
          _values[field.name] = v;
          _errors.remove(field.name);
        });
      },
    );
  }

  Widget _buildFooter(FormColorConfig colors) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.footerBackground,
        border: Border(
          top: BorderSide(color: ElderColors.slate700),
        ),
        borderRadius: const BorderRadius.only(
          bottomLeft: Radius.circular(12),
          bottomRight: Radius.circular(12),
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          if (widget.onCancel != null)
            OutlinedButton(
              onPressed: _isSubmitting ? null : widget.onCancel,
              style: OutlinedButton.styleFrom(
                foregroundColor: colors.secondaryButtonText,
                side: BorderSide(color: colors.secondaryButtonBorder),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 12,
                ),
              ),
              child: Text(widget.cancelLabel),
            ),
          const SizedBox(width: 12),
          ElevatedButton(
            onPressed: _isSubmitting ? null : _handleSubmit,
            style: ElevatedButton.styleFrom(
              backgroundColor: colors.primaryButton,
              foregroundColor: colors.buttonText,
              disabledBackgroundColor: ElderColors.slate600,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
              ),
              padding: const EdgeInsets.symmetric(
                horizontal: 20,
                vertical: 12,
              ),
            ),
            child: _isSubmitting
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: ElderColors.slate300,
                    ),
                  )
                : Text(widget.submitLabel),
          ),
        ],
      ),
    );
  }
}

/// Internal tab data structure.
class _TabData {
  _TabData({
    required this.id,
    required this.label,
    required this.fields,
  });

  final String id;
  final String label;
  final List<FormFieldConfig> fields;
}
