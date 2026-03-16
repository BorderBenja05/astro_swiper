import 'dart:typed_data';
import 'package:flutter/foundation.dart';

enum ConnectionStatus { disconnected, connecting, connected, error }

class AppState extends ChangeNotifier {
  ConnectionStatus _status = ConnectionStatus.disconnected;
  String _errorMessage = '';

  // Keybinds: [[key, label], ...] — classification keys only (back filtered out)
  List<List<String>> _keybinds = [];
  String _backKey = 'left'; // key that triggers undo

  Uint8List? _image;
  String _filename = '';
  String _progress = '';
  bool _isLoading = false;
  bool _isDone = false;

  // --- Getters ---
  ConnectionStatus get status => _status;
  String get errorMessage => _errorMessage;
  List<List<String>> get keybinds => _keybinds;
  String get backKey => _backKey;
  Uint8List? get image => _image;
  String get filename => _filename;
  String get progress => _progress;
  bool get isLoading => _isLoading;
  bool get isDone => _isDone;

  // --- Setters ---

  void setConnecting() {
    _status = ConnectionStatus.connecting;
    _errorMessage = '';
    notifyListeners();
  }

  void setConnected() {
    _status = ConnectionStatus.connected;
    notifyListeners();
  }

  void setError(String message) {
    _status = ConnectionStatus.error;
    _errorMessage = message;
    notifyListeners();
  }

  void setDisconnected() {
    _status = ConnectionStatus.disconnected;
    _image = null;
    _keybinds = [];
    _isDone = false;
    _isLoading = false;
    notifyListeners();
  }

  /// Parse keybinds from the server's `keybinds` event.
  /// Server sends [[key, label], ...]; back button always has label 'back'.
  void setKeybinds(List<dynamic> raw) {
    _keybinds = [];
    for (final kb in raw) {
      final key = kb[0].toString();
      final label = kb[1].toString();
      if (label == 'back') {
        _backKey = key;
      } else {
        _keybinds.add([key, label]);
      }
    }
    notifyListeners();
  }

  void setLoading() {
    _isLoading = true;
    notifyListeners();
  }

  void setImage(Uint8List bytes, String filename, String progress) {
    _image = bytes;
    _filename = filename;
    _progress = progress;
    _isLoading = false;
    _isDone = false;
    notifyListeners();
  }

  void setDone() {
    _isDone = true;
    _isLoading = false;
    notifyListeners();
  }
}
