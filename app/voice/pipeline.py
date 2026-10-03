"""BUDDY Voice Pipeline Orchestrator.

Coordinates AudioCapture, Voice Activity Detection (VAD), Speech-to-Text (STT),
Text-to-Speech (TTS), and Wake-Word Detection while integrating seamlessly
with BUDDY Core State Machine and EventBus.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.core import BuddyState, EventBus, StateMachine
from app.core.config import BuddyConfig
from app.voice.capture import AudioCaptureInterface, MockAudioCapture, SoundDeviceAudioCapture
from app.voice.device import AudioDeviceManager
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    SpeechSynthesisFailedEvent,
    VoiceCommandReceivedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
    VoiceRecognitionFailedEvent,
)
from app.voice.exceptions import AudioCaptureError, STTError, TTSError, VoiceError
from app.voice.models import AudioData, STTResult, VADState
from app.voice.stt import MockSTTProvider, SpeechRecognitionSTTProvider, SpeechToTextProvider
from app.voice.tts import MockTTSProvider, Pyttsx3TTSProvider, TextToSpeechProvider
from app.voice.vad import EnergyVAD, VoiceActivityDetectorInterface
from app.voice.wake import MockWakeWordDetector, WakeWordDetector

logger = logging.getLogger("buddy.voice.pipeline")


class VoicePipeline:
    """End-to-end voice pipeline managing audio capture, speech recognition, and speech synthesis."""

    def __init__(
        self,
        config: BuddyConfig,
        event_bus: EventBus,
        state_machine: StateMachine,
        capture: Optional[AudioCaptureInterface] = None,
        vad: Optional[VoiceActivityDetectorInterface] = None,
        stt: Optional[SpeechToTextProvider] = None,
        tts: Optional[TextToSpeechProvider] = None,
        wake_word: Optional[WakeWordDetector] = None,
        device_manager: Optional[AudioDeviceManager] = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._state_machine = state_machine
        self._device_manager = device_manager or AudioDeviceManager()

        # Initialize providers based on config or inject mock/explicit providers
        self._capture = capture or self._create_default_capture()
        self._vad = vad or EnergyVAD(
            silence_timeout=config.vad_silence_timeout,
            sample_rate=config.audio_sample_rate,
        )
        self._stt = stt or self._create_default_stt()
        self._tts = tts or self._create_default_tts()
        self._wake_word = wake_word or MockWakeWordDetector(wake_word=config.wake_word)

        self._is_active = False
        self._cancel_requested = False
        self._lock = asyncio.Lock()

        # Latency diagnostics baseline
        self.last_capture_latency: float = 0.0
        self.last_vad_latency: float = 0.0
        self.last_stt_latency: float = 0.0
        self.last_pipeline_latency: float = 0.0

    @property
    def capture(self) -> AudioCaptureInterface:
        return self._capture

    @property
    def vad(self) -> VoiceActivityDetectorInterface:
        return self._vad

    @property
    def stt(self) -> SpeechToTextProvider:
        return self._stt

    @property
    def tts(self) -> TextToSpeechProvider:
        return self._tts

    @property
    def wake_word_detector(self) -> WakeWordDetector:
        return self._wake_word

    @property
    def device_manager(self) -> AudioDeviceManager:
        return self._device_manager

    def _create_default_capture(self) -> AudioCaptureInterface:
        if self._config.stt_provider.lower() == "mock" or not self._config.voice_enabled:
            return MockAudioCapture(
                sample_rate=self._config.audio_sample_rate,
                channels=self._config.audio_channels,
            )
        try:
            return SoundDeviceAudioCapture(
                device_id=self._config.audio_input_device,
                sample_rate=self._config.audio_sample_rate,
                channels=self._config.audio_channels,
            )
        except Exception as e:
            logger.warning("Could not initialize hardware capture, falling back to mock: %s", e)
            return MockAudioCapture()

    def _create_default_stt(self) -> SpeechToTextProvider:
        if self._config.stt_provider.lower() == "mock":
            return MockSTTProvider()
        return SpeechRecognitionSTTProvider()

    def _create_default_tts(self) -> TextToSpeechProvider:
        if self._config.tts_provider.lower() == "mock":
            return MockTTSProvider()
        try:
            return Pyttsx3TTSProvider()
        except Exception as e:
            logger.warning("Could not initialize pyttsx3 TTS, falling back to mock: %s", e)
            return MockTTSProvider()

    async def listen_for_command(self, timeout: Optional[float] = None) -> Optional[STTResult]:
        """Capture a single user utterance using VAD, transcribe via STT, and update state.

        Expected State Flow:
        IDLE -> LISTENING -> (VAD speech + silence) -> THINKING -> STTResult
        """
        async with self._lock:
            start_pipeline_time = time.perf_counter()
            self._cancel_requested = False
            listen_timeout = timeout or self._config.voice_timeout

            # 1. State Transition: IDLE -> LISTENING
            if self._state_machine.can_transition_to(BuddyState.LISTENING):
                self._state_machine.transition_to(
                    BuddyState.LISTENING,
                    reason="Voice command capture initiated",
                )
            elif self._state_machine.current_state != BuddyState.LISTENING:
                logger.warning(
                    "Cannot start listening from state %s",
                    self._state_machine.current_state.value,
                )
                return None

            await self._event_bus.publish(
                VoiceListeningStartedEvent(
                    input_device=self._config.audio_input_device,
                    sample_rate=self._config.audio_sample_rate,
                )
            )

            # 2. Start Capture and VAD
            self._vad.reset()
            capture_start_time = time.perf_counter()
            try:
                await self._capture.start()
                self.last_capture_latency = time.perf_counter() - capture_start_time
            except Exception as err:
                logger.error("Audio capture failed to start: %s", err)
                await self._handle_recognition_failure(
                    "AudioCaptureError",
                    f"Microphone capture error: {err}",
                )
                return None

            # 3. Stream chunks into VAD until utterance completion or timeout
            vad_start_time = time.perf_counter()
            deadline = time.time() + listen_timeout

            try:
                while not self._cancel_requested:
                    if time.time() > deadline:
                        raise asyncio.TimeoutError(f"Listening timed out after {listen_timeout}s")

                    chunk = await self._capture.read_chunk(timeout=0.5)
                    vad_state = self._vad.process_chunk(chunk)

                    if vad_state == VADState.COMPLETED:
                        break

                    await asyncio.sleep(0.001)

                self.last_vad_latency = time.perf_counter() - vad_start_time

                if self._cancel_requested:
                    await self._capture.cancel()
                    await self._event_bus.publish(
                        VoiceListeningStoppedEvent(reason="Capture cancelled")
                    )
                    self._recover_to_idle("Listening cancelled")
                    return None

                # 4. Stop capture and retrieve AudioData
                audio = await self._capture.stop()
                await self._event_bus.publish(
                    VoiceListeningStoppedEvent(
                        reason="Utterance completed",
                        duration=audio.duration,
                    )
                )

                # 5. State Transition: LISTENING -> THINKING
                if self._state_machine.can_transition_to(BuddyState.THINKING):
                    self._state_machine.transition_to(
                        BuddyState.THINKING,
                        reason="Utterance captured; dispatching to STT",
                    )

                # 6. Transcribe via STT provider
                stt_start_time = time.perf_counter()
                stt_result = await self._stt.transcribe(audio)
                self.last_stt_latency = time.perf_counter() - stt_start_time
                self.last_pipeline_latency = time.perf_counter() - start_pipeline_time

                # 7. Privacy: Log transcript respecting privacy configuration
                if self._config.log_transcripts:
                    logger.debug("Transcribed speech: '%s' (conf=%.2f)", stt_result.transcript, stt_result.confidence or 0.0)
                else:
                    logger.debug("Transcribed speech received (length=%d chars, duration=%.2fs)", len(stt_result.transcript), audio.duration)

                # 8. Publish VoiceCommandReceivedEvent
                await self._event_bus.publish(
                    VoiceCommandReceivedEvent(
                        transcript=stt_result.transcript,
                        confidence=stt_result.confidence,
                        duration=stt_result.duration,
                        provider=stt_result.provider,
                    )
                )

                return stt_result

            except asyncio.TimeoutError:
                logger.info("Voice listening timed out after %.1fs", listen_timeout)
                await self._capture.cancel()
                await self._handle_recognition_failure("TimeoutError", "Listening timed out")
                return None

            except STTError as err:
                logger.warning("STT transcription failed: %s", err)
                await self._capture.cancel()
                await self._handle_recognition_failure("STTError", str(err))
                return None

            except Exception as err:
                logger.error("Unhandled voice pipeline error: %s", err, exc_info=True)
                await self._capture.cancel()
                await self._handle_recognition_failure(type(err).__name__, str(err))
                return None

    async def speak(self, text: str, interruptible: bool = True) -> None:
        """Voicing response through Text-to-Speech provider with lifecycle events."""
        if not text or not text.strip():
            logger.debug("Empty text passed to speak(); skipping.")
            return

        await self._event_bus.publish(SpeechStartedEvent(text=text))

        try:
            await self._tts.speak(text, interruptible=interruptible)
            await self._event_bus.publish(SpeechStoppedEvent(text=text, completed=True))
        except Exception as err:
            logger.error("TTS playback failed: %s", err)
            await self._event_bus.publish(
                SpeechSynthesisFailedEvent(
                    text=text,
                    error_type=type(err).__name__,
                    message=str(err),
                )
            )

    async def stop_speaking(self) -> None:
        """Interrupt and halt any active speech synthesis."""
        await self._tts.stop()

    def cancel_listening(self) -> None:
        """Signal ongoing listening session to abort."""
        self._cancel_requested = True

    async def _handle_recognition_failure(self, error_type: str, message: str) -> None:
        """Emit failure event and recover state machine to IDLE."""
        await self._event_bus.publish(
            VoiceRecognitionFailedEvent(
                error_type=error_type,
                message=message,
            )
        )
        self._recover_to_idle(f"Recognition failure: {message}")

    def _recover_to_idle(self, reason: str) -> None:
        """Safely return state machine to IDLE from error or intermediate states."""
        current = self._state_machine.current_state
        if current == BuddyState.IDLE:
            return

        if self._state_machine.can_transition_to(BuddyState.IDLE):
            self._state_machine.transition_to(BuddyState.IDLE, reason=reason)
        elif self._state_machine.can_transition_to(BuddyState.ERROR):
            self._state_machine.transition_to(BuddyState.ERROR, reason=reason)
            if self._state_machine.can_transition_to(BuddyState.IDLE):
                self._state_machine.transition_to(BuddyState.IDLE, reason="Recovery from error")
