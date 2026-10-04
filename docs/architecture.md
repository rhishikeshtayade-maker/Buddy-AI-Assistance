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

---

## 7. Loop 3 AI Provider & Conversational Brain Architecture (Implemented)

BUDDY incorporates a provider-agnostic, security-bounded conversational reasoning layer:

```text
                    BUDDY
                      │
                      ▼
              Conversation Manager
                      │
                      ▼
                  AI Router
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
    Cloud Provider           Local Provider (Ollama / Local LLM)
  (OpenAI Compatible)             │
          │                       ▼
          ▼                  Local Model
       AI Model
```

### Components & Responsibilities:

1. **AI Provider Interface (`app/ai/provider.py`)**:
   - `AIProvider`: Abstract protocol declaring `generate()` and `generate_stream()` with token limits, temperature, and timeouts.
   - `MockAIProvider`: Deterministic, offline-testable AI generator with contextual response mapping and error simulation.
   - `CloudAIProvider`: Resilient async HTTP client (via `httpx`) supporting standard chat completion endpoints, bounded exponential backoff retries on 429/5xx, and immediate failure on 401/403.
   - `LocalAIProvider`: Integration contract for local inference engines (e.g. Ollama `localhost:11434`), gracefully reporting service unavailability when not running.

2. **AI Router (`app/ai/router.py`)**:
   - Configuration-driven selection (`AI_PROVIDER=mock|cloud|local`).
   - Dynamic provider registry allowing custom providers without core modification.

3. **Message & Response Models (`app/ai/models.py`)**:
   - `ChatMessage`: Typed message unit with roles (`SYSTEM`, `USER`, `ASSISTANT`, `TOOL`, `EXTERNAL`) and content source classifications.
   - `AIResponse`: Structured response with content, finish reasons, token usage metrics, latency, and tool calls.

4. **Conversation Management (`app/ai/conversation.py`)**:
   - Multi-turn conversation history tracking.
   - Bounded context truncation enforcing `conversation_max_messages` to prevent token overflow.
   - Event publication: `ConversationStartedEvent`, `UserMessageReceivedEvent`, `AIRequestStartedEvent`, `AIResponseReceivedEvent`, `ConversationErrorEvent`, `ConversationEndedEvent`.

5. **Security & Prompt Injection Defenses (`app/ai/prompts.py`)**:
   - Isolated `BUDDY_SYSTEM_PROMPT` establishing grounded identity, honesty about capabilities, and refusal to claim unverified actions.
   - Untrusted Content Wrapping: `<untrusted_external_content source="...">` tags ensure web/external data cannot hijack internal instructions.
   - Strict Execution Boundary: The AI layer has no path to raw execution (`os.system`, `subprocess`, unrestricted filesystem).

6. **Voice Pipeline Integration (`app/ai/conversation.py` & `app/voice/pipeline.py`)**:
   - End-to-end integration: `Microphone` -> `VAD` -> `STT` -> `VoiceCommandReceivedEvent` -> `ConversationManager` -> `AI Provider` -> `TTS` -> `Speaker`.
   - Coordinated state machine progression: `IDLE` -> `LISTENING` -> `THINKING` -> `SPEAKING` -> `IDLE` (with automatic error recovery to `IDLE`).

7. **Developer CLI Chat Mode (`app/ai/chat.py`)**:
   - Interactive terminal testing harness (`python -m app.ai.chat`) enabling rapid prompt iteration without microphone hardware.

---

## 8. Loop 4 Secure Tool System & Computer Control Architecture (Implemented)

BUDDY implements a secure, provider-independent tool execution framework that allows the AI layer to request controlled computer actions while enforcing strict policy gating and verification:

