"""Tests for astro_swiper/_cli.py — CLI entry point."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from astro_swiper._cli import main, DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# DEFAULT_CONFIG
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_config_path_exists(self):
        assert DEFAULT_CONFIG.exists(), f"Default config not found at {DEFAULT_CONFIG}"

    def test_default_config_is_yaml(self):
        content = DEFAULT_CONFIG.read_text()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    def test_default_config_has_keybinds(self):
        parsed = yaml.safe_load(DEFAULT_CONFIG.read_text())
        assert 'keybinds' in parsed


# ---------------------------------------------------------------------------
# --print-config flag
# ---------------------------------------------------------------------------

class TestPrintConfig:
    def test_print_config_exits_zero(self, capsys):
        with patch('sys.argv', ['asswiper', '--print-config']):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0

    def test_print_config_outputs_path(self, capsys):
        with patch('sys.argv', ['asswiper', '--print-config']):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out.strip()
        assert out != ''
        # Output should look like a path
        assert Path(out).suffix in ('.yaml', '.yml') or 'config' in out.lower()


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------

class TestConfigLoading:
    def test_missing_config_raises(self, tmp_path):
        with patch('sys.argv', ['asswiper', '-config', str(tmp_path / 'nope.yaml')]):
            with pytest.raises((SystemExit, FileNotFoundError, OSError)):
                main()

    def test_loads_config_and_runs(self, tmp_path):
        cfg = {
            'keybinds': {'r': 'real'},
            'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
        }
        config_path = tmp_path / 'config.yaml'
        config_path.write_text(yaml.dump(cfg))

        mock_app = MagicMock()
        with patch('sys.argv', ['asswiper', '-config', str(config_path)]):
            with patch('astro_swiper._cli.AstroSwiper', return_value=mock_app) as MockApp:
                main()
        MockApp.assert_called_once()
        mock_app.run.assert_called_once()

    def test_input_dir_arg_overrides_config(self, tmp_path):
        cfg = {
            'input_dir': '/original/dir',
            'keybinds': {'r': 'real'},
            'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
        }
        config_path = tmp_path / 'config.yaml'
        config_path.write_text(yaml.dump(cfg))
        override_dir = str(tmp_path / 'override')

        mock_app = MagicMock()
        with patch('sys.argv', ['asswiper', override_dir, '-config', str(config_path)]):
            with patch('astro_swiper._cli.AstroSwiper', return_value=mock_app) as MockApp:
                main()

        passed_cfg = MockApp.call_args[0][0]
        # input_dir should have been overridden (resolved to absolute path)
        assert passed_cfg['input_dir'] != '/original/dir'
        assert 'override' in passed_cfg['input_dir']

    def test_no_input_dir_arg_keeps_config_value(self, tmp_path):
        cfg = {
            'input_dir': '/from/config',
            'keybinds': {'r': 'real'},
            'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')},
        }
        config_path = tmp_path / 'config.yaml'
        config_path.write_text(yaml.dump(cfg))

        mock_app = MagicMock()
        with patch('sys.argv', ['asswiper', '-config', str(config_path)]):
            with patch('astro_swiper._cli.AstroSwiper', return_value=mock_app) as MockApp:
                main()

        passed_cfg = MockApp.call_args[0][0]
        assert passed_cfg.get('input_dir') == '/from/config'
