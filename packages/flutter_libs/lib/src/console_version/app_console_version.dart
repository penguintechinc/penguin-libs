import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'version_info.dart';
import 'version_logger.dart';
import 'console_style_config.dart';

/// A widget that fetches the app version from an API endpoint,
/// then logs it to the developer console.
///
/// Renders nothing visible ([SizedBox.shrink]).
class AppConsoleVersion extends StatefulWidget {
  const AppConsoleVersion({
    super.key,
    required this.appName,
    required this.versionUrl,
    this.environment,
    this.metadata,
    this.styleConfig = ConsoleStyleConfig.elder,
    this.headers = const {},
  });

  final String appName;
  final String versionUrl;
  final String? environment;
  final Map<String, String>? metadata;
  final ConsoleStyleConfig styleConfig;
  final Map<String, String> headers;

  @override
  State<AppConsoleVersion> createState() => _AppConsoleVersionState();
}

class _AppConsoleVersionState extends State<AppConsoleVersion> {
  @override
  void initState() {
    super.initState();
    _fetchAndLogVersion();
  }

  Future<void> _fetchAndLogVersion() async {
    try {
      final response = await http.get(
        Uri.parse(widget.versionUrl),
        headers: widget.headers,
      );
      if (response.statusCode == 200) {
        final data = json.decode(response.body) as Map<String, dynamic>;
        final version = data['version'] as String? ?? '0.0.0';
        final buildEpoch = data['buildEpoch'] as int?;
        final info = parseVersion(version, buildEpoch: buildEpoch);

        final meta = <String, String>{
          ...?widget.metadata,
          'source': 'API',
        };

        logVersionToConsole(
          widget.appName,
          info,
          environment: widget.environment,
          metadata: meta,
        );
      }
    } catch (e) {
      // Silently fail — version logging is non-critical
    }
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
