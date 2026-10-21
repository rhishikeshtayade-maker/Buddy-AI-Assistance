"""BUDDY Persistent Desktop Runtime.

Orchestrates the background asyncio event loop, persistent wake-word listener,
voice command execution, pause/resume lifecycle, orderly shutdown, and failure recovery.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Coroutine, Optional, Union

from app.ai.conversation import ConversationManager
from app.core import BuddyConfig, BuddyState, EventBus, HealthStatus, LifecycleManager, StateMachine
from app.desktop.audio_meter import MeteredAudioCapture
from app.desktop.bridge import RuntimeEventBridge, UiUpdate
from app.desktop.dispatch import dispatch_voice_intent, recover_state_to_idle
from app.desktop.settings import DesktopSettings, SettingsStore
from app.desktop.single_instance import SingleInstanceGuard
from app.memory import MemoryManager, MemoryPolicy, MemoryService, SqliteMemoryStore
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.voice import (
    AudioDeviceManager,
    EnergyVAD,
    KeywordWakeWordDetector,
    Pyttsx3TTSProvider,
    SoundDeviceAudioCapture,
    SpeechRecognitionSTTProvider,
    VoiceCommandRouter,
    VoiceIntent,
    VoiceIntentType,
    VoicePipeline,
)
from app.voice.capture import AudioCaptureInterface, MockAudioCapture
from app.voice.models import VoiceOutcome
from app.voice.stt import MockSTTProvider
from app.voice.tts import MockTTSProvider
from app.voice.vad import MockVAD
from app.voice.wake import MockWakeWordDetector

logger = logging.getLogger("buddy.desktop.runtime")


# Safeguard patterns for stopping/pausing listening
PAUSE_LISTENING_PATTERNS = {
    "stop listening",
    "pause listening",
    "stop listening buddy",
    "pause listening buddy",
    "hey buddy stop listening",
    "go to sleep",
    "mute microphone",
    "mute mic",
}

# Safeguard patterns for exit
EXIT_BUDDY_PATTERNS = {
    "exit buddy",
    "quit buddy",
    "shutdown buddy",
    "close buddy",
    "terminate buddy",
}


class DesktopRuntime:
    """Manages the persistent BUDDY background runtime and voice loop."""

    def __init__(
        self,
        config: Optional[BuddyConfig] = None,
        settings: Optional[DesktopSettings] = None,
        settings_store: Optional[SettingsStore] = None,
        on_ui_update: Optional[Callable[[UiUpdate], Any]] = None,
        confirm_callback: Optional[Callable[[str], Union[bool, Coroutine[Any, Any, bool]]]] = None,
        use_mock_voice: bool = False,
        instance_name: Optional[str] = None,
    ) -> None:
        self._config = config or BuddyConfig.load_from_env()
        self._settings_store = settings_store or SettingsStore()
        self._settings = settings or self._settings_store.load()
        self._use_mock_voice = use_mock_voice
        self._confirm_callback = confirm_callback

        # Single instance guard
        self._instance_guard = SingleInstanceGuard(name=instance_name or "BUDDY-Desktop-Assistant")

        # Core lifecycle manager
        self._lifecycle = LifecycleManager(self._config)
        self._event_bus = self._lifecycle.event_bus
        self._state_machine = self._lifecycle.state_machine

        # Event bridge to Qt GUI
        self._bridge = RuntimeEventBridge(self._event_bus, on_update=on_ui_update)

        # Threading and loop control
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_running = False
        self._stop_requested = threading.Event()
        self._loop_ready = threading.Event()

        # Voice components
        self._pipeline: Optional[VoicePipeline] = None
        self._metered_capture: Optional[MeteredAudioCapture] = None
        self._router = VoiceCommandRouter()
        self._tool_executor: Optional[ToolExecutor] = None
        self._memory_manager: Optional[MemoryManager] = None
        self._conv_manager: Optional[ConversationManager] = None
        self._mem_store: Optional[SqliteMemoryStore] = None

        # Pause & auto-resume state
        self._is_paused = not self._settings.listen_on_startup
        self._pause_lock = threading.Lock()
        self._resume_timer_task: Optional[asyncio.Task] = None
        self._active_turn_task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def bridge(self) -> RuntimeEventBridge:
        return self._bridge

    @property
    def settings(self) -> DesktopSettings:
        return self._settings

    @property
    def state_machine(self) -> StateMachine:
        return self._state_machine

    @property
    def pipeline(self) -> Optional[VoicePipeline]:
        return self._pipeline

    # -------------------------------------------------------------------------
    # Threading & Execution Controls
    # -------------------------------------------------------------------------

    def start_background(self) -> bool:
        """Start the runtime on a dedicated background thread."""
        if self._is_running:
            return True

        # Acquire single instance mutex
        if not self._instance_guard.acquire():
            logger.warning("Another BUDDY desktop instance is already active. Refusing to run duplicate.")
            return False

        self._stop_requested.clear()
        self._loop_ready.clear()

        self._thread = threading.Thread(
            target=self._thread_entry,
            name="BuddyDesktopRuntimeThread",
            daemon=True,
        )
        self._thread.start()

        # Wait for event loop to initialize (timeout 10s)
        ready = self._loop_ready.wait(timeout=10.0)
        return ready and self._is_running

    def _thread_entry(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._run_async())
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._is_running = False

    async def _run_async(self) -> None:
        """Async entry point running within the dedicated thread loop."""
        try:
            # 1. Initialize core lifecycle
            await self._lifecycle.initialize()
            health_report = await self._lifecycle.start()
            if health_report.status == HealthStatus.UNHEALTHY:
                logger.error("Core lifecycle startup reported UNHEALTHY: %s", health_report.checks)

            # 2. Setup subsystems (tools, memory, conversation, voice pipeline)
            await self._setup_subsystems()

            self._is_running = True
            self._loop_ready.set()

            # Set initial UI state
            self._bridge.set_mic_paused(self._is_paused)

            # Audible welcome announcement if sound enabled and not paused
            if self._settings.sound_enabled and not self._is_paused:
                try:
                    if self._pipeline:
                        await self._pipeline.speak("BUDDY desktop assistant is ready.")
                except Exception as e:
                    logger.debug("Startup welcome chime skipped: %s", e)

            # 3. Enter persistent voice listening loop
            await self._persistent_voice_loop()

        except asyncio.CancelledError:
            pass
        except Exception as err:
            logger.error("Fatal exception in DesktopRuntime: %s", err, exc_info=True)
            self._bridge.emit_update()
        finally:
            await self._cleanup()

    # -------------------------------------------------------------------------
    # Subsystem Wiring
    # -------------------------------------------------------------------------

    async def _setup_subsystems(self) -> None:
        # Tool executor
        self._tool_executor = self._lifecycle.service_registry.get("tool_executor", default=None)
        if self._tool_executor is None:
            tool_reg = ToolRegistry()
            register_builtin_tools(tool_reg)
            self._tool_executor = ToolExecutor(
                registry=tool_reg,
                event_bus=self._event_bus,
                default_timeout=self._config.tools_timeout,
            )

        # Memory manager
        try:
            mem_path = self._config.memory_database_path
            mem_path.parent.mkdir(parents=True, exist_ok=True)
            self._mem_store = SqliteMemoryStore(db_path=mem_path)
            mem_policy = MemoryPolicy(self._config)
            mem_service = MemoryService(
                store=self._mem_store,
                policy=mem_policy,
                event_bus=self._event_bus,
                config=self._config,
            )
            self._memory_manager = MemoryManager(service=mem_service, config=self._config)
        except Exception as e:
            logger.warning("Memory initialization warning: %s", e)
            self._memory_manager = None

        # Audio capture & Voice pipeline
        if self._use_mock_voice or self._config.stt_provider.lower() == "mock":
            base_capture: AudioCaptureInterface = MockAudioCapture()
            stt = MockSTTProvider(default_transcript="Hello BUDDY")
            tts = MockTTSProvider()
            vad = MockVAD()
            wake_detector = MockWakeWordDetector(wake_word=self._config.wake_word)
        else:
            base_capture = SoundDeviceAudioCapture(
                device_id=self._config.audio_input_device,
                sample_rate=self._config.audio_sample_rate,
                channels=self._config.audio_channels,
                chunk_ms=self._config.voice_audio_chunk_ms,
                max_queue_chunks=self._config.voice_audio_queue_size,
                persistent=True,
            )
            vad = EnergyVAD(
                energy_threshold=getattr(self._config, "vad_energy_threshold", 60.0),
                silence_timeout=self._config.vad_silence_timeout,
                sample_rate=self._config.audio_sample_rate,
            )
            stt = SpeechRecognitionSTTProvider()
            tts = Pyttsx3TTSProvider()
            wake_detector = KeywordWakeWordDetector(stt_provider=stt, wake_word=self._config.wake_word)

        # Metered tap for HUD waveform
        self._metered_capture = MeteredAudioCapture(base_capture)

        self._pipeline = VoicePipeline(
            config=self._config,
            event_bus=self._event_bus,
            state_machine=self._state_machine,
            capture=self._metered_capture,
            vad=vad,
            stt=stt,
            tts=tts,
            wake_word=wake_detector,
        )

        # Conversation manager
        self._conv_manager = ConversationManager(
            config=self._config,
            event_bus=self._event_bus,
            state_machine=self._state_machine,
            voice_pipeline=self._pipeline,
            tool_executor=self._tool_executor,
            memory_manager=self._memory_manager,
            auto_subscribe_voice=False,
        )

    # -------------------------------------------------------------------------
    # Persistent Background Voice Loop & Error Recovery
    # -------------------------------------------------------------------------

    async def _persistent_voice_loop(self) -> None:
        """Keeps wake-word listening operational across turns with failure recovery."""
        consecutive_failures = 0
        backoff_delay = 1.0

        while not self._stop_requested.is_set():
            try:
                # If listening is paused, sleep cooperatively until resumed
                if self._is_paused:
                    await asyncio.sleep(0.3)
                    continue

                # Invariant: Must be in IDLE state before starting wake detection
                if self._state_machine.current_state != BuddyState.IDLE:
                    recover_state_to_idle(self._state_machine, "Standby reset for wake detection")

                # Listen for wake word (e.g. "hey buddy") with a bounded timeout
                detected = await self._pipeline.listen_for_wake_word(timeout=5.0)

                if self._stop_requested.is_set() or self._is_paused:
                    continue

                if detected:
                    consecutive_failures = 0
                    backoff_delay = 1.0

                    # Acknowledge prompt
                    if self._settings.sound_enabled:
                        try:
                            await self._pipeline.speak("I'm listening.")
                        except Exception:
                            pass

                    # Command turn
                    await self._handle_active_turn()

                # Cooperative yield
                await asyncio.sleep(0.05)

            except asyncio.CancelledError:
                break
            except Exception as err:
                consecutive_failures += 1
                logger.warning(
                    "Voice loop recoverable failure (#%d): %s. Backing off for %.1fs...",
                    consecutive_failures,
                    err,
                    backoff_delay,
                )
                self._bridge.emit_update()

                # Ensure state machine returns to valid state
                recover_state_to_idle(self._state_machine, "Loop error recovery")

                await asyncio.sleep(backoff_delay)
                # Exponential backoff capped at 10.0 seconds
                backoff_delay = min(10.0, backoff_delay * 1.5)

    async def _handle_active_turn(self) -> None:
        """Perform a single command capture, routing, execution, and speech response."""
        try:
            listen_res = await self._pipeline.listen_with_diagnostics(timeout=7.0)

            if not listen_res.ok or not listen_res.transcript:
                logger.debug("Turn ended without transcription: %s", listen_res.outcome.value)
                return

            transcript = listen_res.transcript.strip()
            self._bridge.set_conversation_turn(transcript=transcript, response=None)

            # 1. Check for pause listening voice command
            transcript_lower = transcript.lower().rstrip(".!? ")
            if any(p in transcript_lower for p in PAUSE_LISTENING_PATTERNS):
                await self.pause_listening(reason="Voice command 'stop listening'")
                if self._settings.sound_enabled:
                    await self._pipeline.speak("I've stopped listening. Click resume or use the tray to wake me.")
                return

            # 2. Check for exit BUDDY voice command with spoken safeguard
            if any(p in transcript_lower for p in EXIT_BUDDY_PATTERNS):
                await self._handle_safeguarded_exit_turn()
                return

            # 3. Classify intent
            intent = self._router.classify(transcript)

            # 4. Dispatch with explicit confirmation callback and status reporting
            response_text = await dispatch_voice_intent(
                intent=intent,
                tool_executor=self._tool_executor,
                memory_manager=self._memory_manager,
                conv_manager=self._conv_manager,
                state_machine=self._state_machine,
                confirm=self._confirm_callback,
                on_status=self._bridge.set_action_status,
            )

            self._bridge.set_conversation_turn(transcript=transcript, response=response_text)

            # 5. Speak response with barge-in support
            if self._settings.sound_enabled:
                await self._pipeline.speak(response_text, interruptible=True, barge_in=True)

        finally:
            recover_state_to_idle(self._state_machine, "Turn finalized")
            self._bridge.emit_update()

    async def _handle_safeguarded_exit_turn(self) -> None:
        """Safeguard exit voice command: prompts for confirmation before exiting."""
        if self._settings.sound_enabled:
            await self._pipeline.speak("Are you sure you want to exit BUDDY? Say yes to confirm.")

        # Listen for brief confirmation
        confirm_res = await self._pipeline.listen_with_diagnostics(timeout=4.0)
        if confirm_res.ok and confirm_res.transcript:
            reply = confirm_res.transcript.strip().lower()
            if any(w in reply for w in ("yes", "confirm", "exit", "quit", "shut down")):
                if self._settings.sound_enabled:
                    await self._pipeline.speak("Shutting down BUDDY. Goodbye!")
                self.request_shutdown()
                return

        if self._settings.sound_enabled:
            await self._pipeline.speak("Exit cancelled.")

    # -------------------------------------------------------------------------
    # Public Controller Actions (Thread-safe from GUI / Tray)
    # -------------------------------------------------------------------------

    def pause_listening(self, reason: str = "User requested pause") -> None:
        """Pause listening and release the microphone device."""
        with self._pause_lock:
            self._is_paused = True

        logger.info("Listening PAUSED (%s). Releasing microphone stream.", reason)

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._async_pause_action)

    def _async_pause_action(self) -> None:
        if self._pipeline:
            self._pipeline.cancel_listening()
            # Release microphone capture
            if hasattr(self._pipeline.capture, "close"):
                asyncio.create_task(self._pipeline.capture.close())

        self._bridge.set_mic_paused(True)

        # Handle auto-resume if configured
        if self._settings.pause_auto_resume_minutes > 0:
            if self._resume_timer_task and not self._resume_timer_task.done():
                self._resume_timer_task.cancel()
            self._resume_timer_task = asyncio.create_task(self._auto_resume_timer())

    async def _auto_resume_timer(self) -> None:
        seconds = self._settings.pause_auto_resume_minutes * 60.0
        try:
            await asyncio.sleep(seconds)
            await self.resume_listening(reason="Auto-resume timer expired")
        except asyncio.CancelledError:
            pass

    def resume_listening(self, reason: str = "User requested resume") -> None:
        """Resume listening for wake word."""
        with self._pause_lock:
            self._is_paused = False

        logger.info("Listening RESUMED (%s).", reason)

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._async_resume_action)

    def _async_resume_action(self) -> None:
        if self._resume_timer_task and not self._resume_timer_task.done():
            self._resume_timer_task.cancel()

        self._bridge.set_mic_paused(False)

    def submit_user_text(self, text: str) -> None:
        """Inject user text directly into the processing pipeline (GUI chat / text input)."""
        if not text or not text.strip():
            return
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._execute_text_turn(text.strip()), self._loop)

    async def _execute_text_turn(self, text: str) -> None:
        """Execute a text-based user turn."""
        self._bridge.set_conversation_turn(transcript=text, response=None)
        try:
            intent = self._router.classify(text)
            response_text = await dispatch_voice_intent(
                intent=intent,
                tool_executor=self._tool_executor,
                memory_manager=self._memory_manager,
                conv_manager=self._conv_manager,
                state_machine=self._state_machine,
                confirm=self._confirm_callback,
                on_status=self._bridge.set_action_status,
            )
            self._bridge.set_conversation_turn(transcript=text, response=response_text)

            if self._settings.sound_enabled and self._pipeline:
                await self._pipeline.speak(response_text, interruptible=True)
        finally:
            recover_state_to_idle(self._state_machine, "Text turn finalized")
            self._bridge.emit_update()

    def update_settings(self, new_settings: DesktopSettings) -> None:
        """Apply and persist updated desktop settings."""
        self._settings = new_settings
        self._settings_store.save(new_settings)
        logger.info("Desktop settings updated and persisted.")

    def request_shutdown(self) -> None:
        """Signal the runtime thread to gracefully exit."""
        logger.info("Shutdown requested for DesktopRuntime.")
        self._stop_requested.set()
        if self._pipeline:
            self._pipeline.cancel_listening()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._async_stop_loop)

    def _async_stop_loop(self) -> None:
        # Stop any active speaking
        if self._pipeline:
            asyncio.create_task(self._pipeline.stop_speaking())

    def stop_and_join(self, timeout: float = 6.0) -> None:
        """Synchronously request shutdown, wait for thread exit, and release mutex."""
        self.request_shutdown()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._instance_guard.release()
        logger.info("DesktopRuntime stopped and resources released.")

    # -------------------------------------------------------------------------
    # Orderly Cleanup
    # -------------------------------------------------------------------------

    async def _cleanup(self) -> None:
        """Shutdown all services, close audio streams, and release devices."""
        logger.info("Executing DesktopRuntime orderly cleanup...")

        # 1. Cancel resume timer
        if self._resume_timer_task and not self._resume_timer_task.done():
            self._resume_timer_task.cancel()

        # 2. Stop audio pipeline and close capture
        if self._pipeline:
            try:
                await self._pipeline.stop_speaking()
            except Exception:
                pass
            if hasattr(self._pipeline.capture, "close"):
                try:
                    await self._pipeline.capture.close()
                except Exception as e:
                    logger.debug("Capture close exception: %s", e)

        # 3. Close SQLite memory store
        if self._mem_store:
            try:
                self._mem_store.close()
            except Exception as e:
                logger.debug("Memory store close exception: %s", e)

        # 4. Perform Core LifecycleManager shutdown
        try:
            await self._lifecycle.shutdown(reason="DesktopRuntime exit")
        except Exception as e:
            logger.warning("Lifecycle shutdown error: %s", e)

        # 5. Release single instance mutex
        self._instance_guard.release()
        self._is_running = False
        logger.info("Orderly cleanup completed.")
