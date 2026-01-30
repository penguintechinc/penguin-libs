import 'package:flutter/material.dart';
import '../theme/elder_colors.dart';

/// A modal dialog wrapper for form content.
///
/// Displays content in an Elder-themed dialog with a title,
/// scrollable body, and action buttons.
class FormBuilderModal extends StatelessWidget {
  const FormBuilderModal({
    super.key,
    required this.title,
    required this.child,
    this.onCancel,
    this.onSubmit,
    this.submitLabel = 'Submit',
    this.cancelLabel = 'Cancel',
    this.isSubmitting = false,
    this.maxWidth = 500,
  });

  final String title;
  final Widget child;
  final VoidCallback? onCancel;
  final VoidCallback? onSubmit;
  final String submitLabel;
  final String cancelLabel;
  final bool isSubmitting;
  final double maxWidth;

  /// Show this modal as a dialog.
  static Future<T?> show<T>({
    required BuildContext context,
    required String title,
    required Widget child,
    VoidCallback? onCancel,
    VoidCallback? onSubmit,
    String submitLabel = 'Submit',
    String cancelLabel = 'Cancel',
    bool isSubmitting = false,
  }) {
    return showDialog<T>(
      context: context,
      barrierDismissible: false,
      builder: (_) => FormBuilderModal(
        title: title,
        onCancel: onCancel ?? () => Navigator.of(context).pop(),
        onSubmit: onSubmit,
        submitLabel: submitLabel,
        cancelLabel: cancelLabel,
        isSubmitting: isSubmitting,
        child: child,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: ElderColors.slate800,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: ElderColors.slate700),
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Header
            Container(
              padding: const EdgeInsets.all(20),
              decoration: const BoxDecoration(
                border: Border(
                  bottom: BorderSide(color: ElderColors.slate700),
                ),
              ),
              child: Text(
                title,
                style: const TextStyle(
                  color: ElderColors.amber400,
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),

            // Body
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: child,
              ),
            ),

            // Footer
            Container(
              padding: const EdgeInsets.all(16),
              decoration: const BoxDecoration(
                color: ElderColors.slate900,
                border: Border(
                  top: BorderSide(color: ElderColors.slate700),
                ),
                borderRadius: BorderRadius.only(
                  bottomLeft: Radius.circular(12),
                  bottomRight: Radius.circular(12),
                ),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  // Cancel button
                  OutlinedButton(
                    onPressed: isSubmitting ? null : onCancel,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: ElderColors.slate300,
                      side: const BorderSide(color: ElderColors.slate600),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 12,
                      ),
                    ),
                    child: Text(cancelLabel),
                  ),
                  const SizedBox(width: 12),
                  // Submit button
                  ElevatedButton(
                    onPressed: isSubmitting ? null : onSubmit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: ElderColors.amber500,
                      foregroundColor: ElderColors.slate900,
                      disabledBackgroundColor: ElderColors.slate600,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 12,
                      ),
                    ),
                    child: isSubmitting
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: ElderColors.slate300,
                            ),
                          )
                        : Text(submitLabel),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
