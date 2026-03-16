import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/app_state.dart';
import '../services/socket_service.dart';
import '../services/ssh_tunnel_service.dart';
import 'login_screen.dart';

class ClassifierScreen extends StatefulWidget {
  final SshTunnelService ssh;
  final SocketService socket;

  const ClassifierScreen({super.key, required this.ssh, required this.socket});

  @override
  State<ClassifierScreen> createState() => _ClassifierScreenState();
}

class _ClassifierScreenState extends State<ClassifierScreen> {
  bool _contrastOpen = false;

  Future<void> _disconnect() async {
    widget.socket.disconnect();
    await widget.ssh.disconnect();
    if (!mounted) return;
    context.read<AppState>().setDisconnected();
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
  }

  void _key(String k) => widget.socket.sendKey(k);

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();

    // Fell off the server — return to login
    if (state.status == ConnectionStatus.disconnected) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
        );
      });
      return const SizedBox.shrink();
    }

    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: const Color(0xFF111111),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              state.filename.isEmpty ? 'Astro Swiper' : state.filename,
              style: const TextStyle(fontSize: 12, color: Colors.white70),
              overflow: TextOverflow.ellipsis,
            ),
            if (state.progress.isNotEmpty)
              Text(
                state.progress,
                style:
                    const TextStyle(fontSize: 11, color: Colors.tealAccent),
              ),
          ],
        ),
        actions: [
          IconButton(
            icon: Icon(
              Icons.tune,
              color: _contrastOpen ? Colors.tealAccent : Colors.grey,
            ),
            tooltip: 'Contrast / Brightness',
            onPressed: () =>
                setState(() => _contrastOpen = !_contrastOpen),
          ),
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.grey),
            tooltip: 'Disconnect',
            onPressed: _disconnect,
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Image ──────────────────────────────────────────────
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (state.isDone)
                  _doneScreen()
                else if (state.image != null)
                  InteractiveViewer(
                    child: Image.memory(
                      state.image!,
                      fit: BoxFit.contain,
                      gaplessPlayback: true,
                    ),
                  )
                else
                  const Center(
                    child: CircularProgressIndicator(color: Colors.teal),
                  ),

                // Rendering overlay
                if (state.isLoading)
                  Container(
                    color: Colors.black54,
                    child: const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          CircularProgressIndicator(color: Colors.teal),
                          SizedBox(height: 12),
                          Text('Rendering…',
                              style: TextStyle(color: Colors.teal)),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),

          // ── Contrast panel (collapsible) ───────────────────────
          if (_contrastOpen) _contrastPanel(),

          // ── Classification buttons ─────────────────────────────
          if (!state.isDone) _buttonBar(state),
        ],
      ),
    );
  }

  // ── Sub-widgets ──────────────────────────────────────────────────────────

  Widget _doneScreen() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.check_circle_outline,
                size: 80, color: Colors.teal),
            const SizedBox(height: 16),
            const Text(
              'All done!',
              style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.bold,
                  color: Colors.teal),
            ),
            const SizedBox(height: 8),
            const Text(
              'Every triplet has been classified.',
              style: TextStyle(color: Colors.white54),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 28),
            ElevatedButton.icon(
              onPressed: _disconnect,
              icon: const Icon(Icons.logout),
              label: const Text('Disconnect'),
              style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.teal,
                  foregroundColor: Colors.white),
            ),
          ],
        ),
      ),
    );
  }

  Widget _contrastPanel() {
    return Container(
      color: const Color(0xFF181818),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: Column(
        children: [
          _contrastRow(
            icon: Icons.brightness_6,
            label: 'Brightness',
            onMinus: () => _key('shift+left'),
            onPlus: () => _key('shift+right'),
          ),
          const SizedBox(height: 6),
          _contrastRow(
            icon: Icons.contrast,
            label: 'Contrast',
            onMinus: () => _key('shift+down'),
            onPlus: () => _key('shift+up'),
          ),
        ],
      ),
    );
  }

  Widget _contrastRow({
    required IconData icon,
    required String label,
    required VoidCallback onMinus,
    required VoidCallback onPlus,
  }) {
    return Row(
      children: [
        Icon(icon, size: 16, color: Colors.grey),
        const SizedBox(width: 8),
        Text(label,
            style: const TextStyle(fontSize: 12, color: Colors.grey)),
        const Spacer(),
        _adjBtn('−', onMinus),
        const SizedBox(width: 10),
        _adjBtn('+', onPlus),
      ],
    );
  }

  Widget _adjBtn(String label, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 34,
        height: 34,
        decoration: BoxDecoration(
          border: Border.all(color: Colors.teal),
          borderRadius: BorderRadius.circular(4),
        ),
        alignment: Alignment.center,
        child: Text(label,
            style: const TextStyle(color: Colors.tealAccent, fontSize: 20)),
      ),
    );
  }

  Widget _buttonBar(AppState state) {
    return Container(
      color: const Color(0xFF111111),
      padding: const EdgeInsets.fromLTRB(8, 10, 8, 14),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Classification buttons
          Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.center,
            children: state.keybinds.map((kb) {
              return _classBtn(kb[1], () => _key(kb[0]));
            }).toList(),
          ),
          const SizedBox(height: 8),
          // Undo
          TextButton.icon(
            onPressed: () => _key(state.backKey),
            icon: const Icon(Icons.undo, size: 15, color: Colors.grey),
            label: const Text('Undo last',
                style: TextStyle(color: Colors.grey, fontSize: 12)),
            style: TextButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              minimumSize: Size.zero,
            ),
          ),
        ],
      ),
    );
  }

  Widget _classBtn(String label, VoidCallback onTap) {
    return ElevatedButton(
      onPressed: onTap,
      style: ElevatedButton.styleFrom(
        backgroundColor: const Color(0xFF1A3333),
        foregroundColor: Colors.tealAccent,
        elevation: 0,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(6),
          side: const BorderSide(color: Colors.teal, width: 0.5),
        ),
      ),
      child: Text(label, style: const TextStyle(fontSize: 14)),
    );
  }
}
