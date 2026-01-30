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
  Future<void> load() async {
    if (!enabled) {
      _loaded = true;
      notifyListeners();
      return;
    }
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_storageKey);
    if (raw != null) {
      try {
        // Simple JSON-like parsing for stored consent
        // In practice, use dart:convert json
        final parts = raw.split(',');
        _consent = CookieConsentData(
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
        _consent = const CookieConsentData();
      }
    }
    _loaded = true;
    notifyListeners();
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
    final value = [
      'accepted:${_consent.accepted}',
      'essential:${_consent.essential}',
      'functional:${_consent.functional}',
      'analytics:${_consent.analytics}',
      'marketing:${_consent.marketing}',
      'timestamp:${_consent.timestamp}',
    ].join(',');
    await prefs.setString(_storageKey, value);
  }
}
