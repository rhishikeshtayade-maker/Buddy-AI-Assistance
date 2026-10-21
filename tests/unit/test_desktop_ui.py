"""Unit tests for PySide6 Desktop UI components (HUD, Orb, Waveform, Settings)."""

import os
import sys
import unittest

# Ensure offscreen platform for deterministic CI / headless execution
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.desktop.bridge import UiUpdate, VisualState
from app.desktop.settings import AnimationIntensity, DesktopSettings, HudPosition
from app.desktop.startup import InMemoryRunKeyBackend, LoginStartupManager
from app.desktop.ui.hud import GlassHudWindow
from app.desktop.ui.orb import AnimatedOrbWidget
from app.desktop.ui.settings_dialog import SettingsDialog
from app.desktop.ui.tray import BuddySystemTray, create_tray_icon
from app.desktop.ui.waveform import WaveformWidget


class TestDesktopUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self) -> None:
        self.settings = DesktopSettings(
            animation_intensity=AnimationIntensity.FULL,
            hud_opacity=0.9,
            hud_position=HudPosition.BOTTOM_RIGHT,
        )

    def test_hud_window_instantiation_and_components(self) -> None:
        hud = GlassHudWindow(self.settings)
        self.assertIsNotNone(hud._orb)
        self.assertIsNotNone(hud._waveform)
        self.assertIsNotNone(hud._mic_chip)
        self.assertIsNotNone(hud._status_label)

        # Repositioning
        hud.reposition(HudPosition.TOP_RIGHT)
        self.assertTrue(hud.x() >= 0)
        self.assertTrue(hud.y() >= 0)

        # Apply UiUpdate
        update = UiUpdate(
            visual_state=VisualState.LISTENING,
            core_state="LISTENING",
            status_text="Listening for command...",
            mic_active=True,
            audio_level=0.5,
            last_transcript="hello",
        )
        hud._apply_ui_update(update)

        self.assertEqual(hud._orb._visual_state, VisualState.LISTENING)
        self.assertEqual(hud._waveform._visual_state, VisualState.LISTENING)
        self.assertEqual(hud._status_label.text(), "Listening for command...")
        self.assertEqual(hud._mic_chip.text(), "LISTENING")

        # Test expand / collapse
        self.assertFalse(hud._is_expanded)
        hud.toggle_expanded_mode()
        self.assertTrue(hud._is_expanded)
        hud.toggle_expanded_mode()
        self.assertFalse(hud._is_expanded)

    def test_animated_orb_intensity_modes(self) -> None:
        orb = AnimatedOrbWidget(intensity=AnimationIntensity.FULL)
        self.assertTrue(orb._timer.isActive())

        orb.set_intensity(AnimationIntensity.REDUCED)
        self.assertTrue(orb._timer.isActive())
        self.assertEqual(orb._timer.interval(), 83)

        orb.set_intensity(AnimationIntensity.OFF)
        self.assertFalse(orb._timer.isActive())

    def test_waveform_widget_audio_levels(self) -> None:
        wave = WaveformWidget(intensity=AnimationIntensity.FULL)
        wave.set_visual_state(VisualState.LISTENING)
        wave.set_audio_level(0.8)

        self.assertGreater(max(wave._target_bars), 0.1)

    def test_settings_dialog_save(self) -> None:
        backend = InMemoryRunKeyBackend()
        startup_mgr = LoginStartupManager(backend=backend)
        saved_holder = []

        dialog = SettingsDialog(
            settings=self.settings,
            on_save=saved_holder.append,
            startup_manager=startup_mgr,
        )

        # Toggle startup
        dialog._startup_check.setChecked(True)
        dialog._intensity_combo.setCurrentIndex(1)  # REDUCED
        dialog._opacity_slider.setValue(80)

        dialog._handle_save()

        self.assertEqual(len(saved_holder), 1)
        saved = saved_holder[0]
        self.assertTrue(saved.start_at_login)
        self.assertEqual(saved.animation_intensity, AnimationIntensity.REDUCED)
        self.assertAlmostEqual(saved.hud_opacity, 0.8)
        self.assertTrue(startup_mgr.is_enabled())

    def test_tray_icon_and_actions(self) -> None:
        icon_active = create_tray_icon(active=True, paused=False)
        self.assertFalse(icon_active.isNull())

        icon_paused = create_tray_icon(active=False, paused=True)
        self.assertFalse(icon_paused.isNull())

        toggle_calls = []
        pause_calls = []
        tray = BuddySystemTray(
            on_toggle_show=lambda: toggle_calls.append(True),
            on_pause_resume=lambda: pause_calls.append(True),
        )

        tray._handle_toggle_show()
        self.assertEqual(len(toggle_calls), 1)

        tray._handle_pause_resume()
        self.assertEqual(len(pause_calls), 1)
