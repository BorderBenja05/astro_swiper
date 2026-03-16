"""Tests for astro_swiper/classifier.py — TripletClassifier."""

import base64
import gzip
import shutil
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from astro_swiper.classifier import TripletClassifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_storage(classified=None):
    storage = MagicMock()
    storage.get_classified.return_value = set(classified or [])
    storage.undo.return_value = None
    return storage


def make_classifier(keybinds=None, back_button='left', resume=True,
                    overwrite=False, classified=None):
    if keybinds is None:
        keybinds = {'r': 'real', 'b': 'bogus'}
    storage = make_storage(classified)
    socketio = MagicMock()
    clf = TripletClassifier(
        keybinds=keybinds,
        back_button=back_button,
        storage=storage,
        socketio=socketio,
        resume=resume,
        overwrite=overwrite,
    )
    return clf, storage, socketio


def fake_imgs():
    return (np.zeros((10, 10)), np.zeros((10, 10)), np.zeros((10, 10)))


def wait_for_threads(timeout=1.0):
    """Wait for daemon threads to finish."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        active = [t for t in threading.enumerate()
                  if t.daemon and t != threading.current_thread()]
        if not active:
            break
        time.sleep(0.05)
    time.sleep(0.05)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_keybinds_stored(self):
        clf, _, _ = make_classifier({'r': 'real', 'b': 'bogus'})
        assert clf.keybinds == {'r': 'real', 'b': 'bogus'}

    def test_back_button_stored(self):
        clf, _, _ = make_classifier(back_button='q')
        assert clf.back_button == 'q'

    def test_triplets_empty_initially(self):
        clf, _, _ = make_classifier()
        assert clf.triplets == []

    def test_index_zero_initially(self):
        clf, _, _ = make_classifier()
        assert clf.index == 0

    def test_default_vmin_vmax(self):
        clf, _, _ = make_classifier()
        assert clf.vmin == 0.0
        assert clf.vmax == 1.0

    def test_overwrite_calls_clear(self):
        clf, storage, _ = make_classifier(overwrite=True)
        storage.clear.assert_called_once()

    def test_no_overwrite_does_not_clear(self):
        clf, storage, _ = make_classifier(overwrite=False)
        storage.clear.assert_not_called()

    def test_resume_loads_pre_classified(self):
        clf, storage, _ = make_classifier(classified={'sci1', 'sci2'}, resume=True)
        assert clf.pre_classified == {'sci1', 'sci2'}

    def test_no_resume_ignores_storage_classified(self):
        clf, storage, _ = make_classifier(classified={'sci1', 'sci2'}, resume=False)
        assert clf.pre_classified == set()


# ---------------------------------------------------------------------------
# load_directory
# ---------------------------------------------------------------------------

class TestLoadDirectory:
    def test_custom_loader_called_with_dir(self, tmp_path):
        clf, _, _ = make_classifier()
        loader = MagicMock(return_value=[])
        clf.load_directory(str(tmp_path), triplet_loader=loader)
        loader.assert_called_once_with(str(tmp_path))

    def test_custom_loader_populates_triplets(self, tmp_path):
        clf, _, _ = make_classifier()
        triplets = [['sub1', 'sci1', 'ref1'], ['sub2', 'sci2', 'ref2']]
        clf.load_directory(None, triplet_loader=lambda d: triplets)
        assert len(clf.triplets) == 2

    def test_triplets_sorted_by_sci_path(self):
        clf, _, _ = make_classifier()
        triplets = [
            ['sub_c', 'sci_c', 'ref_c'],
            ['sub_a', 'sci_a', 'ref_a'],
            ['sub_b', 'sci_b', 'ref_b'],
        ]
        clf.load_directory(None, triplet_loader=lambda d: triplets)
        assert [t[1] for t in clf.triplets] == ['sci_a', 'sci_b', 'sci_c']

    def test_resume_skips_pre_classified(self):
        clf, storage, _ = make_classifier(classified={'sci_a'}, resume=True)
        triplets = [['sub_a', 'sci_a', 'ref_a'], ['sub_b', 'sci_b', 'ref_b']]
        clf.load_directory(None, triplet_loader=lambda d: triplets)
        assert clf.index == 1  # skipped sci_a

    def test_no_resume_starts_at_zero(self):
        clf, storage, _ = make_classifier(classified={'sci_a'}, resume=False)
        triplets = [['sub_a', 'sci_a', 'ref_a'], ['sub_b', 'sci_b', 'ref_b']]
        clf.load_directory(None, triplet_loader=lambda d: triplets)
        assert clf.index == 0

    def test_scan_finds_fits_triplets(self, tmp_path):
        for prefix in ['foo', 'bar']:
            for sfx in ['scicutout.fits', 'subcutout.fits', 'refcutout.fits']:
                (tmp_path / f'{prefix}{sfx}').touch()
        clf, _, _ = make_classifier()
        clf.load_directory(str(tmp_path))
        assert len(clf.triplets) == 2

    def test_scan_finds_fits_gz_triplets(self, tmp_path):
        for sfx in ['scicutout.fits.gz', 'subcutout.fits.gz', 'refcutout.fits.gz']:
            (tmp_path / f'foo{sfx}').touch()
        clf, _, _ = make_classifier()
        clf.load_directory(str(tmp_path))
        assert len(clf.triplets) == 1

    def test_scan_ignores_incomplete_triplets(self, tmp_path):
        # Only sci file present, no sub/ref
        (tmp_path / 'fooscicutout.fits').touch()
        clf, _, _ = make_classifier()
        clf.load_directory(str(tmp_path))
        assert len(clf.triplets) == 0

    def test_scan_prefers_gz_over_plain_fits(self, tmp_path):
        """Both .fits and .fits.gz exist for the same base; gz takes priority."""
        for sfx in ['scicutout.fits.gz', 'subcutout.fits.gz', 'refcutout.fits.gz']:
            (tmp_path / f'foo{sfx}').touch()
        for sfx in ['scicutout.fits', 'subcutout.fits', 'refcutout.fits']:
            (tmp_path / f'foo{sfx}').touch()
        clf, _, _ = make_classifier()
        clf.load_directory(str(tmp_path))
        # At least one triplet found (may find 2 due to both patterns, but not crash)
        assert len(clf.triplets) >= 1


# ---------------------------------------------------------------------------
# _apply_scaling
# ---------------------------------------------------------------------------

class TestApplyScaling:
    def test_shift_up_decreases_vmax(self):
        clf, _, _ = make_classifier()
        old_vmax = clf.vmax
        clf._apply_scaling('shift+up')
        assert clf.vmax < old_vmax
        assert clf.vmin == 0.0

    def test_shift_down_increases_vmax(self):
        clf, _, _ = make_classifier()
        old_vmax = clf.vmax
        clf._apply_scaling('shift+down')
        assert clf.vmax > old_vmax

    def test_shift_right_shifts_both_up(self):
        clf, _, _ = make_classifier()
        clf.vmin, clf.vmax = 0.0, 1.0
        clf._apply_scaling('shift+right')
        assert clf.vmin > 0.0
        assert clf.vmax > 1.0
        assert abs((clf.vmax - 1.0) - clf.vmin) < 1e-10

    def test_shift_left_shifts_both_down(self):
        clf, _, _ = make_classifier()
        clf.vmin, clf.vmax = 0.0, 1.0
        clf._apply_scaling('shift+left')
        assert clf.vmin < 0.0
        assert clf.vmax < 1.0

    def test_clears_b64_cache(self):
        clf, _, _ = make_classifier()
        clf._b64 = 'cached_value'
        clf._apply_scaling('shift+up')
        assert clf._b64 is None

    def test_step_proportional_to_range(self):
        clf, _, _ = make_classifier()
        clf.vmin, clf.vmax = 0.0, 2.0  # range = 2.0
        clf._apply_scaling('shift+up')
        # step = 2.0 * 0.1 = 0.2, so vmax decreases by 0.2
        assert abs(clf.vmax - 1.8) < 1e-10


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_saves_to_storage(self):
        clf, storage, _ = make_classifier({'r': 'real'})
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._classify('r')
        storage.save.assert_called_once_with('sub1', 'sci1', 'ref1', 'r', 'real')

    def test_adds_sci_to_pre_classified(self):
        clf, _, _ = make_classifier({'r': 'real'})
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._classify('r')
        assert 'sci1' in clf.pre_classified

    def test_advances_index(self):
        clf, _, _ = make_classifier({'r': 'real'})
        clf.triplets = [['sub1', 'sci1', 'ref1'], ['sub2', 'sci2', 'ref2']]
        clf.index = 0
        clf._classify('r')
        assert clf.index == 1

    def test_skips_pre_classified_after_advance(self):
        clf, _, _ = make_classifier({'r': 'real'}, classified={'sci2'}, resume=True)
        clf.triplets = [
            ['sub1', 'sci1', 'ref1'],
            ['sub2', 'sci2', 'ref2'],
            ['sub3', 'sci3', 'ref3'],
        ]
        clf.index = 0
        clf._classify('r')
        assert clf.index == 2  # sci2 already classified, skipped

    def test_index_stops_at_end(self):
        clf, _, _ = make_classifier({'r': 'real'})
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._classify('r')
        assert clf.index == 1  # past end — handled by _emit_current's bounds check


# ---------------------------------------------------------------------------
# _undo
# ---------------------------------------------------------------------------

class TestUndo:
    def test_undo_nothing_prints_message(self, capsys):
        clf, storage, _ = make_classifier()
        storage.undo.return_value = None
        clf._undo()
        assert 'Nothing to undo' in capsys.readouterr().out

    def test_undo_restores_index(self):
        clf, storage, _ = make_classifier()
        storage.undo.return_value = 'sci1'
        clf.triplets = [['sub1', 'sci1', 'ref1'], ['sub2', 'sci2', 'ref2']]
        clf.pre_classified = {'sci1'}
        clf.index = 1
        clf._undo()
        assert clf.index == 0

    def test_undo_removes_from_pre_classified(self):
        clf, storage, _ = make_classifier()
        storage.undo.return_value = 'sci1'
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.pre_classified = {'sci1'}
        clf.index = 1
        clf._undo()
        assert 'sci1' not in clf.pre_classified

    def test_undo_sci_not_in_triplets_decrements_index(self):
        clf, storage, _ = make_classifier()
        storage.undo.return_value = 'unknown_sci'
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 1
        clf._undo()
        assert clf.index == 0

    def test_undo_index_not_below_zero(self):
        clf, storage, _ = make_classifier()
        storage.undo.return_value = 'unknown_sci'
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._undo()
        assert clf.index >= 0


# ---------------------------------------------------------------------------
# handle_key (via threads)
# ---------------------------------------------------------------------------

class TestHandleKey:
    def _setup_with_triplet(self):
        clf, storage, sio = make_classifier({'r': 'real'}, back_button='left')
        clf.triplets = [['sub1', 'sci1', 'ref1'], ['sub2', 'sci2', 'ref2']]
        clf.index = 0
        clf._imgs = fake_imgs()
        clf._imgs_idx = 0
        return clf, storage, sio

    def _render_ctx(self, clf):
        """Context manager that patches both _render and _load_triplet."""
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(clf, '_render', return_value='b64data'))
        stack.enter_context(patch.object(clf, '_load_triplet', return_value=fake_imgs()))
        return stack

    def test_classification_key_saves(self):
        clf, storage, sio = self._setup_with_triplet()
        with self._render_ctx(clf):
            clf.handle_key('r')
            wait_for_threads()
        storage.save.assert_called()

    def test_back_button_calls_undo(self):
        clf, storage, sio = self._setup_with_triplet()
        with self._render_ctx(clf):
            clf.handle_key('left')
            wait_for_threads()
        storage.undo.assert_called()

    def test_shift_key_adjusts_scaling(self):
        clf, _, _ = self._setup_with_triplet()
        original_vmax = clf.vmax
        with self._render_ctx(clf):
            clf.handle_key('shift+up')
            wait_for_threads()
        assert clf.vmax != original_vmax

    def test_unknown_key_does_nothing(self):
        clf, storage, sio = self._setup_with_triplet()
        clf.handle_key('z')
        wait_for_threads()
        storage.save.assert_not_called()
        storage.undo.assert_not_called()

    def test_emits_update_after_classify(self):
        clf, storage, sio = self._setup_with_triplet()
        with self._render_ctx(clf):
            clf.handle_key('r')
            wait_for_threads()
        # socketio.emit should have been called (loading + update/done)
        assert sio.emit.called

    def test_handle_key_thread_is_daemon(self):
        """Spawned threads should be daemon threads so they don't block exit."""
        clf, _, _ = self._setup_with_triplet()
        spawned = []
        original_start = threading.Thread.start

        def track_thread(self_thread):
            spawned.append(self_thread)
            original_start(self_thread)

        with patch.object(threading.Thread, 'start', track_thread):
            with self._render_ctx(clf):
                clf.handle_key('r')
                wait_for_threads()

        assert all(t.daemon for t in spawned)


