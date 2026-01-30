import 'dart:math';

/// Generate a random password of the given [length].
///
/// Uses [Random.secure] for cryptographic randomness.
/// Characters: uppercase, lowercase, digits (matching react-libs).
String generatePassword({int length = 14}) {
  const chars =
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  final random = Random.secure();
  return String.fromCharCodes(
    Iterable.generate(
      length,
      (_) => chars.codeUnitAt(random.nextInt(chars.length)),
    ),
  );
}
