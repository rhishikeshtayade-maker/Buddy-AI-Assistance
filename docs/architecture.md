# BUDDY System Architecture

## 1. Overview & Core Philosophy

**BUDDY** is a voice-first, agentic, local-first, modular, and secure desktop AI assistant for Windows.

### Architectural Tenets:
1. **Zero Unrestricted Execution**: The LLM / AI never receives arbitrary shell access. All actions are dispatched via typed, sandboxed, and risk-rated tools.
2. **Security & Permission Gatekeeper**: Every capability request passes through the Security & Permission Engine before execution.
3. **Loop Engineering**: Continuous verification loop (Observe → Understand → Plan → Implement → Run → Test → Verify → Diagnose → Fix → Retest → Document).
4. **Resilient Failure Recovery**: Degrade gracefully (e.g. offline fallback, retry policies, sanitized error messages).

---

## 2. High-Level Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                 DESKTOP UI (PySide6)                              |
|   Dashboard  |  Voice Visualizer  |  Task Monitor  |  Security Center  |  Settings|
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                                   BUDDY CORE                                      |
|  - Lifecycle Management & State Machine (IDLE -> LISTENING -> THINKING -> EXEC)   |
|  - Event Bus (Decoupled Pub/Sub across modules)                                   |
|  - Configuration & Health Diagnostics Registry                                    |
+----------------------+--------------------+--------------------+------------------+
                       |                    |                    |
        +--------------+                    |                    +-------------+
        v                                   v                                  v
+-------------------+              +-------------------+              +-------------------+
|  VOICE PIPELINE   |              | CONVERSATION & AI |              | SECURITY ENGINE   |
| - Audio Capture   |              | - AIProvider      |              | - Risk Levels 0-4 |
| - VAD & Wake Word |              |   (Local / Cloud) |              | - Confirmation    |
| - STT (Whisper)   |              | - Task Planner    |              | - Local PIN / Auth|
| - TTS Synthesis   |              | - Context Window  |              | - Encrypted Store |
+-------------------+              +---------+---------+              +---------+---------+
                                             |                                  |
                                             v                                  v
                               +--------------------------------------------------+
                               |                 TOOL REGISTRY                    |
                               |  - Application Control   - Filesystem (Guarded)  |
                               |  - System Diagnostics    - Browser Agent (Safe)  |
                               |  - Vision / Screenshot   - Developer Mode        |
                               +---------------------+----------------------------+
                                                     |
                                                     v
                               +--------------------------------------------------+
                               |               VERIFICATION ENGINE                |
                               |  Confirms real system state post-execution       |
                               +---------------------+----------------------------+
                                                     |
                                                     v
                               +--------------------------------------------------+
                               |           AUDIT LOG & PERSISTENCE                |
                               |  Tamper-evident logs & AES-256-GCM encrypted DB  |
                               +--------------------------------------------------+
```

---

## 3. Directory Layout & Module Responsibilities

- **`app/core/`**: Assistant orchestrator, configuration schemas (`config.py`), event bus (`events.py`), exceptions hierarchy (`exceptions.py`), and lifecycle state machine (`lifecycle.py`).
- **`app/voice/`**: Audio capture, voice activity detection, wake word listener, STT/TTS abstractions.
- **`app/ai/`**: Abstract AI provider (`AIProvider`), local/cloud implementations, prompt templates, context manager.
- **`app/agent/`**: Agentic decomposition, step planning, execution loop, step verification.
- **`app/tools/`**: Typed tools conforming to `BaseTool`, with metadata, JSON schema inputs/outputs, risk classification, and confirmation gates.
- **`app/security/`**: AES-256-GCM cryptography, OS keyring credentials, permission matrix, multi-factor/PIN confirmation, tamper-evident audit logging.
- **`app/memory/`**: Short-term conversational cache, long-term semantic storage, encrypted profile store.
- **`app/vision/`**: Controlled screenshot grabbing and visual analysis pipeline.
- **`app/automation/`**: Cron/interval schedulers, event triggers, and automated workflows.
- **`app/ui/`**: PySide6 dark-mode modern desktop user interface and reactive status widgets.
- **`app/storage/`**: Local SQLite database management, encrypted schema migrations, and models.

---

## 4. State Machine Specification

BUDDY operates under strict, strongly-typed states (`BuddyState`):

```text
STARTING -> IDLE, ERROR
IDLE -> LISTENING, THINKING, SHUTTING_DOWN
LISTENING -> THINKING, ERROR, SHUTTING_DOWN
THINKING -> EXECUTING, SPEAKING, ERROR, SHUTTING_DOWN
EXECUTING -> THINKING, SPEAKING, ERROR, SHUTTING_DOWN
SPEAKING -> IDLE, ERROR, SHUTTING_DOWN
ERROR -> IDLE, SHUTTING_DOWN
SHUTTING_DOWN -> (terminal)
```

Transitions are strictly validated against `VALID_TRANSITIONS`. Invalid transitions immediately raise `StateTransitionError`.

---

## 5. Loop 1 Core Runtime Architecture (Implemented)

The following core runtime systems are active and verified:

1. **State Machine (`app/core/state.py`)**:
   - Strongly typed `BuddyState` enum.
   - Rejection of illegal transitions with explicit `StateTransitionError`.
   - Immutable `StateTransitionRecord` history audit log.
   - Synchronous/async thread safety using recursive locks.

2. **Async Event Bus (`app/core/events.py`)**:
   - Decoupled publisher-subscriber model with `subscribe()`, `unsubscribe()`, and `publish()`.
   - Core typed events: `ApplicationStartedEvent`, `ApplicationStoppingEvent`, `ApplicationStoppedEvent`, `StateChangedEvent`, `ErrorEvent`, `HealthChangedEvent`.
   - Exception isolation ensuring a single failing subscriber cannot crash the bus or disrupt others.
   - Idempotent bus shutdown.

3. **Typed Configuration (`app/core/config.py`)**:
   - Environment-driven schema via Pydantic Settings (`BuddyConfig`).
   - Dual-naming support (`APP_ENV` / `BUDDY_ENV`, `LOG_LEVEL` / `BUDDY_LOG_LEVEL`).
   - Automatic secret masking via `to_safe_dict()`.

4. **Structured Logging & Secret Redaction (`app/core/logging.py`)**:
   - Unified logging namespace (`buddy.*`).
   - Contextual attributes: `state`, `event`, `operation`.
   - Automated regex-based scrubbing (`SecretRedactionFilter`) of API keys, bearer tokens, passwords, and private keys.

5. **Service Registry (`app/core/registry.py`)**:
   - Thread-safe key/type service locator avoiding brittle global singletons.
   - Strict duplication prevention with override controls.

6. **Health Monitoring System (`app/core/health.py`)**:
   - Status levels: `HEALTHY`, `DEGRADED`, `UNHEALTHY`.
   - Built-in diagnostics for configuration, event bus, service registry, and system runtime.
   - Concurrently executed checks with latency timing.
   - Aggregated system status calculation.

7. **Lifecycle Manager (`app/core/lifecycle.py`)**:
   - Deterministic startup: `initialize()` -> `start()` -> `run()` -> `stop()` -> `shutdown()`.
   - Idempotent cleanup safe against multiple invocations.
   - Windows console signal interception (`SIGINT`, `SIGTERM`, `SIGBREAK`).

8. **Runtime Context (`app/core/context.py`)**:
   - Unified typed container passing active core runtime services across future modules.

---

## 6. Loop 2 Voice Pipeline Architecture (Implemented)

BUDDY implements a decoupled, vendor-agnostic voice subsystem:

```text
                 MICROPHONE
                     │
                     ▼
              AUDIO CAPTURE (SoundDevice / Mock)
                     │
                     ▼
            VOICE ACTIVITY DETECTION (Energy RMS / Mock)
                     │
                     ▼
              SPEECH-TO-TEXT (SpeechRecognition / Mock)
                     │
                     ▼
              VOICE COMMAND (VoiceCommandReceivedEvent)
                     │
                     ▼
                BUDDY CORE (IDLE -> LISTENING -> THINKING)
                     │
                     ▼
              TEXT RESPONSE
                     │
                     ▼
             TEXT-TO-SPEECH (pyttsx3 / Mock)
                     │
                     ▼
                 SPEAKER