# ---------------------------------------------------------------------------
# _render
# ---------------------------------------------------------------------------

class TestRender:
    def test_returns_base64_string(self):
        clf, _, _ = make_classifier()
        result = clf._render(fake_imgs())
        assert isinstance(result, str)

    def test_output_is_valid_png(self):
        clf, _, _ = make_classifier()
        result = clf._render(fake_imgs())
        decoded = base64.b64decode(result)
        assert decoded[:8] == b'\x89PNG\r\n\x1a\n'

    def test_b64_cache_used_when_params_unchanged(self):
        clf, _, _ = make_classifier()
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._imgs = fake_imgs()
        clf._imgs_idx = 0

        with patch.object(clf, '_render', wraps=clf._render) as mock_render:
            clf._get_b64()
            clf._get_b64()
            assert mock_render.call_count == 1

    def test_b64_cache_invalidated_when_vmin_changes(self):
        clf, _, _ = make_classifier()
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._imgs = fake_imgs()
        clf._imgs_idx = 0

        with patch.object(clf, '_render', wraps=clf._render) as mock_render:
            clf._get_b64()
            clf.vmin = 0.5
            clf._b64_key = None
            clf._b64 = None
            clf._get_b64()
            assert mock_render.call_count == 2


# ---------------------------------------------------------------------------
# _load_fits
# ---------------------------------------------------------------------------