```text
       User / Voice
            │
            ▼
    ConversationManager
            │
            ▼
        AI Provider
            │ (tool_calls)
            ▼
       ToolRequest
            │
            ▼
       ToolRegistry (Lookup ToolDefinition)
            │
            ▼
     PermissionEngine ───► Authentication / Confirmation Boundary
            │
            ▼
      Tool Execution (Bounded Timeout, asyncio.wait_for)
            │
            ▼
     State Verification (Empirical system state inspection)
            │
            ▼
        ToolResult (success=verified, verified=True)
            │
            ▼
    ConversationManager (TOOL message: wrap_untrusted_content)
            │
            ▼
        AI Provider (Final synthesized answer)
```

### Key Components:

1. **Tool Models (`app/tools/models.py`)**:
   - `ToolRiskLevel` (0=SAFE, 1=LOW, 2=MODERATE, 3=HIGH, 4=CRITICAL).
   - `ToolPermissionLevel` (`NONE`, `SESSION`, `CONFIRM`, `AUTHENTICATE`).
   - Strongly typed `ToolDefinition`, `ToolRequest`, `ToolResult`, and `ToolExecutionStatus`.

2. **Tool Registry (`app/tools/registry.py`)**:
   - Thread-safe registry preventing duplicate registration and ensuring only trusted application code registers tools.
   - Unknown tools fail closed immediately.

3. **Tool Interface (`app/tools/base.py`)**:
   - Abstract base class requiring `validate_input()`, `execute()`, and empirical `verify()`.
   - Execution alone does NOT imply success; verification is mandatory.

4. **Permission Engine (`app/security/permissions.py`)**:
   - Risk derived solely from immutable `ToolDefinition`, immune to AI argument or prompt manipulation.
   - Evaluates mandatory confirmation and authentication gates.

5. **Confirmation & Authentication Boundaries (`app/security/confirmation.py` & `app/security/authentication.py`)**:
   - Single-use, non-transferable cryptographic confirmation tokens tied to request ID and hashed arguments. Replay attacks and parameter tampering are rejected.
   - Local authentication interface supporting salted PBKDF2 PIN verification.

6. **Centralized Path Sandboxing (`app/security/path_policy.py`)**:
   - Strictly confines file operations to authorized user roots (Documents, Downloads, Desktop).
   - Rejects directory traversal (`../`), Windows device namespaces (`CON`, `PRN`, `NUL`), UNC paths (`\\server\share`), and protected files (`.env`, `.ssh`, certificates, credentials).

7. **Registered Computer Control Tools (`app/tools/system.py`, `app/tools/applications.py`, `app/tools/filesystem.py`)**:
   - System: `system.get_info`, `system.get_battery`, `system.get_volume`, `system.set_volume`.
   - Applications: `app.list`, `app.open` (explicit allowlist: `notepad`, `calculator`, `paint`, `explorer`), `app.close` (requires confirmation).
   - Filesystem: `file.search`, `file.read`, `file.create`, `file.rename`, `file.copy`, `file.move`.

8. **AI Tool Integration & Output Sanitization (`app/ai/conversation.py`)**:
   - Passes tool requests from AI response to `ToolExecutor`.
   - Returns verified results as untrusted content wrapped in `<untrusted_external_content>` to defend against prompt injection.
   - Updates state machine: `IDLE` -> `THINKING` -> `EXECUTING` -> `THINKING` -> `SPEAKING` -> `IDLE`.

---

## 9. Loop 6 Controlled Mouse & Keyboard Interaction Architecture

```text
       Voice
         │
         ▼
        AI
         │
         ▼
      Vision
         │
         ▼
    VisionTarget (verified bounding box, confidence >= 0.70, screen fingerprint)
         │
         ▼
  UIActionProposal (action_type, target, screen_dimensions, risk_level)
         │
         ▼
 InteractionRequest (strictly bound coordinates, target_id, fingerprint)
         │
         ▼
 PermissionEngine (target risk classification: SAFE, MODERATE, DANGEROUS, CRITICAL)
         │
         ▼
 Confirmation Boundary (cryptographic token bound to target & arguments)
         │
         ▼
 Interaction Tools (mouse.click, mouse.double_click, mouse.scroll, keyboard.key_press, keyboard.type_text)
         │
         ▼
 Empirical Verification (screen state change / accessibility change verification)
         │
         ▼
     ToolResult
         │
         ▼
        AI
         │
         ▼
       Voice
```

