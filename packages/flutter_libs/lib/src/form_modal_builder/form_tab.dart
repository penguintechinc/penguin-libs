/// A tab grouping for form fields in [FormModalBuilder].
class FormTab {
  const FormTab({
    required this.id,
    required this.label,
    this.icon,
    this.description,
  });

  final String id;
  final String label;
  final dynamic icon;
  final String? description;
}
