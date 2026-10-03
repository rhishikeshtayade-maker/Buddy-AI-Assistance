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

BUDDY operates under strict states:
```
  [STARTING]
      |
      v
    [IDLE] <------------------------------------+
      |                                         |
      | (Wake word or Push-to-talk)             |
      v                                         |
  [LISTENING]                                   |
      |                                         |
      | (Speech captured & transcribed)         |
      v                                         |
  [THINKING]                                    |
      |                                         |
      +---> [Awaiting Confirmation / Auth]      |
      |               |                         |
      | (Approved)    | (Denied)                |
      v               v                         |
  [EXECUTING] --------+                         |
      |                                         |
      | (Response ready)                        |
      v                                         |
  [SPEAKING] -----------------------------------+
      |
      | (Fatal error or user interrupt)
      v
   [ERROR] ---> [IDLE]
```
