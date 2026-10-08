"""BUDDY Voice Pipeline Orchestrator.

Coordinates AudioCapture, Voice Activity Detection (VAD), Speech-to-Text (STT),
Text-to-Speech (TTS), and Wake-Word Detection while integrating seamlessly
with BUDDY Core State Machine and EventBus.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Callable, Optional

from app.core import BuddyState, EventBus, StateMachine
from app.core.config import BuddyConfig
from app.voice.capture import AudioCaptureInterface, MockAudioCapture, SoundDeviceAudioCapture
from app.voice.device import AudioDeviceManager
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    SpeechSynthesisFailedEvent,
    VoiceBargeInDetectedEvent,
    VoiceCommandReceivedEvent,
    VoiceLatencyRecordedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
    VoicePartialTranscriptEvent,
    VoiceRecognitionFailedEvent,
    VoiceSpeechDetectedEvent,
    VoiceSpeechEndedEvent,
    WakeWordDetectedEvent,
)
from app.voice.exceptions import (
    AudioCaptureError,
    NoAudioFramesError,
    STTEmptyError,
    STTError,
    STTServiceError,
    STTTimeoutError,
    STTUnclearError,
    TTSError,
    VoiceError,
)
from app.voice.models import (
    AudioData,
    CaptureDiagnostics,
    ListenResult,
    STTResult,
    TranscriptionStatus,
    VADState,
    VoiceLatencyMetrics,
    VoiceOutcome,
)
from app.voice.stt import (
    MockSTTProvider,
    MockStreamingSTTProvider,
    SpeechRecognitionSTTProvider,
    SpeechToTextProvider,
    StreamingSTTProvider,
    StreamingSTTSession,
)
from app.voice.tts import MockTTSProvider, Pyttsx3TTSProvider, TextToSpeechProvider
from app.voice.vad import EnergyVAD, MockVAD, VoiceActivityDetectorInterface
from app.voice.wake import KeywordWakeWordDetector, LocalWakeWordDetector, MockWakeWordDetector, WakeWordDetector

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
        self._stt = stt or self._create_default_stt()
        self._tts = tts or self._create_default_tts()
        self._capture = capture or self._create_default_capture()
        self._vad = vad or EnergyVAD(
            energy_threshold=getattr(config, "vad_energy_threshold", 60.0),
            silence_timeout=config.vad_silence_timeout,
            sample_rate=config.audio_sample_rate,
        )
        if wake_word:
            self._wake_word = wake_word
        elif self._config.stt_provider.lower() != "mock":
            self._wake_word = KeywordWakeWordDetector(stt_provider=self._stt, wake_word=config.wake_word)
        else:
            self._wake_word = MockWakeWordDetector(wake_word=config.wake_word)

        self._is_active = False
        self._cancel_requested = False
        self._lock = asyncio.Lock()

        # Latency diagnostics baseline
        self.last_capture_latency: float = 0.0
        self.last_vad_latency: float = 0.0
        self.last_stt_latency: float = 0.0
        self.last_pipeline_latency: float = 0.0
        self.last_metrics: Optional[VoiceLatencyMetrics] = None

    @property
    def metrics(self) -> Optional[VoiceLatencyMetrics]:
        """Return the most recent turn's latency metrics."""
        return self.last_metrics

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
        is_testing = getattr(self._config, "app_env", "").lower() == "testing"
        if not self._config.voice_enabled or (is_testing and self._config.stt_provider.lower() == "mock"):
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
            return MockAudioCapture(
                sample_rate=self._config.audio_sample_rate,
                channels=self._config.audio_channels,
            )

    def _create_default_stt(self) -> SpeechToTextProvider:
        if self._config.stt_provider.lower() in ("speech_recognition", "google", "system"):
            return SpeechRecognitionSTTProvider()
        if self._config.stt_provider.lower() == "mock":
            return MockSTTProvider()
        return SpeechRecognitionSTTProvider()

    def _create_default_tts(self) -> TextToSpeechProvider:
        if self._config.tts_provider.lower() in ("pyttsx3", "system", "windows"):
            try:
                return Pyttsx3TTSProvider()
            except Exception as e:
                logger.warning("Could not initialize pyttsx3 TTS: %s", e)
                return MockTTSProvider()
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
        result = await self.listen_with_diagnostics(timeout=timeout)
        return result.stt_result if result.ok else None

    async def listen_with_diagnostics(self, timeout: Optional[float] = None) -> ListenResult:
        """Capture and transcribe with explicit outcome classification (A-G).

        Taxonomy:
          A: MIC_UNAVAILABLE     - AudioCapture failed to open/start
          B: NO_FRAMES           - Stream started but 0 audio chunks arrived
          C: SILENCE             - Chunks received but no speech activity
          D: STT_FAILED          - Speech detected but transcription failed (empty/unclear/error)
          G: TRANSCRIBED         - Transcription succeeded with valid text
        """
        async with self._lock:
            start_pipeline_time = time.perf_counter()
            diag = CaptureDiagnostics(
                energy_threshold=getattr(self._vad, "energy_threshold", 0.0),
                noise_floor=getattr(self._vad, "noise_floor", 0.0) or 0.0,
            )
            metrics = VoiceLatencyMetrics(
                stt_provider=getattr(self._stt, "provider_name", "mock"),
                capture_start_ms=start_pipeline_time * 1000.0,
            )

            if self._cancel_requested:
                self._cancel_requested = False
                self._recover_to_idle("Listening cancelled before start")
                metrics.success = False
                metrics.capture_end_ms = time.perf_counter() * 1000.0
                metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                return ListenResult(
                    outcome=VoiceOutcome.CANCELLED,
                    error_message="Listening cancelled before start",
                    diagnostics=diag,
                    latency_metrics=metrics,
                )

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
                self._recover_to_idle(f"Recovery from invalid start state: {self._state_machine.current_state.value}")
                return ListenResult(
                    outcome=VoiceOutcome.ROUTING_FAILED,
                    error_message=f"Invalid start state: {self._state_machine.current_state.value}",
                    diagnostics=diag,
                    latency_metrics=metrics,
                )

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
                diag.stream_opened = True
                self.last_capture_latency = time.perf_counter() - capture_start_time
            except Exception as err:
                logger.error("Audio capture failed to start: %s", err)
                diag.stream_opened = False
                diag.error = str(err)
                await self._handle_recognition_failure(
                    "AudioCaptureError",
                    f"Microphone capture error: {err}",
                )
                metrics.success = False
                metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                return ListenResult(
                    outcome=VoiceOutcome.MIC_UNAVAILABLE,
                    error_message=str(err),
                    diagnostics=diag,
                    latency_metrics=metrics,
                    capture_latency=time.perf_counter() - capture_start_time,
                    total_latency=time.perf_counter() - start_pipeline_time,
                )

            # 2b. Initialize Streaming STT session if enabled and supported
            stt_session: Optional[StreamingSTTSession] = None
            if getattr(self._config, "voice_streaming_enabled", True) and getattr(self._stt, "supports_streaming", False):
                try:
                    stt_session = await self._stt.start_stream(
                        sample_rate=self._config.audio_sample_rate,
                    )
                except Exception as e:
                    logger.debug("Could not start streaming STT session, using batch fallback: %s", e)
                    stt_session = None

            # 3. Stream chunks into VAD and STT session until utterance completion or timeout
            vad_start_time = time.perf_counter()
            deadline = time.time() + listen_timeout
            chunks_received = 0
            bytes_received = 0
            first_chunk_t = None
            peak_rms = 0.0
            sum_rms = 0.0

            try:
                while not self._cancel_requested:
                    if time.time() > deadline:
                        raise asyncio.TimeoutError(f"Listening timed out after {listen_timeout}s")

                    chunk = await self._capture.read_chunk(timeout=0.5)
                    if first_chunk_t is None:
                        first_chunk_t = time.perf_counter() - vad_start_time
                    chunks_received += 1
                    bytes_received += len(chunk)

                    vad_state, vad_event = (
                        self._vad.process_chunk_event(chunk)
                        if hasattr(self._vad, "process_chunk_event")
                        else (self._vad.process_chunk(chunk), "none")
                    )
                    chunk_rms = getattr(self._vad, "last_rms", 0.0) or EnergyVAD.calculate_chunk_rms(chunk)
                    peak_rms = max(peak_rms, chunk_rms)
                    sum_rms += chunk_rms

                    if vad_event == "speech_started":
                        await self._event_bus.publish(
                            VoiceSpeechDetectedEvent(
                                rms=chunk_rms,
                                threshold=getattr(self._vad, "energy_threshold", 0.0),
                            )
                        )

                    # Feed streaming STT if active
                    if stt_session is not None:
                        try:
                            partial = await stt_session.push_chunk(chunk)
                            if partial:
                                if metrics.first_transcript_ms is None:
                                    metrics.first_transcript_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                                await self._event_bus.publish(
                                    VoicePartialTranscriptEvent(partial_text=partial)
                                )
                        except Exception as stt_chunk_err:
                            logger.debug("Streaming STT push_chunk error: %s", stt_chunk_err)

                    if vad_state == VADState.COMPLETED:
                        if vad_event == "speech_ended":
                            await self._event_bus.publish(
                                VoiceSpeechEndedEvent(
                                    speech_seconds=getattr(self._vad, "last_speech_seconds", 0.0),
                                    reason=getattr(self._vad, "completion_reason", "silence_timeout") or "silence_timeout",
                                )
                            )
                        break

                    await asyncio.sleep(0.001)

                self.last_vad_latency = time.perf_counter() - vad_start_time
                metrics.capture_end_ms = time.perf_counter() * 1000.0
                diag.chunks_received = chunks_received
                diag.bytes_received = bytes_received
                diag.first_chunk_latency = first_chunk_t
                diag.peak_rms = peak_rms
                diag.mean_rms = (sum_rms / chunks_received) if chunks_received > 0 else 0.0
                diag.speech_detected = getattr(self._vad, "has_speech", False)
                diag.speech_seconds = getattr(self._vad, "last_speech_seconds", 0.0)
                diag.termination = getattr(self._vad, "completion_reason", "completed") or "completed"

                if self._cancel_requested:
                    if stt_session is not None:
                        await stt_session.cancel()
                    await self._capture.cancel()
                    await self._event_bus.publish(
                        VoiceListeningStoppedEvent(reason="Capture cancelled")
                    )
                    self._recover_to_idle("Listening cancelled")
                    metrics.success = False
                    metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                    return ListenResult(
                        outcome=VoiceOutcome.CANCELLED,
                        error_message="Listening cancelled",
                        diagnostics=diag,
                        latency_metrics=metrics,
                    )

                # Check if frames were received
                if chunks_received == 0:
                    if stt_session is not None:
                        await stt_session.cancel()
                    await self._capture.stop()
                    await self._handle_recognition_failure("NoAudioFramesError", "No audio frames received from microphone")
                    metrics.success = False
                    metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                    return ListenResult(
                        outcome=VoiceOutcome.NO_FRAMES,
                        error_message="Microphone opened but delivered no audio frames",
                        diagnostics=diag,
                        latency_metrics=metrics,
                        total_latency=time.perf_counter() - start_pipeline_time,
                    )

                # 4. Stop capture and retrieve AudioData
                audio = await self._capture.stop()
                diag.window_seconds = audio.duration
                diag.utterance_seconds = audio.duration

                await self._event_bus.publish(
                    VoiceListeningStoppedEvent(
                        reason="Utterance completed",
                        duration=audio.duration,
                    )
                )

                # If no speech activity detected (pure silence)
                is_mock_vad = isinstance(self._vad, MockVAD)
                if not is_mock_vad and not diag.speech_detected and audio.duration < 0.2:
                    if stt_session is not None:
                        await stt_session.cancel()
                    self._recover_to_idle("No speech detected (silence)")
                    await self._handle_recognition_failure("SilenceError", "No speech detected (silence)")
                    metrics.success = False
                    metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                    return ListenResult(
                        outcome=VoiceOutcome.SILENCE,
                        transcription_status=TranscriptionStatus.NOT_ATTEMPTED,
                        diagnostics=diag,
                        latency_metrics=metrics,
                        capture_latency=time.perf_counter() - vad_start_time,
                        total_latency=time.perf_counter() - start_pipeline_time,
                    )

                # 5. State Transition: LISTENING -> THINKING
                if self._state_machine.can_transition_to(BuddyState.THINKING):
                    self._state_machine.transition_to(
                        BuddyState.THINKING,
                        reason="Utterance captured; dispatching to STT",
                    )

                # 6. Transcribe via STT provider (Streaming or Batch)
                stt_start_time = time.perf_counter()
                metrics.stt_start_ms = stt_start_time * 1000.0
                try:
                    if stt_session is not None:
                        stt_result = await stt_session.finish()
                    else:
                        stt_result = await self._stt.transcribe(audio)

                    stt_end_time = time.perf_counter()
                    self.last_stt_latency = stt_end_time - stt_start_time
                    self.last_pipeline_latency = stt_end_time - start_pipeline_time
                    metrics.stt_complete_ms = stt_end_time * 1000.0
                    metrics.total_turn_ms = self.last_pipeline_latency * 1000.0
                    self.last_metrics = metrics

                    await self._event_bus.publish(
                        VoiceLatencyRecordedEvent(
                            total_turn_ms=metrics.total_turn_ms,
                            metrics_summary=metrics.to_safe_dict(),
                        )
                    )

                    # Privacy log
                    if self._config.log_transcripts:
                        logger.debug("Transcribed speech: '%s' (conf=%.2f)", stt_result.transcript, stt_result.confidence or 0.0)
                    else:
                        logger.debug("Transcribed speech received (length=%d chars, duration=%.2fs)", len(stt_result.transcript), audio.duration)

                    # Publish VoiceCommandReceivedEvent
                    await self._event_bus.publish(
                        VoiceCommandReceivedEvent(
                            transcript=stt_result.transcript,
                            confidence=stt_result.confidence,
                            duration=stt_result.duration,
                            provider=stt_result.provider,
                        )
                    )

                    return ListenResult(
                        outcome=VoiceOutcome.TRANSCRIBED,
                        transcription_status=TranscriptionStatus.TRANSCRIPTION_SUCCESS,
                        stt_result=stt_result,
                        diagnostics=diag,
                        latency_metrics=metrics,
                        capture_latency=self.last_vad_latency,
                        stt_latency=self.last_stt_latency,
                        total_latency=self.last_pipeline_latency,
                    )

                except STTEmptyError as err:
                    logger.info("STT returned empty transcript: %s", err)
                    await self._handle_recognition_failure("STTEmptyError", str(err))
                    metrics.success = False
                    metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                    return ListenResult(
                        outcome=VoiceOutcome.STT_FAILED,
                        transcription_status=TranscriptionStatus.TRANSCRIPTION_EMPTY,
                        error_message=str(err),
                        diagnostics=diag,
                        latency_metrics=metrics,
                    )
                except STTUnclearError as err:
                    logger.info("Speech was unclear/unintelligible: %s", err)
                    await self._handle_recognition_failure("STTUnclearError", str(err))
                    metrics.success = False
                    metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                    return ListenResult(
                        outcome=VoiceOutcome.STT_FAILED,
                        transcription_status=TranscriptionStatus.TRANSCRIPTION_UNCLEAR,
                        error_message=str(err),
                        diagnostics=diag,
                        latency_metrics=metrics,
                    )
                except (STTServiceError, STTTimeoutError, STTError) as err:
                    logger.warning("STT service error: %s", err)
                    await self._handle_recognition_failure(type(err).__name__, str(err))
                    metrics.success = False
                    metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                    return ListenResult(
                        outcome=VoiceOutcome.STT_FAILED,
                        transcription_status=TranscriptionStatus.TRANSCRIPTION_ERROR,
                        error_message=str(err),
                        diagnostics=diag,
                        latency_metrics=metrics,
                    )

            except asyncio.TimeoutError:
                logger.info("Voice listening timed out after %.1fs", listen_timeout)
                if stt_session is not None:
                    await stt_session.cancel()
                await self._capture.cancel()
                await self._handle_recognition_failure("TimeoutError", "Listening timed out")
                sample_rate = getattr(self._config, "audio_sample_rate", 16000) or 16000
                total_samples = bytes_received // 2
                diag.chunks_received = chunks_received
                diag.bytes_received = bytes_received
                diag.first_chunk_latency = first_chunk_t
                diag.peak_rms = peak_rms
                diag.mean_rms = (sum_rms / chunks_received) if chunks_received > 0 else 0.0
                diag.speech_detected = getattr(self._vad, "has_speech", False)
                diag.speech_seconds = getattr(self._vad, "last_speech_seconds", 0.0)
                diag.window_seconds = total_samples / sample_rate if sample_rate > 0 else 0.0
                diag.utterance_seconds = diag.speech_seconds
                diag.termination = "timeout"
                metrics.success = False
                metrics.capture_end_ms = time.perf_counter() * 1000.0
                metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                return ListenResult(
                    outcome=VoiceOutcome.SILENCE if chunks_received > 0 else VoiceOutcome.NO_FRAMES,
                    error_message=f"Listening timed out after {listen_timeout}s",
                    diagnostics=diag,
                    latency_metrics=metrics,
                    capture_latency=time.perf_counter() - vad_start_time,
                    total_latency=time.perf_counter() - start_pipeline_time,
                )

            except Exception as err:
                logger.error("Unhandled voice pipeline error: %s", err, exc_info=True)
                if stt_session is not None:
                    await stt_session.cancel()
                await self._capture.cancel()
                await self._handle_recognition_failure(type(err).__name__, str(err))
                sample_rate = getattr(self._config, "audio_sample_rate", 16000) or 16000
                total_samples = bytes_received // 2
                diag.chunks_received = chunks_received
                diag.bytes_received = bytes_received
                diag.peak_rms = peak_rms
                diag.mean_rms = (sum_rms / chunks_received) if chunks_received > 0 else 0.0
                diag.window_seconds = total_samples / sample_rate if sample_rate > 0 else 0.0
                diag.termination = "error"
                metrics.success = False
                metrics.capture_end_ms = time.perf_counter() * 1000.0
                metrics.total_turn_ms = (time.perf_counter() - start_pipeline_time) * 1000.0
                return ListenResult(
                    outcome=VoiceOutcome.MIC_UNAVAILABLE if not diag.stream_opened else VoiceOutcome.STT_FAILED,
                    error_message=str(err),
                    diagnostics=diag,
                    latency_metrics=metrics,
                )

    async def _run_barge_in_monitor(self) -> bool:
        """Monitor microphone input during speech output to detect user interruption."""
        floor = getattr(self._vad, "noise_floor", 0.0) or 50.0
        # Elevate threshold comfortably above output feedback echo margin
        threshold = max(floor + 80.0, getattr(self._vad, "energy_threshold", 60.0) * 1.6, 140.0)

        started_here = False
        if not self._capture.is_capturing:
            try:
                await self._capture.start()
                started_here = True
            except Exception:
                return False

        consecutive_frames = 0
        try:
            while True:
                try:
                    chunk = await self._capture.read_chunk(timeout=0.08)
                    rms = EnergyVAD.calculate_chunk_rms(chunk)
                    if rms >= threshold:
                        consecutive_frames += 1
                        if consecutive_frames >= 2:
                            return True
                    else:
                        consecutive_frames = 0
                except (asyncio.TimeoutError, AudioCaptureError):
                    continue
        except asyncio.CancelledError:
            if started_here and self._capture.is_capturing:
                try:
                    await self._capture.stop()
                except Exception:
                    pass
            raise
        return False

    async def speak(self, text: str, interruptible: bool = True, barge_in: Optional[bool] = None) -> bool:
        """Voicing response through Text-to-Speech provider with lifecycle events and barge-in.

        Returns True if playback finished completely, False if cancelled or interrupted by barge-in.
        """
        if not text or not text.strip():
            logger.debug("Empty text passed to speak(); skipping.")
            if self._state_machine.current_state in (BuddyState.THINKING, BuddyState.EXECUTING):
                self._recover_to_idle("Speech skipped for empty text")
            return True

        should_return_to_idle = False
        if self._state_machine.current_state in (BuddyState.THINKING, BuddyState.EXECUTING):
            if self._state_machine.can_transition_to(BuddyState.SPEAKING):
                self._state_machine.transition_to(BuddyState.SPEAKING, reason="Voicing speech response")
                should_return_to_idle = True
        elif self._state_machine.current_state == BuddyState.SPEAKING:
            should_return_to_idle = True

        enable_barge_in = (
            barge_in if barge_in is not None
            else getattr(self._config, "voice_barge_in_enabled", True)
        )

        await self._event_bus.publish(SpeechStartedEvent(text=text))

        try:
            if enable_barge_in and interruptible and self._state_machine.can_transition_to(BuddyState.LISTENING):
                speak_task = asyncio.create_task(self._tts.speak(text, interruptible=interruptible))
                monitor_task = asyncio.create_task(self._run_barge_in_monitor())
                done, pending = await asyncio.wait(
                    [speak_task, monitor_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

                if monitor_task in done and monitor_task.result() is True:
                    await self._tts.stop()
                    await self._event_bus.publish(SpeechStoppedEvent(text=text, completed=False, interrupted=True))
                    await self._event_bus.publish(VoiceBargeInDetectedEvent(reason="User speech detected during playback"))
                    if self._state_machine.can_transition_to(BuddyState.LISTENING):
                        self._state_machine.transition_to(BuddyState.LISTENING, reason="Barge-in speech interruption")
                    return False
                else:
                    if speak_task in done:
                        speak_task.result()
                    await self._event_bus.publish(SpeechStoppedEvent(text=text, completed=True))
                    return True
            else:
                await self._tts.speak(text, interruptible=interruptible)
                await self._event_bus.publish(SpeechStoppedEvent(text=text, completed=True))
                return True

        except Exception as err:
            logger.error("TTS playback failed: %s", err)
            await self._event_bus.publish(
                SpeechSynthesisFailedEvent(
                    text=text,
                    error_type=type(err).__name__,
                    message=str(err),
                )
            )
            raise
        finally:
            if should_return_to_idle and self._state_machine.current_state == BuddyState.SPEAKING:
                self._recover_to_idle("Speech playback completed")

    async def speak_stream(
        self,
        token_stream: AsyncIterator[str],
        interruptible: bool = True,
        barge_in: Optional[bool] = None,
    ) -> bool:
        """Streamingly voice response tokens with incremental synthesis and barge-in monitoring."""
        should_return_to_idle = False
        if self._state_machine.current_state in (BuddyState.THINKING, BuddyState.EXECUTING):
            if self._state_machine.can_transition_to(BuddyState.SPEAKING):
                self._state_machine.transition_to(BuddyState.SPEAKING, reason="Voicing streaming speech response")
                should_return_to_idle = True
        elif self._state_machine.current_state == BuddyState.SPEAKING:
            should_return_to_idle = True

        enable_barge_in = (
            barge_in if barge_in is not None
            else getattr(self._config, "voice_barge_in_enabled", True)
        )

        await self._event_bus.publish(SpeechStartedEvent(text="[stream]"))

        try:
            if enable_barge_in and interruptible and self._state_machine.can_transition_to(BuddyState.LISTENING):
                speak_task = asyncio.create_task(self._tts.speak_stream(token_stream, interruptible=interruptible))
                monitor_task = asyncio.create_task(self._run_barge_in_monitor())
                done, pending = await asyncio.wait(
                    [speak_task, monitor_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

                if monitor_task in done and monitor_task.result() is True:
                    await self._tts.stop()
                    await self._event_bus.publish(SpeechStoppedEvent(text="[stream]", completed=False, interrupted=True))
                    await self._event_bus.publish(VoiceBargeInDetectedEvent(reason="User speech detected during streaming playback"))
                    if self._state_machine.can_transition_to(BuddyState.LISTENING):
                        self._state_machine.transition_to(BuddyState.LISTENING, reason="Barge-in streaming interruption")
                    return False
                else:
                    if speak_task in done:
                        speak_task.result()
                    await self._event_bus.publish(SpeechStoppedEvent(text="[stream]", completed=True))
                    return True
            else:
                await self._tts.speak_stream(token_stream, interruptible=interruptible)
                await self._event_bus.publish(SpeechStoppedEvent(text="[stream]", completed=True))
                return True

        except Exception as err:
            logger.error("TTS streaming playback failed: %s", err)
            raise
        finally:
            if should_return_to_idle and self._state_machine.current_state == BuddyState.SPEAKING:
                self._recover_to_idle("Speech streaming playback completed")

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

    async def listen_for_wake_word(self, timeout: Optional[float] = None) -> bool:
        """Capture audio utterance and test if configured wake word is present."""
        async with self._lock:
            self._cancel_requested = False
            listen_timeout = timeout or 10.0
            deadline = time.time() + listen_timeout

            self._vad.reset()
            self._wake_word.reset()
            try:
                await self._capture.start()
            except Exception as e:
                logger.error("Failed to start audio capture for wake word: %s", e)
                return False

            chunk_detected = False
            try:
                while not self._cancel_requested:
                    if time.time() > deadline:
                        break

                    chunk = await self._capture.read_chunk(timeout=0.5)

                    # Incremental chunk check for streaming/local wake detectors
                    if self._wake_word.process_chunk(chunk):
                        chunk_detected = True
                        break

                    vad_state = self._vad.process_chunk(chunk)
                    if vad_state == VADState.COMPLETED:
                        break

                    await asyncio.sleep(0.001)

                if self._cancel_requested:
                    await self._capture.cancel()
                    return False

                audio = await self._capture.stop()
                if chunk_detected:
                    await self._event_bus.publish(
                        WakeWordDetectedEvent(wake_word=self._wake_word.wake_word)
                    )
                    return True

                if not audio or not audio.raw_data:
                    return False

                detected = await self._wake_word.detect(audio)
                if detected:
                    await self._event_bus.publish(
                        WakeWordDetectedEvent(wake_word=self._wake_word.wake_word)
                    )
                return detected

            except asyncio.CancelledError:
                try:
                    await self._capture.cancel()
                except Exception:
                    pass
                raise
            except Exception as e:
                logger.debug("Wake word detection loop error: %s", e)
                try:
                    await self._capture.cancel()
                except Exception:
                    pass
                return False
