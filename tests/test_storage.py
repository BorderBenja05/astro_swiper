"""Tests for astro_swiper/storage.py — all three backends and the factory."""

import os
import pytest
from pathlib import Path

from astro_swiper.storage import (
    SQLiteBackend, CSVBackend, TxtBackend, make_backend
)


# ---------------------------------------------------------------------------
# SQLiteBackend
# ---------------------------------------------------------------------------

class TestSQLiteBackend:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.backend = SQLiteBackend(str(tmp_path / 'test.db'))
        yield
        self.backend.close()

    def test_get_classified_empty(self):
        assert self.backend.get_classified() == set()

    def test_save_and_get_classified(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        assert self.backend.get_classified() == {'sci1'}

    def test_save_multiple(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        assert self.backend.get_classified() == {'sci1', 'sci2'}

    def test_save_replace_on_duplicate_sci(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub1_new', 'sci1', 'ref1_new', 'b', 'bogus')
        assert len(self.backend.get_classified()) == 1

    def test_undo_empty_returns_none(self):
        assert self.backend.undo() is None

    def test_undo_returns_last_sci_path(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        result = self.backend.undo()
        assert result == 'sci1'

    def test_undo_removes_last_entry(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        result = self.backend.undo()
        assert result == 'sci2'
        assert self.backend.get_classified() == {'sci1'}

    def test_undo_respects_insertion_order(self):
        for i in range(5):
            self.backend.save(f'sub{i}', f'sci{i}', f'ref{i}', 'r', 'real')
        result = self.backend.undo()
        assert result == 'sci4'

    def test_clear_empties_table(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.clear()
        assert self.backend.get_classified() == set()

    def test_creates_parent_directories(self, tmp_path):
        nested = str(tmp_path / 'a' / 'b' / 'c' / 'test.db')
        backend = SQLiteBackend(nested)
        backend.close()
        assert Path(nested).exists()


# ---------------------------------------------------------------------------
# CSVBackend
# ---------------------------------------------------------------------------

class TestCSVBackend:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.csv_path = tmp_path / 'test.csv'
        self.backend = CSVBackend(str(self.csv_path))

    def test_creates_csv_with_header(self):
        content = self.csv_path.read_text()
        assert 'sub_path' in content
        assert 'sci_path' in content
        assert 'ref_path' in content
        assert 'label' in content

    def test_get_classified_empty(self):
        assert self.backend.get_classified() == set()

    def test_save_and_get_classified(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        assert self.backend.get_classified() == {'sci1'}

    def test_save_multiple(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        assert self.backend.get_classified() == {'sci1', 'sci2'}

    def test_undo_empty_returns_none(self):
        assert self.backend.undo() is None

    def test_undo_returns_last_sci_path(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        result = self.backend.undo()
        assert result == 'sci1'
        assert self.backend.get_classified() == set()

    def test_undo_removes_last_row(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        result = self.backend.undo()
        assert result == 'sci2'
        assert self.backend.get_classified() == {'sci1'}

    def test_clear_resets_to_header_only(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.clear()
        assert self.backend.get_classified() == set()
        # Header must still be present
        content = self.csv_path.read_text()
        assert 'sub_path' in content

    def test_creates_parent_directories(self, tmp_path):
        nested = str(tmp_path / 'x' / 'y' / 'test.csv')
        backend = CSVBackend(nested)
        assert Path(nested).exists()

    def test_existing_file_not_overwritten(self, tmp_path):
        """Opening an existing CSV should not reset it."""
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        # Re-open same file
        backend2 = CSVBackend(str(self.csv_path))
        assert backend2.get_classified() == {'sci1'}


# ---------------------------------------------------------------------------
# TxtBackend
# ---------------------------------------------------------------------------

class TestTxtBackend:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.keybinds = {
            'r': str(tmp_path / 'real.txt'),
            'b': str(tmp_path / 'bogus.txt'),
        }
        self.ac_path = str(tmp_path / 'already_classified.txt')
        self.backend = TxtBackend(self.keybinds, self.ac_path)

    def test_creates_already_classified_file(self):
        assert Path(self.ac_path).exists()

    def test_get_classified_empty(self):
        assert self.backend.get_classified() == set()

    def test_save_and_get_classified(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        assert self.backend.get_classified() == {'sci1'}

    def test_save_writes_triplet_to_keybind_file(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        content = Path(self.keybinds['r']).read_text()
        assert 'sub1' in content
        assert 'sci1' in content
        assert 'ref1' in content

    def test_save_appends_sci_and_key_to_ac_file(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        lines = Path(self.ac_path).read_text().splitlines()
        assert 'sci1' in lines
        assert 'r' in lines

    def test_save_multiple(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        assert self.backend.get_classified() == {'sci1', 'sci2'}

    def test_undo_empty_returns_none(self):
        assert self.backend.undo() is None

    def test_undo_returns_last_sci_path(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        result = self.backend.undo()
        assert result == 'sci1'
        assert self.backend.get_classified() == set()

    def test_undo_removes_triplet_from_keybind_file(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'r', 'real')
        self.backend.undo()
        content = Path(self.keybinds['r']).read_text()
        assert 'sci2' not in content
        assert 'sci1' in content

    def test_undo_multiple_entries(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        result = self.backend.undo()
        assert result == 'sci2'
        assert 'sci2' not in self.backend.get_classified()
        assert 'sci1' in self.backend.get_classified()

    def test_clear_empties_all_files(self):
        self.backend.save('sub1', 'sci1', 'ref1', 'r', 'real')
        self.backend.save('sub2', 'sci2', 'ref2', 'b', 'bogus')
        self.backend.clear()
        assert self.backend.get_classified() == set()
        assert Path(self.keybinds['r']).read_text() == ''
        assert Path(self.keybinds['b']).read_text() == ''


# ---------------------------------------------------------------------------
# make_backend factory
# ---------------------------------------------------------------------------

class TestMakeBackend:
    def test_sqlite_backend(self, tmp_path):
        cfg = {'storage': {'backend': 'sqlite', 'db': str(tmp_path / 'test.db')}}
        backend = make_backend(cfg, {})
        assert isinstance(backend, SQLiteBackend)
        backend.close()

    def test_csv_backend(self, tmp_path):
        cfg = {'storage': {'backend': 'csv', 'file': str(tmp_path / 'test.csv')}}
        backend = make_backend(cfg, {})
        assert isinstance(backend, CSVBackend)

    def test_txt_backend(self, tmp_path):
        keybinds = {'r': str(tmp_path / 'real.txt')}
        cfg = {
            'storage': {
                'backend': 'txt',
                'already_classified': str(tmp_path / 'ac.txt'),
            }
        }
        backend = make_backend(cfg, keybinds)
        assert isinstance(backend, TxtBackend)

    def test_default_empty_config_uses_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        backend = make_backend({}, {})
        assert isinstance(backend, SQLiteBackend)
        backend.close()

    def test_unknown_backend_raises_value_error(self):
        cfg = {'storage': {'backend': 'unknown'}}
        with pytest.raises(ValueError, match="Unknown storage backend"):
            make_backend(cfg, {})

    def test_case_insensitive_backend_name(self, tmp_path):
        cfg = {'storage': {'backend': 'SQLite', 'db': str(tmp_path / 'test.db')}}
        backend = make_backend(cfg, {})
        assert isinstance(backend, SQLiteBackend)
        backend.close()
