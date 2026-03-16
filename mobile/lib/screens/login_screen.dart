import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/app_state.dart';
import '../services/ssh_tunnel_service.dart';
import '../services/socket_service.dart';
import 'classifier_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _hostCtrl = TextEditingController();
  final _sshPortCtrl = TextEditingController(text: '22');
  final _serverPortCtrl = TextEditingController(text: '5000');
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _obscurePass = true;
  bool _savePrefs = true;

  @override
  void initState() {
    super.initState();
    _loadPrefs();
  }

  Future<void> _loadPrefs() async {
    final p = await SharedPreferences.getInstance();
    setState(() {
      _hostCtrl.text = p.getString('host') ?? '';
      _sshPortCtrl.text = p.getString('ssh_port') ?? '22';
      _serverPortCtrl.text = p.getString('server_port') ?? '5000';
      _userCtrl.text = p.getString('username') ?? '';
    });
  }

  Future<void> _savePrefsIfNeeded() async {
    if (!_savePrefs) return;
    final p = await SharedPreferences.getInstance();
    await p.setString('host', _hostCtrl.text.trim());
    await p.setString('ssh_port', _sshPortCtrl.text.trim());
    await p.setString('server_port', _serverPortCtrl.text.trim());
    await p.setString('username', _userCtrl.text.trim());
  }

  Future<void> _connect() async {
    if (!_formKey.currentState!.validate()) return;

    final appState = context.read<AppState>();
    appState.setConnecting();
    await _savePrefsIfNeeded();

    final sshSvc = SshTunnelService();
    final sockSvc = SocketService();

    try {
      await sshSvc.connect(
        host: _hostCtrl.text.trim(),
        sshPort: int.parse(_sshPortCtrl.text.trim()),
        username: _userCtrl.text.trim(),
        password: _passCtrl.text,
        remotePort: int.parse(_serverPortCtrl.text.trim()),
      );

      final localPort = sshSvc.localPort!;
      final completer = Completer<void>();

      sockSvc.connect(
        port: localPort,
        onKeybinds: (keybinds) {
          appState.setKeybinds(keybinds);
          appState.setConnected();
          if (!completer.isCompleted) completer.complete();
        },
        onImage: appState.setImage,
        onLoading: appState.setLoading,
        onDone: appState.setDone,
        onDisconnect: appState.setDisconnected,
      );

      // Wait for the server to respond with keybinds (confirms tunnel works)
      await completer.future.timeout(
        const Duration(seconds: 15),
        onTimeout: () => throw TimeoutException('Server did not respond in time'),
      );

      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => ClassifierScreen(ssh: sshSvc, socket: sockSvc),
        ),
      );
    } catch (e) {
      sockSvc.disconnect();
      await sshSvc.disconnect();
      appState.setError(e.toString().replaceAll('Exception: ', ''));
    }
  }

  @override
  void dispose() {
    _hostCtrl.dispose();
    _sshPortCtrl.dispose();
    _serverPortCtrl.dispose();
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  InputDecoration _dec(String label, IconData icon) => InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
      );

  String? _reqValidator(String? v) =>
      (v?.trim().isEmpty ?? true) ? 'Required' : null;

  String? _portValidator(String? v) {
    final n = int.tryParse(v?.trim() ?? '');
    return (n == null || n < 1 || n > 65535) ? 'Invalid port' : null;
  }

  @override
  Widget build(BuildContext context) {
    final appState = context.watch<AppState>();
    final isConnecting = appState.status == ConnectionStatus.connecting;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Header
                  const Icon(Icons.auto_awesome, size: 56, color: Colors.teal),
                  const SizedBox(height: 8),
                  Text(
                    'Astro Swiper',
                    textAlign: TextAlign.center,
                    style: Theme.of(context)
                        .textTheme
                        .headlineMedium
                        ?.copyWith(color: Colors.teal, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  const Text(
                    'SSH → remote server',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey, fontSize: 12),
                  ),
                  const SizedBox(height: 32),

                  // Hostname
                  TextFormField(
                    controller: _hostCtrl,
                    decoration: _dec('Hostname or IP', Icons.dns),
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    validator: _reqValidator,
                  ),
                  const SizedBox(height: 12),

                  // SSH Port | Server Port
                  Row(children: [
                    Expanded(
                      child: TextFormField(
                        controller: _sshPortCtrl,
                        decoration: _dec('SSH Port', Icons.cable),
                        keyboardType: TextInputType.number,
                        validator: _portValidator,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextFormField(
                        controller: _serverPortCtrl,
                        decoration: _dec('Server Port', Icons.router),
                        keyboardType: TextInputType.number,
                        validator: _portValidator,
                      ),
                    ),
                  ]),
                  const SizedBox(height: 12),

                  // Username
                  TextFormField(
                    controller: _userCtrl,
                    decoration: _dec('Username', Icons.person),
                    autocorrect: false,
                    validator: _reqValidator,
                  ),
                  const SizedBox(height: 12),

                  // Password
                  TextFormField(
                    controller: _passCtrl,
                    decoration: _dec('Password', Icons.lock).copyWith(
                      suffixIcon: IconButton(
                        icon: Icon(_obscurePass
                            ? Icons.visibility_off
                            : Icons.visibility),
                        onPressed: () =>
                            setState(() => _obscurePass = !_obscurePass),
                      ),
                    ),
                    obscureText: _obscurePass,
                    validator: _reqValidator,
                  ),
                  const SizedBox(height: 4),

                  // Remember prefs
                  Row(children: [
                    Checkbox(
                      value: _savePrefs,
                      onChanged: (v) => setState(() => _savePrefs = v ?? true),
                      activeColor: Colors.teal,
                    ),
                    const Text('Remember host & username',
                        style: TextStyle(fontSize: 13)),
                  ]),

                  // Error message
                  if (appState.errorMessage.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.shade900.withOpacity(0.4),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.red.shade700),
                      ),
                      child: Text(
                        appState.errorMessage,
                        style: const TextStyle(
                            color: Colors.redAccent, fontSize: 13),
                      ),
                    ),
                  ],
                  const SizedBox(height: 20),

                  // Connect button
                  ElevatedButton.icon(
                    onPressed: isConnecting ? null : _connect,
                    icon: isConnecting
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child:
                                CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.login),
                    label:
                        Text(isConnecting ? 'Connecting…' : 'Connect'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.teal,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