### Core Tenets of Controlled Interaction:
1. **The AI Never Directly Controls Mouse or Keyboard**: The AI can only produce a structured `UIActionProposal`.
2. **Coordinates Must Originate from Verified Targets**: Direct raw coordinate injection (`x=100, y=200`) without a registered, unexpired `VisionTarget` is rejected immediately.
3. **Stale-Screen Protection**: Actions carry the detection-time screen visual fingerprint. If the screen changes dynamically prior to click execution, the action is rejected with `SCREEN_CHANGED`.
4. **Restricted Keyboard Allowlist**: Only explicit safe navigation keys (`ENTER`, `ESC`, `TAB`, `SPACE`, arrow keys, etc.) are allowed. Arbitrary OS shortcut combos are rejected.
5. **Zero Credential / Password Typing**: Automatic typing of passwords, OTPs, API keys, or security tokens is strictly forbidden and fails closed. Typed text is never persisted or logged in audit records.
6. **Narrow Native APIs**: Uses low-level Windows User32 APIs via `ctypes` (`SetCursorPos`, `mouse_event`, `keybd_event`) without third-party automation dependencies like PyAutoGUI.

---

## 10. Loop 7 Advanced Agentic Task Planning & Multi-Step Execution Architecture

```text
       USER GOAL
          │
          ▼
     TASK PLANNER (restricted prompt sandbox, structured output only)
          │
          ▼
      TASK PLAN (strongly-typed Task & TaskStep models)
          │
          ▼
    PLAN VALIDATOR (DAG cycle check, schema check, max_steps, risk synchronization)
          │
          ▼
    STEP EXECUTOR (sequential loop, bounded retries, adaptive replanning)
          │
          ▼
   PERMISSION ENGINE (per-step authorization against ToolDefinition)
          │
          ▼
 CONFIRMATION / AUTH (per-action gating; plan approval is NOT step permission)
          │
          ▼
   REGISTERED TOOL (sandboxed tools from ToolRegistry)
          │
          ▼
      EXECUTION (isolated tool execution via ToolExecutor)
          │
          ▼
    VERIFICATION (empirical system state inspection)
          │
          ▼
     STEP RESULT (ToolResult with success, verified, latency)
          │
          ▼
     TASK CONTEXT (ephemeral state tracking: active apps, fingerprints, targets)
          │
          ▼
  NEXT STEP / REPLAN (evaluate environment changes, abort or adapt)
          │
          ▼
 FINAL VERIFIED RESULT (only empirically verified outcomes reported)
```

### Non-Negotiable Core Principles of Loop 7:
1. **Zero Direct Execution Authority**: The Task Planner never executes actions directly, never runs Python `eval()` or `exec()`, never launches subprocesses, and never touches shell or OS APIs.
2. **Immutability of Risk Levels**: The AI cannot assign or downgrade its own risk levels. Risk tiers and confirmation requirements originate exclusively from registered `ToolDefinition` contracts in the `ToolRegistry`.
3. **Per-Action Authorization Boundary**: A plan is not permission. Approving a plan does not bypass step-level confirmation or authentication. Each dangerous step must independently pass the security boundary.
4. **DAG Dependency Validation**: Step dependencies are validated as a Directed Acyclic Graph before execution. Circular dependencies are rejected immediately. If a prerequisite step fails, dependent steps are marked `SKIPPED`.
5. **Bounded Retries**: Transient failures (e.g. temporary timeouts) are retried at most 2 times. Security blocks, permission denials, confirmation requirements, and invalid arguments are categorically non-retryable.
6. **Adaptive Re-planning**: If the visual screen fingerprint changes or a target disappears (`SCREEN_CHANGED` / `TARGET_NOT_FOUND`), the executor halts the step, captures fresh state, and re-plans adaptively.
7. **Anti-Runaway Protection**: Execution is constrained by strict boundaries: `max_task_steps = 20`, `max_tool_calls_per_task = 30`, and timeouts on planning and execution.
8. **Instant Human Cancellation**: Users can cancel a running task at any moment (`cancel_task()`). The executor immediately halts scheduling and prevents any further actions from beginning.
9. **Untrusted Tool Result Boundary**: Tool outputs are untrusted external data and are wrapped/sanitized; tool results can never create tools, alter policies, or grant permissions.
10. **Sanitized Persistence & Audit**: Audit logs record step metadata, permission decisions, and verification status. Passwords, secrets, sensitive typed text, and raw screenshots are strictly excluded from logs and task context.

