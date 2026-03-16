"""Tests for astro_swiper/web.py — AstroSwiper Flask app and SocketIO events."""

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from astro_swiper.web import AstroSwiper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def empty_loader(d):
    return []


def make_app(tmp_path, extra_cfg=None, triplet_loader=empty_loader):
    cfg = {
        'keybinds': {'r': 'real', 'b': 'bogus'},
        'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
    }
    if extra_cfg:
        cfg.update(extra_cfg)
    return AstroSwiper(cfg, triplet_loader=triplet_loader)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestAstroSwiperInit:
    def test_init_with_dict_config(self, tmp_path):
        app = make_app(tmp_path)
        assert app._port == 5000

    def test_init_with_yaml_file(self, tmp_path):
        cfg = {
            'keybinds': {'r': 'real'},
            'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
        }
        yaml_path = tmp_path / 'config.yaml'
        yaml_path.write_text(yaml.dump(cfg))
        app = AstroSwiper(str(yaml_path), triplet_loader=empty_loader)
        assert app._port == 5000

    def test_custom_port(self, tmp_path):
        app = make_app(tmp_path, extra_cfg={'port': 8080})
        assert app._port == 8080

    def test_no_input_dir_and_no_loader_raises(self, tmp_path):
        cfg = {
            'keybinds': {'r': 'real'},
            'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
        }
        with pytest.raises(ValueError, match="input_dir"):
            AstroSwiper(cfg)

    def test_keybinds_coerced_to_strings(self, tmp_path):
        cfg = {
            'keybinds': {1: 2},  # int keys/values
            'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
        }
        app = AstroSwiper(cfg, triplet_loader=empty_loader)
        assert all(isinstance(k, str) for k in app._classifier.keybinds)
        assert all(isinstance(v, str) for v in app._classifier.keybinds.values())

    def test_flask_app_created(self, tmp_path):
        from flask import Flask
        app = make_app(tmp_path)
        assert isinstance(app._app, Flask)

    def test_classifier_created(self, tmp_path):
        from astro_swiper.classifier import TripletClassifier
        app = make_app(tmp_path)
        assert isinstance(app._classifier, TripletClassifier)

    def test_default_back_button(self, tmp_path):
        app = make_app(tmp_path)
        assert app._classifier.back_button == 'left'

    def test_custom_back_button(self, tmp_path):
        app = make_app(tmp_path, extra_cfg={'back_button': 'q'})
        assert app._classifier.back_button == 'q'

    def test_resume_default_true(self, tmp_path):
        app = make_app(tmp_path)
        assert app._classifier.resume is True

    def test_triplet_loader_called(self, tmp_path):
        loader = MagicMock(return_value=[])
        make_app(tmp_path, extra_cfg={'input_dir': str(tmp_path)}, triplet_loader=loader)
        loader.assert_called_once()


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

class TestHTTPRoutes:
    @pytest.fixture
    def client(self, tmp_path):
        app = make_app(tmp_path)
        app._app.config['TESTING'] = True
        return app._app.test_client()

    def test_index_returns_200(self, client):
        response = client.get('/')
        assert response.status_code == 200

    def test_index_returns_html(self, client):
        response = client.get('/')
        assert b'<!DOCTYPE html>' in response.data or b'<html' in response.data

    def test_index_contains_title(self, client):
        response = client.get('/')
        assert b'Astro Swiper' in response.data

    def test_index_includes_socketio_script(self, client):
        response = client.get('/')
        assert b'socket.io' in response.data

    def test_index_shows_keybind_hint(self, client):
        response = client.get('/')
        # The hint text about shift+arrows should be present
        assert b'shift' in response.data.lower() or b'Shift' in response.data

    def test_background_route_returns_png(self, client):
        response = client.get('/background')
        assert response.status_code == 200
        assert response.content_type == 'image/png'

    def test_background_route_returns_bytes(self, client):
        response = client.get('/background')
        assert len(response.data) > 0


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------

class TestSocketIOEvents:
    @pytest.fixture
    def sio_client(self, tmp_path):
        from flask_socketio import SocketIOTestClient
        app_obj = make_app(tmp_path)
        # Patch send_current so it doesn't try to render images
        with patch.object(app_obj._classifier, 'send_current'):
            client = SocketIOTestClient(app_obj._app, app_obj._sio)
            yield client, app_obj

    def test_client_connects_successfully(self, sio_client):
        client, _ = sio_client
        assert client.is_connected()

    def test_connect_emits_keybinds_event(self, sio_client):
        client, _ = sio_client
        received = client.get_received()
        event_names = [msg['name'] for msg in received]
        assert 'keybinds' in event_names

    def test_keybinds_event_contains_keybind_list(self, sio_client):
        client, app_obj = sio_client
        received = client.get_received()
        keybinds_event = next(m for m in received if m['name'] == 'keybinds')
        kb_list = keybinds_event['args'][0]
        assert isinstance(kb_list, list)
        assert len(kb_list) >= 1

    def test_keybinds_event_includes_back_button(self, sio_client):
        client, app_obj = sio_client
        received = client.get_received()
        keybinds_event = next(m for m in received if m['name'] == 'keybinds')
        kb_list = keybinds_event['args'][0]
        keys = [item[0] for item in kb_list]
        assert app_obj._classifier.back_button in keys

    def test_keypress_event_calls_handle_key(self, tmp_path):
        from flask_socketio import SocketIOTestClient
        app_obj = make_app(tmp_path)
        with patch.object(app_obj._classifier, 'send_current'):
            with patch.object(app_obj._classifier, 'handle_key') as mock_handle:
                client = SocketIOTestClient(app_obj._app, app_obj._sio)
                client.emit('keypress', {'key': 'r'})
                time.sleep(0.1)
        mock_handle.assert_called_with('r')

    def test_keypress_empty_key(self, tmp_path):
        from flask_socketio import SocketIOTestClient
        app_obj = make_app(tmp_path)
        with patch.object(app_obj._classifier, 'send_current'):
            with patch.object(app_obj._classifier, 'handle_key') as mock_handle:
                client = SocketIOTestClient(app_obj._app, app_obj._sio)
                client.emit('keypress', {})
                time.sleep(0.1)
        # Missing 'key' field defaults to empty string
        mock_handle.assert_called_with('')

    def test_connect_calls_send_current(self, tmp_path):
        from flask_socketio import SocketIOTestClient
        app_obj = make_app(tmp_path)
        with patch.object(app_obj._classifier, 'send_current') as mock_send:
            client = SocketIOTestClient(app_obj._app, app_obj._sio)
            time.sleep(0.2)
        mock_send.assert_called()
