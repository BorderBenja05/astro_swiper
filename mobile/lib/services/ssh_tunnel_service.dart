import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:dartssh2/dartssh2.dart';

/// Opens an SSH connection and creates a local TCP port-forward to the
/// remote astro-swiper Flask-SocketIO server.
///
/// Usage:
///   final svc = SshTunnelService();
///   await svc.connect(host: '...', sshPort: 22, username: '...', password: '...');
///   // then connect Socket.IO to http://127.0.0.1:${svc.localPort}
///   await svc.disconnect();
class SshTunnelService {
  SSHClient? _client;
  ServerSocket? _localServer;
  int? _localPort;

  int? get localPort => _localPort;
  bool get isConnected => _client != null;

  Future<void> connect({
    required String host,
    required int sshPort,
    required String username,
    required String password,
    int remotePort = 5000,
  }) async {
    final socket = await SSHSocket.connect(host, sshPort);
    _client = SSHClient(
      socket,
      username: username,
      onPasswordRequest: () => password,
    );

    // Bind a local TCP server on a random free port
    _localServer = await ServerSocket.bind('127.0.0.1', 0);
    _localPort = _localServer!.port;

    // Each incoming local connection gets forwarded through the SSH tunnel
    _localServer!.listen((localSocket) async {
      try {
        final channel = await _client!.forwardLocal('127.0.0.1', remotePort);
        _pipe(localSocket, channel);
      } catch (_) {
        localSocket.close();
      }
    });
  }

  void _pipe(Socket local, SSHForwardChannel remote) {
    // local → remote
    local.listen(
      (Uint8List data) => remote.sink.add(data),
      onDone: () => remote.sink.close(),
      onError: (_) => remote.sink.close(),
      cancelOnError: true,
    );
    // remote → local
    remote.stream.listen(
      (Uint8List data) => local.add(data),
      onDone: () => local.close(),
      onError: (_) => local.close(),
      cancelOnError: true,
    );
  }

  Future<void> disconnect() async {
    await _localServer?.close();
    _localServer = null;
    _client?.close();
    _client = null;
    _localPort = null;
  }
}