---

## 11. Loop 8 Long-Term Memory & Contextual Personalization Architecture

```text
       USER INPUT / GOAL
              │
              ▼
    CONVERSATION / AGENT
              │
              ▼
       MEMORY MANAGER
  (Natural Language Command Check)
   ├── Remember / Forget / Clear / Show
   └── Recalls Relevant Bounded Context
              │
              ▼
        MEMORY POLICY
   (Conservative Secret Detection &
    Prompt Injection Neutralization)
              │
              ▼
    BOUNDED CONTEXT INJECTION
  (<recalled_context> untrusted data block)
              │
              ▼
          AI REASONING
  (Uses preferences without permission bypass)
              │
              ▼
   AUTHENTICATED ENCRYPTION
  (Optional Fernet AES key derivation)
              │
              ▼
   SQLITE PERSISTENCE STORE
  (Parameterized queries, WAL mode, migrations)
```

### Fundamental Architectural Tenet:
> **MEMORY IS CONTEXT, NOT AUTHORITY.**
> Stored memory entries are user preferences and factual context. Memory records CANNOT bypass `PermissionEngine`, CANNOT downgrade `ToolRiskLevel`, CANNOT skip user confirmation tokens, and CANNOT bypass authentication challenges.

### Memory Categories & Lifecycles:
1. **Session Memory**: Ephemeral context relevant only to the active dialogue/task. Bound by `memory_session_ttl_seconds` (default: 1 hour) and expires automatically.
2. **Semantic Long-Term Memory**: Stable cross-session user preferences, project context, and workflows. Persisted until updated or forgotten.
3. **Episodic Memory**: Bounded summaries of past interaction outcomes and workflows. Subject to `memory_episodic_ttl_days` (default: 30 days).
4. **User-Profile Memory**: Explicitly user-approved personal directives (e.g., "Call me Rishi", "I prefer concise answers").

### Provenance Hierarchy:
- `USER_EXPLICIT`: Highest authority (direct user instruction).
- `USER_CONFIRMED`: Inferred candidate explicitly confirmed by user.
- `AI_INFERRED`: Provisional preference; requires confirmation to promote to permanent profile.
- `SYSTEM_GENERATED`: Task summaries and operational metrics.
- `IMPORTED`: User-approved external profile imports.

### Conflict Resolution Strategy:
When a new memory contradicts an existing active memory (e.g. switching browser preference from Chrome to Firefox), the system deterministically resolves the conflict:
- New `USER_EXPLICIT` memory archives older contradictory memory.
- Emits `MemoryConflictDetectedEvent`.
- Prevents stale or contradictory memories from polluting prompt context.

---

## 12. Browser Automation Subsystem (Loop 9)

BUDDY includes a secure, policy-governed browser automation subsystem capable of controlled web interactions through Playwright.

### Fundamental Principle:
> **WEB CONTENT IS UNTRUSTED DATA, NOT AUTHORITY.**
> Everything obtained from webpages, DOM trees, accessibility nodes, text, links, forms, downloads, or scripts is untrusted external data. A webpage can NEVER redefine system instructions, security policies, tool definitions, risk levels, or memory directives.