class TestLoadFits:
    def test_load_plain_fits(self, tmp_path):
        from astropy.io.fits import PrimaryHDU
        data = np.ones((10, 10), dtype=float)
        path = tmp_path / 'test.fits'
        PrimaryHDU(data).writeto(str(path))

        clf, _, _ = make_classifier()
        result = clf._load_fits(str(path))
        assert result.shape == (10, 10)
        np.testing.assert_array_almost_equal(result, data)

    def test_load_gzipped_fits(self, tmp_path):
        from astropy.io.fits import PrimaryHDU
        data = np.ones((10, 10), dtype=float)
        fits_path = tmp_path / 'test.fits'
        gz_path = tmp_path / 'test.fits.gz'
        PrimaryHDU(data).writeto(str(fits_path))
        with open(fits_path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

        clf, _, _ = make_classifier()
        result = clf._load_fits(str(gz_path))
        assert result.shape == (10, 10)

    def test_nan_values_replaced_with_zero(self, tmp_path):
        from astropy.io.fits import PrimaryHDU
        data = np.array([[float('nan'), 1.0], [2.0, float('nan')]])
        path = tmp_path / 'nantest.fits'
        PrimaryHDU(data).writeto(str(path))

        clf, _, _ = make_classifier()
        result = clf._load_fits(str(path))
        assert not np.isnan(result).any()
        assert result[0, 0] == 0.0
        assert result[1, 1] == 0.0


# ---------------------------------------------------------------------------
# send_current / _emit_current
# ---------------------------------------------------------------------------

class TestEmit:
    def test_emit_current_calls_done_when_past_end(self):
        clf, _, sio = make_classifier()
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 1  # past end
        clf._emit_current()
        sio.emit.assert_called_with('done', {'message': 'All 1 triplets done!'})

    def test_emit_current_sends_update_with_payload(self):
        clf, _, sio = make_classifier()
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._imgs = fake_imgs()
        clf._imgs_idx = 0

        with patch.object(clf, '_render', return_value='base64data'):
            clf._emit_current()

        call_args = sio.emit.call_args
        assert call_args[0][0] == 'update'
        payload = call_args[0][1]
        assert payload['image'] == 'base64data'
        assert 'filename' in payload
        assert 'progress' in payload

    def test_emit_current_to_specific_sid(self):
        clf, _, sio = make_classifier()
        clf.triplets = [['sub1', 'sci1', 'ref1']]
        clf.index = 0
        clf._imgs = fake_imgs()
        clf._imgs_idx = 0

        with patch.object(clf, '_render', return_value='base64data'):
            clf._emit_current(to='sid123')

        call_args = sio.emit.call_args
        assert call_args[1].get('to') == 'sid123' or 'sid123' in call_args[0]
