# BUDDY Tool System Specification (Loop 4)

## 1. Tool Architecture

BUDDY implements a strictly sandboxed, permission-gated tool execution layer. The AI model never directly invokes operating system APIs, shells, or Python code.

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

> **Fundamental Principle:**
> **The AI may REQUEST a tool. The AI may NOT directly execute a tool.**
> BUDDY never executes arbitrary AI-generated code, arbitrary shell commands, or arbitrary Python scripts.

---

## 2. Core Tool Models

Located in `app/tools/models.py`:

- **`ToolRiskLevel`**:
  - `0 = SAFE`: Read-only queries with no local state change (e.g. system info, battery, volume query).
  - `1 = LOW`: Minor non-destructive local interactions (e.g. launch allowlisted Notepad, create file).
  - `2 = MODERATE`: State mutations requiring explicit user confirmation (e.g. rename file, move file, close application).
  - `3 = HIGH`: Destructive or broad changes requiring two-step confirmation.
  - `4 = CRITICAL`: System-wide alterations requiring authentication + explicit confirmation.
- **`ToolPermissionLevel`**: `NONE`, `SESSION`, `CONFIRM`, `AUTHENTICATE`.
- **`ToolDefinition`**: Immutable specification with input/output JSON schemas, risk tier, confirmation flag, and execution timeout.
- **`ToolRequest`**: Unique request with request ID, target tool name, structured parameters, and originator.
- **`ToolResult`**: Strongly typed execution outcome with `success`, `verified`, terminal `status`, `output`, `error`, and latency.

---

## 3. Registered Safe Computer Control Tools

Every tool inherits from `Tool` (`app/tools/base.py`) and is registered in `ToolRegistry` (`app/tools/registry.py`).

| Tool Identifier | Module | Risk Tier | Requires Confirmation | Description |
|---|---|---|---|---|
| `system.get_info` | `app.tools.system` | SAFE (0) | No | OS, architecture, Python version, CPU cores, RAM metrics. |
| `system.get_battery` | `app.tools.system` | SAFE (0) | No | Battery percentage, charging status, time remaining. |
| `system.get_volume` | `app.tools.system` | SAFE (0) | No | Current audio master volume level (0-100). |
| `system.set_volume` | `app.tools.system` | LOW (1) | No | Bounded volume setting (0-100) with read-back verification. |
| `app.list` | `app.tools.applications` | SAFE (0) | No | Safe running process list (name, PID, status). No tokens or env vars. |
| `app.open` | `app.tools.applications` | LOW (1) | No | Launch allowlisted app (`notepad`, `calculator`, `paint`, `explorer`). |
| `app.close` | `app.tools.applications` | MODERATE (2) | **Yes** | Graceful termination of allowlisted process with process check verification. |
| `file.search` | `app.tools.filesystem` | LOW (1) | No | Search for files matching glob pattern inside authorized roots. |
| `file.read` | `app.tools.filesystem` | LOW (1) | No | Read text content within authorized roots (1MB size bound). |
| `file.create` | `app.tools.filesystem` | LOW (1) | No | Create new file with SHA-256 hash and size verification. |
| `file.rename` | `app.tools.filesystem` | MODERATE (2) | **Yes** | Rename file with path validation on source and destination. |
| `file.copy` | `app.tools.filesystem` | MODERATE (2) | **Yes** | Copy file within authorized roots with destination verification. |
| `file.move` | `app.tools.filesystem` | MODERATE (2) | **Yes** | Move file within authorized roots with source removal verification. |

---

## 4. Path Security & Sandboxing (`PathPolicy`)

Located in `app/security/path_policy.py`:

