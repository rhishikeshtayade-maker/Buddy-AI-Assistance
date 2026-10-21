"""Unit tests for BUDDY Desktop Settings and Persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from app.desktop.settings import (
    AnimationIntensity,
    DesktopSettings,
    HudPosition,
    SettingsStore,
)


class TestDesktopSettings(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "test_settings.json"
        self.store = SettingsStore(self.settings_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_settings(self) -> None:
        settings = DesktopSettings()
        self.assertFalse(settings.start_at_login, "start_at_login must be False by default")
        self.assertEqual(settings.animation_intensity, AnimationIntensity.FULL)
        self.assertAlmostEqual(settings.hud_opacity, 0.92)
        self.assertEqual(settings.hud_position, HudPosition.BOTTOM_RIGHT)
        self.assertTrue(settings.sound_enabled)
        self.assertTrue(settings.listen_on_startup)
        self.assertFalse(settings.start_minimized_to_tray)
        self.assertFalse(settings.force_opaque)

    def test_save_and_load(self) -> None:
        custom = DesktopSettings(
            animation_intensity=AnimationIntensity.REDUCED,
            hud_opacity=0.75,
            hud_position=HudPosition.TOP_CENTER,
            sound_enabled=False,
            start_at_login=True,
            force_opaque=True,
        )
        self.store.save(custom)

        loaded = self.store.load()
        self.assertEqual(loaded.animation_intensity, AnimationIntensity.REDUCED)
        self.assertAlmostEqual(loaded.hud_opacity, 0.75)
        self.assertEqual(loaded.hud_position, HudPosition.TOP_CENTER)
        self.assertFalse(loaded.sound_enabled)
        self.assertTrue(loaded.start_at_login)
        self.assertTrue(loaded.force_opaque)

    def test_corrupt_file_recovery(self) -> None:
        self.settings_path.write_text("{invalid json corrupt", encoding="utf-8")
        loaded = self.store.load()
        # Falls back cleanly to safe defaults
        self.assertEqual(loaded.animation_intensity, AnimationIntensity.FULL)
        self.assertFalse(loaded.start_at_login)

    def test_opacity_bounds(self) -> None:
        with self.assertRaises(Exception):
            DesktopSettings(hud_opacity=1.5)
        with self.assertRaises(Exception):
            DesktopSettings(hud_opacity=0.1)
