import 'dart:convert';
import 'dart:typed_data';
import 'package:socket_io_client/socket_io_client.dart' as IO;

typedef OnKeybinds = void Function(List<dynamic> keybinds);
typedef OnImage = void Function(Uint8List bytes, String filename, String progress);
typedef OnVoid = void Function();

/// Manages the Socket.IO connection to the astro-swiper backend.
/// Assumes the connection goes to a local port that is SSH-tunneled.
class SocketService {
  IO.Socket? _socket;

  bool get isConnected => _socket?.connected ?? false;

  void connect({
    required int port,
    required OnKeybinds onKeybinds,
    required OnImage onImage,
    required OnVoid onLoading,
    required OnVoid onDone,
    required OnVoid onDisconnect,
  }) {
    _socket = IO.io(
      'http://127.0.0.1:$port',
      IO.OptionBuilder()
          .setTransports(['websocket'])
          .disableAutoConnect()
          .setTimeout(10000)
          .build(),
    );

    // Server sends [[key, label], ...] — back button has label 'back'
    _socket!.on('keybinds', (data) {
      if (data is List) onKeybinds(data);
    });

    // Server sends {image: '<base64>', filename: '...', progress: '...'}
    _socket!.on('update', (data) {
      if (data is! Map) return;
      final imageStr = data['image'] as String? ?? '';
      final filename = data['filename'] as String? ?? '';
      final progress = data['progress'] as String? ?? '';
      try {
        onImage(base64Decode(imageStr), filename, progress);
      } catch (_) {}
    });

    // Server signals rendering in progress
    _socket!.on('loading', (_) => onLoading());

    // Server signals all triplets have been classified
    _socket!.on('done', (_) => onDone());

    _socket!.on('disconnect', (_) => onDisconnect());

    _socket!.connect();
  }

  /// Emit a keypress exactly as the web client does:
  ///   socket.emit('keypress', {key: 'a'})
  void sendKey(String key) {
    _socket?.emit('keypress', {'key': key});
  }

  void disconnect() {
    _socket?.disconnect();
    _socket?.dispose();
    _socket = null;
  }
}
