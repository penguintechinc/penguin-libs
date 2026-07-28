import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Consent categories for GDPR compliance.
class CookieConsentData {
  const CookieConsentData({
    this.accepted = false,
    this.essential = true,
    this.functional = false,
    this.analytics = false,
    this.marketing = false,
    this.timestamp,
  });

  factory CookieConsentData.fromJson(Map<String, dynamic> json) {
    return CookieConsentData(
      accepted: json['accepted'] as bool? ?? false,
      essential: true,
      functional: json['functional'] as bool? ?? false,
      analytics: json['analytics'] as bool? ?? false,
      marketing: json['marketing'] as bool? ?? false,
      timestamp: json['timestamp'] as int?,
    );
  }

  final bool accepted;
  final bool essential;
  final bool functional;
  final bool analytics;
  final bool marketing;
  final int? timestamp;

  CookieConsentData copyWith({
    bool? accepted,
    bool? essential,
    bool? functional,
    bool? analytics,
    bool? marketing,
    int? timestamp,
  }) {
    return CookieConsentData(
      accepted: accepted ?? this.accepted,
      essential: essential ?? this.essential,
      functional: functional ?? this.functional,
      analytics: analytics ?? this.analytics,
      marketing: marketing ?? this.marketing,
      timestamp: timestamp ?? this.timestamp,
    );
  }

  Map<String, dynamic> toJson() => {
        'accepted': accepted,
        'essential': essential,
        'functional': functional,
        'analytics': analytics,
        'marketing': marketing,
        'timestamp': timestamp,
      };
}

/// State management for GDPR cookie consent.
///
/// Persists consent preferences via [SharedPreferences].
/// Replaces the React useCookieConsent hook.
class CookieConsentNotifier extends ChangeNotifier {
  CookieConsentNotifier({this.enabled = true});

  static const _storageKey = 'gdpr_consent';

  final bool enabled;
  CookieConsentData _consent = const CookieConsentData();
  bool _loaded = false;

  /// Current consent state.
  CookieConsentData get consent => _consent;

  /// Whether the user can interact with the login form.
  ///
  /// True if GDPR is disabled or consent has been accepted.
  bool get canInteract => !enabled || _consent.accepted;

  /// Whether consent data has been loaded from storage.
  bool get loaded => _loaded;

  /// Load saved consent from persistent storage.
  ///
  /// Reads the current JSON-encoded format; if that's not present but a
  /// legacy comma/colon-encoded value is (from before the JSON migration),
  /// parses that instead so a prior user's consent is never silently reset
  /// to "not accepted". The next [_save] call re-persists in JSON, so the
  /// legacy branch only runs once per installation.
  Future<void> load() async {
    if (!enabled) {
      _loaded = true;
      notifyListeners();
      return;
    }
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_storageKey);
    if (raw != null) {
      _consent = _parseStored(raw) ?? const CookieConsentData();
    }
    _loaded = true;
    notifyListeners();
  }

  /// Parse a stored consent value, trying the current JSON format first
  /// and falling back to the legacy comma/colon format. Returns `null`
  /// only if neither can be parsed (genuinely corrupt data).
  CookieConsentData? _parseStored(String raw) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map<String, dynamic>) {
        return CookieConsentData.fromJson(decoded);
      }
    } on FormatException {
      // Not JSON — fall through to the legacy format below.
    }

    try {
      final parts = raw.split(',');
      return CookieConsentData(
        accepted: parts.contains('accepted:true'),
        functional: parts.contains('functional:true'),
        analytics: parts.contains('analytics:true'),
        marketing: parts.contains('marketing:true'),
        timestamp: int.tryParse(
          parts
              .firstWhere((p) => p.startsWith('timestamp:'),
                  orElse: () => 'timestamp:0')
              .split(':')
              .last,
        ),
      );
    } catch (_) {
      return null;
    }
  }

  /// Accept all cookie categories.
  Future<void> acceptAll() async {
    _consent = CookieConsentData(
      accepted: true,
      essential: true,
      functional: true,
      analytics: true,
      marketing: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
    );
    await _save();
    notifyListeners();
  }

  /// Accept only essential cookies.
  Future<void> acceptEssentialOnly() async {
    _consent = CookieConsentData(
      accepted: true,
      essential: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
    );
    await _save();
    notifyListeners();
  }

  /// Accept with custom preferences.
  Future<void> acceptWithPreferences({
    bool functional = false,
    bool analytics = false,
    bool marketing = false,
  }) async {
    _consent = CookieConsentData(
      accepted: true,
      essential: true,
      functional: functional,
      analytics: analytics,
      marketing: marketing,
      timestamp: DateTime.now().millisecondsSinceEpoch,
    );
    await _save();
    notifyListeners();
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_storageKey, jsonEncode(_consent.toJson()));
  }
}
