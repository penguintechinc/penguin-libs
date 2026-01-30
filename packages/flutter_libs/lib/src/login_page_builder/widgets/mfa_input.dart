import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../theme/elder_colors.dart';

/// A 6-digit MFA code input with auto-advance focus.
///
/// Each digit gets its own text field. Supports:
/// - Auto-advance on digit entry
/// - Backspace navigates to previous field
/// - Paste support (fills all fields from clipboard)
class MFAInput extends StatefulWidget {
  const MFAInput({
    super.key,
    this.length = 6,
    required this.onCompleted,
    this.onChanged,
    this.inputBackground = ElderColors.slate900,
    this.inputBorder = ElderColors.slate600,
    this.inputFocusBorder = ElderColors.amber500,
    this.textColor = ElderColors.white,
    this.autoFocus = true,
  });

  final int length;
  final ValueChanged<String> onCompleted;
  final ValueChanged<String>? onChanged;
  final Color inputBackground;
  final Color inputBorder;
  final Color inputFocusBorder;
  final Color textColor;
  final bool autoFocus;

  @override
  State<MFAInput> createState() => _MFAInputState();
}

class _MFAInputState extends State<MFAInput> {
  late final List<TextEditingController> _controllers;
  late final List<FocusNode> _focusNodes;

  @override
  void initState() {
    super.initState();
    _controllers = List.generate(
      widget.length,
      (_) => TextEditingController(),
    );
    _focusNodes = List.generate(
      widget.length,
      (_) => FocusNode(),
    );
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    for (final f in _focusNodes) {
      f.dispose();
    }
    super.dispose();
  }

  String get _currentCode =>
      _controllers.map((c) => c.text).join();

  void _onChanged(int index, String value) {
    // Handle paste (multi-character input)
    if (value.length > 1) {
      _handlePaste(value);
      return;
    }

    if (value.isNotEmpty && index < widget.length - 1) {
      _focusNodes[index + 1].requestFocus();
    }

    final code = _currentCode;
    widget.onChanged?.call(code);

    if (code.length == widget.length) {
      widget.onCompleted(code);
    }
  }

  void _handlePaste(String value) {
    final digits = value.replaceAll(RegExp(r'[^0-9]'), '');
    for (var i = 0; i < widget.length && i < digits.length; i++) {
      _controllers[i].text = digits[i];
    }
    final focusIndex =
        digits.length >= widget.length ? widget.length - 1 : digits.length;
    _focusNodes[focusIndex].requestFocus();

    final code = _currentCode;
    widget.onChanged?.call(code);
    if (code.length == widget.length) {
      widget.onCompleted(code);
    }
  }

  void _onKeyEvent(int index, KeyEvent event) {
    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.backspace &&
        _controllers[index].text.isEmpty &&
        index > 0) {
      _controllers[index - 1].clear();
      _focusNodes[index - 1].requestFocus();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(widget.length, (index) {
        return Container(
          width: 48,
          height: 56,
          margin: EdgeInsets.only(
            right: index < widget.length - 1 ? 8 : 0,
          ),
          child: KeyboardListener(
            focusNode: FocusNode(),
            onKeyEvent: (event) => _onKeyEvent(index, event),
            child: TextField(
              controller: _controllers[index],
              focusNode: _focusNodes[index],
              autofocus: widget.autoFocus && index == 0,
              textAlign: TextAlign.center,
              keyboardType: TextInputType.number,
              maxLength: 1,
              style: TextStyle(
                color: widget.textColor,
                fontSize: 24,
                fontWeight: FontWeight.w600,
              ),
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
              ],
              decoration: InputDecoration(
                counterText: '',
                filled: true,
                fillColor: widget.inputBackground,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide(color: widget.inputBorder),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide(color: widget.inputBorder),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide(
                    color: widget.inputFocusBorder,
                    width: 2,
                  ),
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
              ),
              onChanged: (v) => _onChanged(index, v),
            ),
          ),
        );
      }),
    );
  }
}
