import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// An ALTCHA (https://altcha.org) proof-of-work challenge, as served by the
/// CAPTCHA `challengeUrl` endpoint.
class AltchaChallenge {
  const AltchaChallenge({
    required this.algorithm,
    required this.challenge,
    required this.salt,
    required this.signature,
    required this.maxNumber,
  });

  /// Parse a challenge from the JSON body returned by `challengeUrl`.
  ///
  /// Throws a [FormatException] if any required field is missing.
  factory AltchaChallenge.fromJson(Map<String, dynamic> json) {
    final challenge = json['challenge'] as String?;
    final salt = json['salt'] as String?;
    final signature = json['signature'] as String?;
    if (challenge == null || salt == null || signature == null) {
      throw const FormatException(
        'Malformed ALTCHA challenge response: missing challenge/salt/signature',
      );
    }
    return AltchaChallenge(
      algorithm: json['algorithm'] as String? ?? 'SHA-256',
      challenge: challenge,
      salt: salt,
      signature: signature,
      maxNumber: (json['maxnumber'] as num?)?.toInt() ?? 1000000,
    );
  }

  final String algorithm;
  final String challenge;
  final String salt;
  final String signature;
  final int maxNumber;
}

/// Fetch an ALTCHA challenge from [challengeUrl].
///
/// Applies a 30-second timeout. Throws on network failure, a non-200
/// response, or a malformed body — callers must treat any thrown error as
/// fail-closed (no CAPTCHA token issued).
Future<AltchaChallenge> fetchAltchaChallenge(String challengeUrl) async {
  final response = await http
      .get(Uri.parse(challengeUrl))
      .timeout(const Duration(seconds: 30));

  if (response.statusCode != 200) {
    throw http.ClientException(
      'ALTCHA challenge request failed with status ${response.statusCode}',
    );
  }

  final decoded = json.decode(response.body);
  if (decoded is! Map<String, dynamic>) {
    throw const FormatException(
      'ALTCHA challenge response was not a JSON object',
    );
  }
  return AltchaChallenge.fromJson(decoded);
}

/// Solve [challenge] by brute-forcing `number` in `[0, maxNumber]` such that
/// `hex(hash(salt + number)) == challenge`, per the ALTCHA protocol.
///
/// Runs on a background isolate via [compute] so the solve loop never blocks
/// the UI thread. Throws [UnsupportedError] for an algorithm this package
/// does not implement, and [StateError] if no solution exists within
/// [AltchaChallenge.maxNumber] — both must be treated as fail-closed by
/// callers.
Future<int> solveAltchaChallenge(AltchaChallenge challenge) {
  return compute(_solveInIsolate, {
    'algorithm': challenge.algorithm,
    'challenge': challenge.challenge,
    'salt': challenge.salt,
    'maxnumber': challenge.maxNumber,
  });
}

/// Top-level entry point required by [compute] — must be a static/top-level
/// function so it can be sent to the background isolate.
int _solveInIsolate(Map<String, dynamic> params) => solveAltchaSync(params);

/// Synchronous ALTCHA solver, exposed directly (not run on an isolate) so it
/// can be exercised in unit tests without the overhead/asynchrony of
/// [compute]. Production code should call [solveAltchaChallenge] instead.
int solveAltchaSync(Map<String, dynamic> params) {
  final algorithm = (params['algorithm'] as String).toUpperCase();
  final salt = params['salt'] as String;
  final challengeHex = (params['challenge'] as String).toLowerCase();
  final maxNumber = params['maxnumber'] as int;

  for (var number = 0; number <= maxNumber; number++) {
    final digest = _hash(algorithm, utf8.encode('$salt$number'));
    if (digest.toString() == challengeHex) {
      return number;
    }
  }
  throw StateError('No ALTCHA solution found within maxnumber=$maxNumber');
}

Digest _hash(String algorithm, List<int> bytes) {
  switch (algorithm) {
    case 'SHA-1':
      return sha1.convert(bytes);
    case 'SHA-256':
      return sha256.convert(bytes);
    case 'SHA-512':
      return sha512.convert(bytes);
    default:
      throw UnsupportedError('Unsupported ALTCHA algorithm: $algorithm');
  }
}

/// Build the base64-encoded ALTCHA verification payload for [challenge]
/// solved with [number] — this is the value sent as the CAPTCHA token.
String buildAltchaPayload(AltchaChallenge challenge, int number) {
  final payload = <String, dynamic>{
    'algorithm': challenge.algorithm,
    'challenge': challenge.challenge,
    'number': number,
    'salt': challenge.salt,
    'signature': challenge.signature,
  };
  return base64.encode(utf8.encode(json.encode(payload)));
}