```

### Components & Abstractions:

1. **Audio Device Management (`app/voice/device.py`)**:
   - `AudioDeviceManager`: Lists input/output devices, detects system defaults, and validates endpoint capabilities without crashing on missing hardware.

2. **Audio Capture (`app/voice/capture.py`)**:
   - `AudioCaptureInterface`: Vendor-neutral interface for start, stop, cancel, and chunk reading.
   - `SoundDeviceAudioCapture`: Real-time microphone capture via PortAudio/sounddevice with non-blocking audio queues.
   - `MockAudioCapture`: Deterministic audio capture generator for unit testing and CI.

3. **Voice Activity Detection (`app/voice/vad.py`)**:
   - `EnergyVAD`: Real-time RMS amplitude energy detector with configurable silence timeout (default 1.5s), minimum speech threshold (0.3s), and maximum duration bounds (15s).
   - States: `WAITING` -> `SPEAKING` -> `SILENCE` -> `COMPLETED`.
   - `MockVAD`: Programmable state transitions for headless testing.

4. **Speech-to-Text (`app/voice/stt.py`)**:
   - `SpeechToTextProvider`: Protocol returning structured `STTResult` (transcript, confidence, language, duration, provider).
   - `SpeechRecognitionSTTProvider`: Python speech_recognition integration with thread pooling and timeout handling.
   - `MockSTTProvider`: Deterministic, configurable transcription engine for CI.

5. **Text-to-Speech & Speech Interruption (`app/voice/tts.py`)**:
   - `TextToSpeechProvider`: Synthesizes and voices text with immediate cancellation support via `stop()`.
   - `Pyttsx3TTSProvider`: Local, offline speech synthesis engine (Windows SAPI5).
   - `MockTTSProvider`: In-memory speech recording and interruption tracking.

6. **Wake Word Detection (`app/voice/wake.py`)**:
   - `WakeWordDetector`: Abstract trigger phrase detector interface.
   - `MockWakeWordDetector`: Deterministic detector for automated testing.
   - `KeywordWakeWordDetector`: Lightweight keyword verification through STT.

7. **Voice Pipeline Orchestrator (`app/voice/pipeline.py`)**:
   - Coordinates the full voice cycle while updating BUDDY core state (`IDLE` -> `LISTENING` -> `THINKING`).
   - Publishes decoupled voice events: `VoiceListeningStartedEvent`, `VoiceListeningStoppedEvent`, `VoiceCommandReceivedEvent`, `VoiceRecognitionFailedEvent`, `SpeechStartedEvent`, `SpeechStoppedEvent`, `SpeechSynthesisFailedEvent`.
   - Measures capture, VAD, STT, and total pipeline latency.

8. **Privacy & Security Architecture**:
   - In-memory ephemeral buffers: raw PCM bytes are scrubbed immediately after transcription.
   - Transcript masking: Transcripts are suppressed or masked at INFO level unless `LOG_TRANSCRIPTS=true` is set.
   - Zero continuous recording or unauthorized audio transmission.