- **Authorized Roots**: strictly constrained to user Documents, Downloads, Desktop (plus configurable test roots).
- **Path Traversal Defense**: detects and blocks `..`, `../`, `..\`, mixed slashes, and relative escaping.
- **Windows Device Path Defense**: blocks reserved device stems (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, `\\.\`, `\\?\`).
- **UNC Path Defense**: blocks network shares (`\\server\share`).
- **Protected File Defense**: blocks access to `.env`, `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.git`, private keys (`*.key`, `*.pem`), credentials, SAM, and browser databases.
- **Symlink & Junction Defense**: resolves canonical path (`resolve()`) and asserts canonical target is within authorized root.

---

## 5. Verification Engine

Execution alone does not equal success. Every tool implements `verify()`:
- `app.open`: executes binary, then polls process table to empirically verify the process exists.
- `app.close`: issues termination signal, then confirms the process has completely exited.
- `file.create`: writes file, then reads bytes from disk to confirm existence, size, and SHA-256 digest match.
- `system.set_volume`: adjusts level, then reads back actual volume to verify requested state was applied.

If verification fails:
- `ToolResult.success = False`
- `ToolResult.verified = False`
- `ToolResult.status = VERIFICATION_FAILED`
- The AI is informed that verification failed and never reports false completion to the user.

---

## 6. Audit Logging

Every tool request emits structured audit records to `data/audit.log` and standard logging:
- Automatic masking of passwords, tokens, API keys, and sensitive parameters.
- Audit trail includes: `timestamp`, `request_id`, `conversation_id`, `tool_name`, `risk_level`, `permission_decision`, `confirmation_decision`, `execution_status`, `verified`, `execution_latency`, `error_category`.

---

## 7. Controlled Mouse & Keyboard Interaction Tools (Loop 6)

| Tool Name | Module | Risk Level | Confirmation? | Description |
|---|---|---|---|---|
| `mouse.click` | `app.tools.mouse` | MODERATE (2) | **Yes** | Click a verified UI element. Requires valid `target_id` and detection fingerprint. |
| `mouse.double_click` | `app.tools.mouse` | MODERATE (2) | **Yes** | Double-click a verified UI element on screen. |
| `mouse.scroll` | `app.tools.mouse` | LOW (1) | No | Scroll active window vertically by non-zero lines (bounded to -100..100). |
| `keyboard.key_press` | `app.tools.keyboard` | LOW (1) | No | Press a single allowlisted navigation key (e.g. ENTER, ESC, TAB, SPACE, ARROWS). |
| `keyboard.type_text` | `app.tools.keyboard` | LOW (1) | No | Type user-approved harmless text into focused element. Passwords/tokens rejected. |

### Interaction Models & Proposals
- `UIActionProposal`: Produced from vision analysis and user intent. Links action to an empirically verified `VisionTarget`.
- `InteractionRequest`: Strictly bound instruction with verified `(x, y)` coordinates, `target_id`, `screen_fingerprint`, and bounds validation.
- Direct raw coordinate injection without a verified target is strictly prohibited.
- Typed text is never persisted or logged in audit records or event payloads.

---

## 8. Agentic Task Planning & Multi-Step Execution (Loop 7)

### Agent Core Modules (`app.agent`)
| Component | Module | Responsibility |
|---|---|---|
| `TaskPlanner` | `app.agent.planner` | Decomposes high-level natural language user goals into structured `Task` models using restricted prompts. Never executes code. |
| `TaskPlanValidator` | `app.agent.validator` | Validates step limits, DAG dependency cycles, tool existence, argument injection patterns, and synchronizes risk tiers from `ToolRegistry`. |
| `TaskExecutor` | `app.agent.executor` | Sequentially executes steps through `ToolExecutor`, pauses for confirmation/auth, executes bounded retries, and triggers adaptive re-planning. |
| `AgentService` | `app.agent.service` | High-level facade tying planning, validation, execution, state machine transitions, and EventBus lifecycle events together. |
| `TaskContext` | `app.agent.context` | Ephemeral, privacy-sanitized execution state (active applications, screen fingerprints, discovered targets, completed step records). |

### Multi-Step Execution Lifecycle
1. **Planning**: `AgentService.plan_goal(goal)` -> `TaskPlanner.plan(goal, context)`
2. **Validation**: `TaskPlanValidator.validate_plan(task)` (Enforces DAG dependencies, rejects forbidden tools, syncs risk levels)
3. **Execution**: `TaskExecutor.execute_task(task, confirmation_token, auth_credential)`
4. **Step Gating**: Every step independently passes `PermissionEngine`, `ConfirmationManager`, and `Authenticator`.
5. **Adaptive Recovery**: When `SCREEN_CHANGED` or `TARGET_NOT_FOUND` occurs, the executor triggers re-planning (up to 2 times).
6. **Verification**: Only steps with `verified=True` are counted toward success. Missing targets stop the task honestly without false success claims.

---

## 9. Long-Term Memory & Contextual Personalization (Loop 8)

### Core Principle
> **MEMORY IS CONTEXT, NOT AUTHORITY.**
> Memory stored in BUDDY provides personalized context (e.g. preferred applications, user name, workflow styles) but **never** authorizes computer actions, modifies `ToolRiskLevel`, bypasses confirmation tokens, alters authentication requirements, or overrides system safety instructions.

### Memory Architecture Components (`app.memory`)
| Component | Module | Responsibility |
|---|---|---|
| `MemoryManager` | `app.memory.manager` | High-level facade for `remember()`, `recall()`, `forget()`, `list_memories()`, command parsing, and XML prompt injection defense wrapping. |
| `MemoryService` | `app.memory.service` | Business logic orchestrating candidate creation, validation against `MemoryPolicy`, deterministic conflict resolution, and bounded retrieval. |
| `MemoryPolicy` | `app.memory.policy` | Conservative policy enforcing rejection of secrets (passwords, PINs, OTPs, API keys, JWTs, card numbers) and prompt override instructions. |
| `MemoryStore` / `SqliteMemoryStore` | `app.memory.store` | Parameterized SQLite persistent backend with WAL mode, schema versioning, bounds enforcement, and tokenized keyword search. |
| `MemoryEncryptor` / `FernetMemoryEncryptor` | `app.memory.encryption` | Encryption abstraction providing authenticated AES-128-CBC + HMAC-SHA256 encryption for sensitive memories with fail-closed key loading. |
| `MemoryRecord` | `app.memory.models` | Strict Pydantic model (`extra="forbid"`) with memory type, source, sensitivity, status, confidence, timestamps, and metadata. |

### Memory Gating & Tool Execution Interaction
- Memory is injected into AI prompts strictly inside `<recalled_context>` tags as untrusted data.
- Tool requests generated by the AI after recalling memories are still subject to the full Loop 4-7 security pipeline:
  `AI Tool Request -> ToolRegistry -> PermissionEngine -> ConfirmationManager / Authenticator -> ToolExecutor -> Verification`.
- Any memory instructing the AI that "actions are permanently authorized without confirmation" is rejected by policy or treated as inert text with zero security privilege.

---

## 10. Browser Automation Tools (Loop 9)

All browser automation tools flow through `ToolRegistry` and `ToolExecutor`. The AI planner never accesses Playwright directly.

### Registered Browser Tools
| Tool Name | Risk Tier | Permission | Confirmation | Timeout | Description |
|---|---|---|---|---|---|
| `browser.open` | LOW | NONE | No | 30.0s | Launch clean, isolated browser session with clean automation profile. |
| `browser.close` | LOW | NONE | No | 10.0s | Close active browser session and release process resources. |
| `browser.new_tab` | LOW | NONE | No | 20.0s | Create a new tab within active browser session (bounds enforced). |
| `browser.switch_tab` | LOW | NONE | No | 10.0s | Switch active focus to a specified tab ID. |
| `browser.navigate` | LOW | NONE | No | 35.0s | Navigate active tab to validated URL with SSRF protection. |
| `browser.back` | SAFE | NONE | No | 15.0s | Navigate back in active tab browsing history. |
| `browser.forward` | SAFE | NONE | No | 15.0s | Navigate forward in active tab browsing history. |
| `browser.reload` | LOW | NONE | No | 20.0s | Reload the current active page. |
| `browser.inspect` | SAFE | NONE | No | 10.0s | Inspect page structure, compute fingerprint, and detect sensitive forms. |
| `browser.find` | SAFE | NONE | No | 15.0s | Discover interactive target element with confidence scoring. |
| `browser.click` | LOW | NONE | No | 15.0s | Click verified target element with fingerprint staleness check. |
| `browser.double_click` | LOW | NONE | No | 15.0s | Double click verified element with fingerprint staleness check. |
| `browser.type` | LOW / HIGH | NONE / CONFIRM | Sensitive fields only | 15.0s | Type text into input field. Never auto-types credentials. |
| `browser.press_key` | LOW | NONE | No | 10.0s | Press allowlisted key (`ENTER`, `TAB`, `ESC`, arrow keys). |
| `browser.select` | LOW | NONE | No | 15.0s | Select dropdown or `<select>` menu option. |
| `browser.scroll` | SAFE | NONE | No | 10.0s | Scroll active page (up or down). |
| `browser.extract_text` | SAFE | NONE | No | 15.0s | Extract visible text, bounded and wrapped in security tags. |
| `browser.screenshot` | SAFE | NONE | No | 15.0s | In-memory base64 screenshot of active browser tab. |
| `browser.download` | MODERATE | CONFIRM | Yes | 60.0s | Download file to sandboxed directory. Blocks `.exe`/`.bat`/`.ps1`. |
| `browser.upload` | MODERATE | CONFIRM | Yes | 30.0s | Upload sandboxed local file. Rejects `.key`/`.pem`/`.env`. |
| `browser.wait` | SAFE | NONE | No | 15.0s | Wait bounded duration (up to 10 seconds). |

### Security Gating & Verification Contract
- `ToolExecutor` validates input schemas with Pydantic `extra="forbid"`.
- Browser actions re-evaluate URLs against `BrowserPolicy` on redirects.
- Every state-changing action triggers post-execution empirical verification.
- Passwords and sensitive input values are redacted from logs, events, and audit trails.

