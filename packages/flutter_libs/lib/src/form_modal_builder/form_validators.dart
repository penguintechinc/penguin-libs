/// Form field validators for [FormModalBuilder].
///
/// Each validator returns `null` if valid, or an error message string.
class FormValidators {
  static final RegExp _emailPattern =
      RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$');
  static final RegExp _telPattern =
      RegExp(r'^[\d\s\-+()]+$');
  static final RegExp _datePattern =
      RegExp(r'^\d{4}-\d{2}-\d{2}$');
  static final RegExp _timePattern =
      RegExp(r'^\d{2}:\d{2}(:\d{2})?$');
  static final RegExp _datetimePattern =
      RegExp(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}');
  static final RegExp _urlPattern =
      RegExp(r'^https?://\S+$', caseSensitive: false);

  /// Build a composite validator for the given field type and constraints.
  static String? Function(dynamic) buildValidator({
    required String type,
    bool required = false,
    num? min,
    num? max,
    String? pattern,
    String? label,
  }) {
    return (dynamic value) {
      final fieldLabel = label ?? 'This field';
      final strValue = value?.toString().trim() ?? '';

      // Required check
      if (required && strValue.isEmpty) {
        return '$fieldLabel is required';
      }

      // Skip further validation if empty and not required
      if (strValue.isEmpty) return null;

      switch (type) {
        case 'email':
          if (!_emailPattern.hasMatch(strValue)) {
            return 'Please enter a valid email address';
          }
        case 'url':
          if (!_urlPattern.hasMatch(strValue)) {
            return 'Please enter a valid URL';
          }
        case 'tel':
          if (!_telPattern.hasMatch(strValue)) {
            return 'Please enter a valid phone number';
          }
        case 'number':
          final numValue = num.tryParse(strValue);
          if (numValue == null) {
            return 'Please enter a valid number';
          }
          if (min != null && numValue < min) {
            return '$fieldLabel must be at least $min';
          }
          if (max != null && numValue > max) {
            return '$fieldLabel must be at most $max';
          }
        case 'date':
          if (!_datePattern.hasMatch(strValue)) {
            return 'Please enter a valid date (YYYY-MM-DD)';
          }
        case 'time':
          if (!_timePattern.hasMatch(strValue)) {
            return 'Please enter a valid time (HH:MM)';
          }
        case 'datetime-local':
        case 'datetimeLocal':
          if (!_datetimePattern.hasMatch(strValue)) {
            return 'Please enter a valid date and time';
          }
        case 'password':
        case 'password_generate':
        case 'passwordGenerate':
          if (strValue.length < 8) {
            return 'Password must be at least 8 characters';
          }
        case 'checkbox_multi':
        case 'checkboxMulti':
          if (required && value is List && value.isEmpty) {
            return 'Please select at least one option';
          }
      }

      // Custom pattern validation
      if (pattern != null && strValue.isNotEmpty) {
        if (!RegExp(pattern).hasMatch(strValue)) {
          return '$fieldLabel format is invalid';
        }
      }

      return null;
    };
  }

  // Convenience validators

  static String? validateRequired(dynamic value, [String? label]) {
    final strValue = value?.toString().trim() ?? '';
    if (strValue.isEmpty) return '${label ?? 'This field'} is required';
    return null;
  }

  static String? validateEmail(String? value) {
    if (value == null || value.trim().isEmpty) return null;
    if (!_emailPattern.hasMatch(value.trim())) {
      return 'Please enter a valid email address';
    }
    return null;
  }

  static String? validateUrl(String? value) {
    if (value == null || value.trim().isEmpty) return null;
    if (!_urlPattern.hasMatch(value.trim())) {
      return 'Please enter a valid URL';
    }
    return null;
  }

  static String? validatePhone(String? value) {
    if (value == null || value.trim().isEmpty) return null;
    if (!_telPattern.hasMatch(value.trim())) {
      return 'Please enter a valid phone number';
    }
    return null;
  }

  static String? validatePassword(String? value) {
    if (value == null || value.isEmpty) return null;
    if (value.length < 8) {
      return 'Password must be at least 8 characters';
    }
    return null;
  }

  static String? validateNumber(String? value, {num? min, num? max}) {
    if (value == null || value.trim().isEmpty) return null;
    final numValue = num.tryParse(value.trim());
    if (numValue == null) return 'Please enter a valid number';
    if (min != null && numValue < min) return 'Must be at least $min';
    if (max != null && numValue > max) return 'Must be at most $max';
    return null;
  }
}
