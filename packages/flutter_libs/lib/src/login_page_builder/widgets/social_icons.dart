import 'package:flutter/material.dart';

/// Social login provider icons using CustomPainter.
///
/// Each icon renders at 24x24 by default.

class GoogleIcon extends StatelessWidget {
  const GoogleIcon({super.key, this.size = 24});
  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _GooglePainter()),
    );
  }
}

class _GooglePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 24;
    final path = Path();
    // G logo simplified
    path.moveTo(22.56 * s, 12.25 * s);
    path.cubicTo(22.56 * s, 11.47 * s, 22.49 * s, 10.72 * s, 22.36 * s, 10 * s);
    path.lineTo(12 * s, 10 * s);
    path.lineTo(12 * s, 14.26 * s);
    path.lineTo(17.92 * s, 14.26 * s);
    path.cubicTo(17.66 * s, 15.63 * s, 16.88 * s, 16.79 * s, 15.71 * s, 17.57 * s);
    path.lineTo(15.71 * s, 20.34 * s);
    path.lineTo(19.28 * s, 20.34 * s);
    path.cubicTo(21.36 * s, 18.42 * s, 22.56 * s, 15.6 * s, 22.56 * s, 12.25 * s);
    path.close();
    canvas.drawPath(path, Paint()..color = const Color(0xFF4285F4));

    final path2 = Path();
    path2.moveTo(12 * s, 23 * s);
    path2.cubicTo(14.97 * s, 23 * s, 17.46 * s, 22.02 * s, 19.28 * s, 20.34 * s);
    path2.lineTo(15.71 * s, 17.57 * s);
    path2.cubicTo(14.73 * s, 18.23 * s, 13.48 * s, 18.63 * s, 12 * s, 18.63 * s);
    path2.cubicTo(9.14 * s, 18.63 * s, 6.72 * s, 16.7 * s, 5.84 * s, 14.1 * s);
    path2.lineTo(2.18 * s, 14.1 * s);
    path2.lineTo(2.18 * s, 16.94 * s);
    path2.cubicTo(3.99 * s, 20.53 * s, 7.7 * s, 23 * s, 12 * s, 23 * s);
    path2.close();
    canvas.drawPath(path2, Paint()..color = const Color(0xFF34A853));

    final path3 = Path();
    path3.moveTo(5.84 * s, 14.1 * s);
    path3.cubicTo(5.62 * s, 13.44 * s, 5.49 * s, 12.74 * s, 5.49 * s, 12 * s);
    path3.cubicTo(5.49 * s, 11.26 * s, 5.62 * s, 10.56 * s, 5.84 * s, 9.9 * s);
    path3.lineTo(5.84 * s, 7.06 * s);
    path3.lineTo(2.18 * s, 7.06 * s);
    path3.cubicTo(1.43 * s, 8.55 * s, 1 * s, 10.22 * s, 1 * s, 12 * s);
    path3.cubicTo(1 * s, 13.78 * s, 1.43 * s, 15.45 * s, 2.18 * s, 16.94 * s);
    path3.lineTo(5.84 * s, 14.1 * s);
    path3.close();
    canvas.drawPath(path3, Paint()..color = const Color(0xFFFBBC05));

    final path4 = Path();
    path4.moveTo(12 * s, 5.38 * s);
    path4.cubicTo(13.62 * s, 5.38 * s, 15.06 * s, 5.94 * s, 16.21 * s, 7 * s);
    path4.lineTo(19.36 * s, 3.85 * s);
    path4.cubicTo(17.45 * s, 2.09 * s, 14.97 * s, 1 * s, 12 * s, 1 * s);
    path4.cubicTo(7.7 * s, 1 * s, 3.99 * s, 3.47 * s, 2.18 * s, 7.06 * s);
    path4.lineTo(5.84 * s, 9.9 * s);
    path4.cubicTo(6.72 * s, 7.3 * s, 9.14 * s, 5.38 * s, 12 * s, 5.38 * s);
    path4.close();
    canvas.drawPath(path4, Paint()..color = const Color(0xFFEA4335));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Generic icon for GitHub, Apple, etc. using Material icons as fallback.
class SocialIconWidget extends StatelessWidget {
  const SocialIconWidget({
    super.key,
    required this.icon,
    this.color,
    this.size = 20,
  });

  final IconData icon;
  final Color? color;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Icon(icon, color: color ?? Colors.white, size: size);
  }
}

/// Get the appropriate icon widget for a built-in provider.
Widget getProviderIcon(String provider, {double size = 20}) {
  switch (provider) {
    case 'google':
      return GoogleIcon(size: size);
    case 'github':
      return Icon(Icons.code, size: size, color: Colors.white);
    case 'microsoft':
      return Icon(Icons.window, size: size, color: Colors.white);
    case 'apple':
      return Icon(Icons.apple, size: size, color: Colors.white);
    case 'twitch':
      return Icon(Icons.videocam, size: size, color: Colors.white);
    case 'discord':
      return Icon(Icons.chat_bubble, size: size, color: Colors.white);
    case 'sso':
      return Icon(Icons.vpn_key, size: size, color: Colors.white);
    case 'enterprise':
      return Icon(Icons.business, size: size, color: Colors.white);
    default:
      return Icon(Icons.login, size: size, color: Colors.white);
  }
}
