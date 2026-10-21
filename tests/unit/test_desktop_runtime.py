"""Unit tests for DesktopRuntime persistent lifecycle, pause/resume, and safe exit."""

import asyncio
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import BuddyConfig, BuddyState
from app.desktop.bridge import UiUpdate, VisualState
from app.desktop.runtime import DesktopRuntime
from app.desktop.settings import DesktopSettings, SettingsStore


class TestDesktopRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "settings.json"
        self.store = SettingsStore(self.settings_path)
        self.settings = DesktopSettings(sound_enabled=False, listen_on_startup=True)
        self.store.save(self.settings)

        self.config = BuddyConfig(
            app_env="testing",
            voice_enabled=True,
            stt_provider="mock",
            tts_provider="mock",
            ai_provider="mock",
        )

        self.updates: list[UiUpdate] = []

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runtime_start_and_shutdown(self) -> None:
        inst_name = f"test-inst-{uuid.uuid4().hex[:8]}"
        runtime = DesktopRuntime(
            config=self.config,
            settings=self.settings,
            settings_store=self.store,
            on_ui_update=self.updates.append,
            use_mock_voice=True,
            instance_name=inst_name,
        )

        started = runtime.start_background()
        self.assertTrue(started, "DesktopRuntime must start successfully")
        self.assertTrue(runtime.is_running)

        # Allow time for initial loop iteration
        time.sleep(0.3)
        self.assertTrue(len(self.updates) > 0)

        # Clean shutdown
        runtime.stop_and_join(timeout=4.0)
        self.assertFalse(runtime.is_running)
        self.assertEqual(runtime.state_machine.current_state, BuddyState.SHUTTING_DOWN)

    def test_pause_and_resume_listening(self) -> None:
        inst_name = f"test-inst-{uuid.uuid4().hex[:8]}"
        runtime = DesktopRuntime(
            config=self.config,
            settings=self.settings,
            settings_store=self.store,
            on_ui_update=self.updates.append,
            use_mock_voice=True,
            instance_name=inst_name,
        )

        runtime.start_background()
        time.sleep(0.2)

        # Pause listening
        runtime.pause_listening(reason="Unit test pause")
        time.sleep(0.2)
        self.assertTrue(runtime.is_paused)
        self.assertEqual(runtime.bridge.compute_visual_state(), VisualState.PAUSED)

        # Resume listening
        runtime.resume_listening(reason="Unit test resume")
        time.sleep(0.2)
        self.assertFalse(runtime.is_paused)
        self.assertIn(runtime.bridge.compute_visual_state(), (VisualState.IDLE, VisualState.LISTENING))

        runtime.stop_and_join(timeout=4.0)

    def test_single_instance_duplicate_rejection(self) -> None:
        shared_name = f"test-shared-{uuid.uuid4().hex[:8]}"
        runtime1 = DesktopRuntime(
            config=self.config,
            settings=self.settings,
            settings_store=self.store,
            on_ui_update=self.updates.append,
            use_mock_voice=True,
            instance_name=shared_name,
        )
        runtime2 = DesktopRuntime(
            config=self.config,
            settings=self.settings,
            settings_store=self.store,
            on_ui_update=self.updates.append,
            use_mock_voice=True,
            instance_name=shared_name,
        )

        try:
            started1 = runtime1.start_background()
            self.assertTrue(started1)

            # Second runtime should refuse to start
            started2 = runtime2.start_background()
            self.assertFalse(started2, "Second instance must be rejected by SingleInstanceGuard")
        finally:
            runtime1.stop_and_join(timeout=4.0)
            runtime2.stop_and_join(timeout=2.0)

    def test_submit_user_text_turn(self) -> None:
        inst_name = f"test-inst-{uuid.uuid4().hex[:8]}"
        runtime = DesktopRuntime(
            config=self.config,
            settings=self.settings,
            settings_store=self.store,
            on_ui_update=self.updates.append,
            use_mock_voice=True,
            instance_name=inst_name,
        )

        runtime.start_background()
        time.sleep(0.2)

        runtime.submit_user_text("what is the current time")
        time.sleep(0.5)

        # Verify turn processed and state returned safely to IDLE
        self.assertEqual(runtime.state_machine.current_state, BuddyState.IDLE)
        # Check that transcript was captured in update
        transcripts = [u.last_transcript for u in self.updates if u.last_transcript]
        self.assertIn("what is the current time", transcripts)

        runtime.stop_and_join(timeout=4.0)
