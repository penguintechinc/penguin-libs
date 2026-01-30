import 'package:flutter/material.dart';
import 'package:flutter_libs/flutter_libs.dart';

void main() {
  runApp(const ExampleApp());
}

class ExampleApp extends StatelessWidget {
  const ExampleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flutter Libs Example',
      theme: ThemeData.dark().copyWith(
        extensions: [ElderThemeData.dark],
      ),
      home: const ExampleHome(),
    );
  }
}

class ExampleHome extends StatelessWidget {
  const ExampleHome({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Flutter Libs Example'),
        backgroundColor: ElderColors.slate800,
      ),
      backgroundColor: ElderColors.slate900,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton(
              onPressed: () => _showFormModal(context),
              style: ElevatedButton.styleFrom(
                backgroundColor: ElderColors.amber500,
                foregroundColor: ElderColors.slate900,
              ),
              child: const Text('Open Form Modal'),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const LoginExample()),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: ElderColors.amber500,
                foregroundColor: ElderColors.slate900,
              ),
              child: const Text('View Login Page'),
            ),
          ],
        ),
      ),
    );
  }

  void _showFormModal(BuildContext context) {
    FormModalBuilder.show(
      context: context,
      title: 'Create Item',
      fields: [
        FormFieldConfig(
          name: 'name',
          label: 'Name',
          type: FormFieldType.text,
          required: true,
          placeholder: 'Enter item name',
        ),
        FormFieldConfig(
          name: 'description',
          label: 'Description',
          type: FormFieldType.textarea,
        ),
        FormFieldConfig(
          name: 'category',
          label: 'Category',
          type: FormFieldType.select,
          options: [
            FormFieldOption(label: 'General', value: 'general'),
            FormFieldOption(label: 'Technical', value: 'technical'),
          ],
        ),
      ],
      onSubmit: (values) async {
        debugPrint('Form submitted: $values');
      },
    );
  }
}

class LoginExample extends StatelessWidget {
  const LoginExample({super.key});

  @override
  Widget build(BuildContext context) {
    return LoginPageBuilder(
      apiConfig: LoginApiConfig(
        loginUrl: 'https://api.example.com/auth/login',
      ),
      branding: BrandingConfig(
        appName: 'Example App',
        tagline: 'Welcome back! Please sign in.',
      ),
      onLoginSuccess: (response) {
        debugPrint('Login success: ${response.user?.email}');
        Navigator.pop(context);
      },
      onLoginError: (error) {
        debugPrint('Login error: $error');
      },
    );
  }
}