```
                    AI PLANNER
                         │
                         ▼
             Structured BrowserAction
                         │
                         ▼
                   BrowserPolicy
         (URL, Scheme, SSRF, Domain Match)
                         │
                         ▼
                   ToolRegistry
                         │
                         ▼
                   ToolExecutor
         (PermissionEngine + Confirm/Auth)
                         │
                         ▼
                  BrowserExecutor
        (Staleness + Timeout + Redaction)
                         │
                         ▼
                  Playwright API
                         │
                         ▼
             Isolated Browser Context
                         │
                         ▼
               Post-Action Verification
             (Empirical State Transition)
                         │
                         ▼
                  Audit Log & Event
`

### Key Subsystem Components:
1. **Playwright Integration**: Drives Chromium or Microsoft Edge via async Playwright APIs. No arbitrary JavaScript execution is supported (`browser.evaluate` and `browser.execute_script` fail closed).
2. **Context Isolation**: Every session launches with a clean automation profile (`BrowserContext`). Personal profiles, saved passwords, autofill, and personal cookies are never imported.
3. **Session & Tab Management & Limits**: Tracks session inactivity timeouts (`max_browser_session_duration`), active tab focus, and concurrent tab quotas (`max_browser_tabs`, `max_browser_actions_per_task`, `max_dom_nodes`, `max_accessibility_nodes`, `max_navigation_redirects`, `max_browser_action_timeout`).
4. **URL & SSRF Policy**:
   - Strictly permits `http` and `https`.
   - Rejects `javascript:`, `file:`, `data:`, `vbscript:`, `chrome:`, `edge:`, `about:`.
   - Blocks loopback (`127.0.0.1`, `localhost`), private networks (RFC 1918), link-local, and cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
   - Translates and validates RFC 6052 NAT64 IPv6 addresses.
   - Re-evaluates destination policy on every HTTP redirect up to `max_navigation_redirects`.
5. **DOM & Accessibility Inspection**:
   - Extracts bounded visible text and WAI-ARIA accessibility trees.
   - Generates deterministic structural SHA-256 page fingerprints to invalidate stale targets across DOM mutations, navigation, reloads, and tab switches.
6. **Prompt Injection Defense & Memory Isolation**:
   - Scans extracted text for adversarial prompt injection patterns.
   - Wraps all extracted data in `<external_web_content>` tags with delimiter escape protection.
   - Webpage content is strictly untrusted context and never automatically creates Loop 8 long-term memory records or permission authority.
7. **Sensitive Field & Credential Protection**:
   - Detects password, username+password, PIN, OTP, CVV, credit card, API token, Authorization header, and cookie/session data fields.
   - Sensitive values cannot be entered automatically, logged, stored in Loop 8 memory, or returned in ordinary tool output.
8. **Controlled Downloads & Uploads**:
   - Downloads are contained within a dedicated sandboxed directory (`data/downloads`).
   - Blocks dangerous executable and script extensions (`.exe`, `.msi`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.reg`) and enforces `max_browser_download_size_mb`. Never launches downloads automatically.
   - Uploads enforce `PathPolicy`, allowed directories, path traversal prevention, file size limits (`max_browser_upload_size_mb`), explicit target binding, and sensitive upload confirmation tokens. Rejects `.exe`, `.pem`, `.key`, `.env`, `id_rsa`.
9. **Controlled Bounded Wait**:
   - `browser.wait` permits only bounded operations (`wait_for_selector`, `wait_for_navigation`, `wait_for_load_state`, bounded duration) with a hard maximum timeout. No arbitrary JavaScript polling or infinite sleep.
10. **Keyboard Allowlist**:
    - Only 13 safe navigation and editing keys permitted: `ENTER`, `ESC`, `TAB`, `BACKSPACE`, `SPACE`, `ARROW_UP`, `ARROW_DOWN`, `ARROW_LEFT`, `ARROW_RIGHT`, `HOME`, `END`, `PAGE_UP`, `PAGE_DOWN`. Arbitrary keyboard injection is strictly rejected.
11. **Cancellation & Verification**:
    - Supports task cancellation via standard asyncio task cancellation and cleanup. Cancellation halts pending actions, runs cleanup, audits the event, and ensures BUDDY reports failure rather than false success.
    - Every state-changing action empirically verifies that the actual system state changed before reporting success. If the page does not change, `BrowserActionResult.success = False`.
12. **CAPTCHA & Challenge Behavior**:
   - Detects CAPTCHA challenges (`recaptcha`, `hcaptcha`, `cf-turnstile`).
   - Never attempts to bypass or solve CAPTCHAs. Pauses task and requests human interaction.

---

## 12. Contextual Awareness & Proactive Assistance (Loop 10)

### Subsystem Pipeline:
```text
ENVIRONMENT
     ↓
OBSERVERS (Foreground, Activity, Notification, Calendar, Scheduler)
     ↓
CONTEXT SNAPSHOT
     ↓
PRIVACY FILTER & SENSITIVE CONTEXT DETECTION
     ↓
TRIGGER ENGINE (Deterministic rule-based matching)
     ↓
RELEVANCE ENGINE (Deterministic 0.0 - 1.0 scoring)
     ↓
INTERRUPTION POLICY (Quiet Hours + Cooldown + Hourly Budget)
     ↓
SUGGESTION / ACTION PROPOSAL
     ↓
SECURITY POLICY
     ↓
TOOL REGISTRY
     ↓
TOOL EXECUTOR
     ↓
PERMISSION ENGINE (Risk Tiers 0-4)
     ↓
CONFIRMATION / AUTHENTICATION (Mandatory for High/Destructive Actions)
     ↓
EXECUTION → VERIFICATION → AUDIT TRAIL
```

### Core Security Principle:
> **Context is DATA. Context is NOT AUTHORITY.**
>
> No observer, notification, calendar event, window title, browser page, or memory record may modify security policy, grant permissions, bypass confirmation or authentication, change tool risk levels, or directly invoke operating system commands. All actions MUST pass through `ToolRegistry` and `ToolExecutor`.

### Privacy Boundary & No-Surveillance Guarantee:
**BUDDY does not continuously monitor the user.**
- **NO Keylogger**: Never captures individual keystrokes, key sequences, or typed characters.
- **NO Clipboard Logger**: Never inspects, logs, or stores clipboard contents.
- **NO Hidden Microphone Capture**: Audio capture occurs exclusively during active wake word / voice pipeline interactions.
- **NO Continuous Screenshots**: Screen captures occur only on explicit user request or active vision tool execution.
- **NO Credential Extraction**: Password manager windows, PIN dialogs, banking pages, and Windows UAC prompts trigger immediate sensitive-context redaction and proactive suppression.
- **Ephemeral Retention**: Context snapshots are bounded in-memory structures subject to short TTL expiration.

### Subsystem Modules (`app/context_awareness/`):
1. **Foreground Observer** (`foreground.py`): Queries active window title and process name via narrow Win32 APIs (`GetForegroundWindow`, `GetWindowTextW`). Window titles are redacted upon detecting sensitive application keywords.
2. **Activity Observer** (`activity.py`): Classifies coarse user state (`ACTIVE`, `IDLE`, `AWAY`, `UNKNOWN`) based strictly on idle duration (`GetLastInputInfo`) without any behavioral surveillance.
3. **Notification Observer** (`notifications.py`): Ingests OS/app notifications via provider interfaces (`NotificationProvider`). All notification data is classified as `UNTRUSTED EXTERNAL DATA` and cannot become execution instructions.
4. **Calendar Provider & Observer** (`calendar.py`): Discovers approaching calendar events within configurable time horizons. Content is untrusted data and cannot authorize actions.
5. **Contextual Scheduler** (`scheduler.py`): Supports one-time, recurring, and relative reminders with event windows, cancellation, and missed-event handling. Dispatches triggers, never direct OS commands.
6. **Trigger Engine** (`triggers.py`): Deterministic rule evaluator mapping context triggers to candidate suggestions or action proposals.
7. **Relevance Engine** (`relevance.py`): Computes 0.0 to 1.0 relevance scores based on activity state, task synergy, and trigger weights without requiring an LLM.
8. **Interruption Management** (`interruption.py`): Enforces quiet hours (e.g. 22:00 -> 07:00), per-fingerprint cooldowns (e.g. 600s), and hourly interruption limits (e.g. max 6/hour).
9. **Deduplication Manager** (`deduplication.py`): Computes SHA-256 fingerprints across trigger types, payload keys, and time buckets to prevent notification spam.
10. **Proactive Action Dispatcher** (`proactive.py`): Exclusively routes action proposals to `ToolExecutor`. Destructive or dangerous actions (file deletion, app termination, shell execution) strictly require confirmation or authentication and are NEVER auto-executed.

---

## 13. Advanced Reasoning & Long-Horizon Agent Orchestration (Loop 12)

### Architecture Pipeline:
```text
USER OBJECTIVE
     ↓
GOAL & REQUIREMENT EXTRACTOR (Deterministic functional requirements, constraints, assumptions)
     ↓
AMBIGUITY DETECTOR (Target ambiguity, destructive actions, missing parameters)
     ├── Blocking Clarification Request (Pauses execution for user response)
     ↓
LONG-HORIZON PLANNER (Directed Acyclic Graph with cycle prevention & dependencies)
     ↓
PLAN QUALITY & SAFETY EVALUATOR (Tool existence, risk tier consistency, verification coverage)
     ↓
EXPLAINABLE CONFIDENCE EVALUATOR (Deterministic scoring with explainable reason codes)
     ↓
LONG-HORIZON ORCHESTRATOR
     ├── TASK BUDGET CONTROLLER (Step limits, duration bounds, tool count, replan limits)
     ├── MILESTONE & CHECKPOINT MANAGER (Progress tracking; zero secret persistence)
     ├── PARALLEL EXECUTION COORDINATOR (Safe read-only concurrent steps; serialization for writes)
     └── SPECIALIST ROLES (Researcher, Coder, Browser, Computer, Verifier with bounded capabilities)
     ↓
TOOL EXECUTOR (All steps routed through Loop 4 permission, confirmation & verification engines)
     ↓
INTERMEDIATE OUTCOME EVALUATOR (Empirical result verification)
     ├── SUCCESS → Update Milestones & Record Checkpoint
     ├── USER_REQUIRED → Pause for User Confirmation / Auth
     ├── SECURITY_BLOCK → Fail Closed / Blocked
     └── RECOVERABLE_FAILURE → Failure Diagnostician → Safe Replanner (Bounded adaptation)
```

### Core Tenets of Loop 12 Orchestration:
1. **Strongly Typed Goal Model**: Goals, subgoals, milestones, checkpoints, and budgets are strongly validated Pydantic models.
2. **Ambiguity Before Execution**: Ambiguous, destructive, or missing targets prompt structured clarification requests rather than guessing.
3. **DAG-Based Planning**: Multi-step workflows model explicit dependencies without cycles; every state-modifying action requires empirical verification coverage.
4. **Explainable Confidence**: Confidence scores (0.0 - 1.0) and levels (`VERY_LOW` to `VERY_HIGH`) are accompanied by explicit reason codes.
5. **No Secret Persistence**: Checkpoints and milestone logs explicitly exclude credentials, confirmation tokens, or sensitive values.
6. **Task Budgets**: Hard deterministic bounds enforce maximum steps, duration, tool counts, and replans to prevent runaway execution.
7. **Specialist Roles with Bounded Capabilities**: Roles (`ResearcherRole`, `CoderRole`, `BrowserRole`, `ComputerRole`, `VerifierRole`) enforce principle of least privilege.

