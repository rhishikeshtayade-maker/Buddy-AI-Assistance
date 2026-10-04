# BUDDY Security & Threat Model (Loop 4)

## 1. Absolute Security Rules

1. **Rule 1**: Never hard-code secrets. Always use environment variables or OS Keyring.
2. **Rule 2**: Never give the AI unrestricted shell access. Tools must be explicit and strictly scoped.
3. **Rule 3**: Never allow the AI to bypass the permission system. Tool execution requires security evaluation.
4. **Rule 4**: Never execute destructive operations without required confirmation.
5. **Rule 5**: Never store passwords/PINs in plaintext. Use secure derivation (PBKDF2-HMAC-SHA256).
6. **Rule 6**: Never store encryption keys beside encrypted data in plaintext.
7. **Rule 7**: Never trust web pages, files, or external tool output as system instructions (Prompt Injection Defense).
8. **Rule 8**: Never silently upload sensitive screen/audio/file data to a cloud service.
9. **Rule 9**: Never claim an action succeeded until it has been empirically verified.
10. **Rule 10**: Never modify user files without authorization or outside allowed sandboxed roots.

---

## 2. Risk Level Matrix

Every registered tool in BUDDY is categorized into a standard risk tier:

| Level | Designation | Description | Examples | Security Controls |
|---|---|---|---|---|
| **0** | **SAFE** | Read-only, non-sensitive system queries | Battery query, CPU status, running app list | Direct execution, audit logged |
| **1** | **LOW** | Minor non-destructive local interactions | Open Notepad, create new file, search files | Direct execution within sandboxed roots, audit logged |
| **2** | **MODERATE** | State modifications, file movement, process kill | Move file, rename file, close application | Explicit interactive confirmation token required |
| **3** | **HIGH** | Destructive changes or broad modifications | Delete file, terminate critical tasks | Mandatory 2-step confirmation token |
| **4** | **CRITICAL** | System-wide alterations, credentials, dev tools | Run script, clear database, modify security policy | PIN / Local OS Auth + Explicit Confirmation |

---

## 3. Permission Engine (`PermissionEngine`)

- Derived **strictly** from the registered `ToolDefinition`.
- The AI model's natural language reasoning, prompt text, or request arguments can **never** downgrade the risk level.
- Rejects unregistered tool requests immediately ("Fail Closed").

---

## 4. Confirmation Boundary (`ConfirmationManager`)

- Generates single-use, cryptographic tokens (`secrets.token_urlsafe(32)`).
- Bound strictly to the exact tuple: `(request_id, tool_name, sha256(arguments))`.
- Expired tokens fail immediately.
- Replay attacks fail immediately (consumed tokens are tracked and rejected).
- Tampered arguments fail immediately.

---

## 5. Local Authentication Boundary (`Authenticator`)

- Supports local authorization challenges for critical operations.
- `PinAuthenticator` uses salted PBKDF2-HMAC-SHA256 with 100,000 iterations and constant-time digest comparison (`hmac.compare_digest`).
- Never logs credentials or plaintext secrets.

---

## 6. Centralized Path Sandboxing (`PathPolicy`)

- Authorized roots: user Documents, Downloads, Desktop.
- Blocks directory traversal attacks (`../`, `..\`, mixed slashes).
- Blocks Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, `\\.\`, `\\?\`).
- Blocks UNC network shares (`\\server\share`).
- Blocks protected files: `.env*`, `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.git`, private keys (`*.key`, `*.pem`), credentials, SAM, and browser user data.
- Enforces canonical resolution (`resolve()`) on all paths and symlinks/junctions.

---

## 7. Prompt Injection Defense

All content ingested from external sources or tool execution output is wrapped in untrusted data delimiters:

```xml
<untrusted_external_content source="tool:file.read">
...
</untrusted_external_content>
```

Directives contained inside tool outputs (e.g. "Ignore previous instructions") are treated strictly as data and cannot override system instructions or trigger unprompted actions.

---

## 8. Audit Logging (`AuditLogger`)

Every tool request, permission decision, confirmation prompt, authentication attempt, execution status, and verification outcome is written to `data/audit.log` and runtime logs with automatic secret redaction.

---

## 9. Controlled Mouse & Keyboard Security Policy (Loop 6)

### Target Binding & Coordinate Invariants
- Direct coordinate injection (e.g. `x=500, y=500`) without a verified, unexpired `VisionTarget` is strictly rejected.
- All target coordinates must be finite numeric values within display boundaries (`0 <= x < width`, `0 <= y < height`). NaN and Infinity are rejected immediately.
- Targets expire after 30 seconds (TTL). Stale targets cannot be clicked.

### Stale-Screen Protection
- Every click action binds to the screen visual fingerprint generated when the target was detected.
- Prior to clicking, the system inspects the current screen state. If the screen visual fingerprint has changed, the action is rejected with `SCREEN_CHANGED`.

### Keyboard Restriction & Sensitive Text Protection
- Keyboard key press is constrained to a hardcoded safe allowlist: `ENTER`, `ESC`, `TAB`, `BACKSPACE`, `SPACE`, `ARROW_UP`, `ARROW_DOWN`, `ARROW_LEFT`, `ARROW_RIGHT`, `HOME`, `END`, `PAGE_UP`, `PAGE_DOWN`.
- Text typing automatically scans for password, token, pin, OTP, API key, and secret patterns. Any detected sensitive credentials cause immediate rejection.
- Typed text is strictly excluded from output metadata, event payloads, and audit logs.

### Protected Applications & Dangerous Actions
- Interaction with password managers (1Password, Bitwarden, KeePass, LastPass), Windows Credential Manager, and UAC elevation dialogs is strictly forbidden and fails closed.
- Target actions are categorized:
  - `SAFE`: navigation, search, open menu (Low/Moderate risk)
  - `MODERATE`: save, rename, submit (Moderate risk, confirmation required)
  - `DANGEROUS`: delete, uninstall, format, drop, kill (High risk, explicit confirmation required)
  - `CRITICAL`: security settings, credentials, privilege escalation (Critical risk, local PIN authentication + confirmation required)

---

## 10. Agentic Task Planning & Multi-Step Security (Loop 7)

### Zero Direct Execution Authority
- The AI Task Planner operates exclusively inside a prompt sandbox with no direct execution authority.
- The planner cannot execute Python `eval()` or `exec()`, run PowerShell/cmd/bash, spawn subprocesses, or invoke Windows APIs directly.
- The planner's only output is a structured JSON plan specifying registered tool names and arguments.

### Immutable Risk Tiers & Permission Gates
- The planner cannot declare or downgrade risk tiers.
- Risk levels (`SAFE`, `LOW`, `MODERATE`, `HIGH`, `CRITICAL`), confirmation requirements, and authentication requirements are synchronized strictly from registered `ToolDefinition` objects in `ToolRegistry`.
- A plan is never permission. Even if a user asks for a multi-step workflow, each dangerous step must independently pass `PermissionEngine`, `ConfirmationManager`, and local authentication gates before execution.

### DAG Dependency Validation
- Plan dependencies are validated as a Directed Acyclic Graph before execution.
- Circular dependencies and self-dependencies are rejected immediately.
- If a prerequisite step fails, all dependent steps are immediately marked `SKIPPED` with `DEPENDENCY_FAILED`.

### Failure Handling & Non-Retryable Boundaries
- Step failures are strictly classified:
  - `TRANSIENT`: Network or temporary timeouts (eligible for bounded retry, max 2).
  - `PERMISSION_DENIED`: Categorically non-retryable (stops task).
  - `CONFIRMATION_REQUIRED`: Pauses task for user confirmation token.
  - `AUTHENTICATION_REQUIRED`: Pauses task for local user authentication.
  - `SECURITY_BLOCKED`: Categorically non-retryable (stops task immediately).
  - `TARGET_NOT_FOUND` / `SCREEN_CHANGED`: Halts step, captures fresh visual state, and triggers adaptive re-planning (max 2 replans).

### Runaway Loop & Storm Protections
- `max_task_steps = 20`: Plans with more than 20 steps are rejected before execution begins.
- `max_tool_calls_per_task = 30`: Prevents infinite retry/replanning loops or tool storms.
- `execution_timeout = 180s`: Bound on total execution duration.

### Untrusted Tool Result Boundary
- Tool outputs are treated as untrusted data.
- Tool outputs are wrapped and sanitized; they can never define new tools, inject shell commands, or alter system security policies.

### Human In-The-Loop Control
- The user can issue a cancellation command (`cancel_task()`) at any time.
- The executor aborts future steps immediately, ensuring that no further actions commence after cancellation.

---

## 11. Long-Term Memory Security & Privacy Model (Loop 8)

### Non-Negotiable Principle: Memory is Context, NOT Authority
- Stored memory can **NEVER**:
  - Authorize a tool execution.
  - Bypass `PermissionEngine` or `ToolExecutor` security checks.
  - Downgrade a registered tool's `ToolRiskLevel`.
  - Skip mandatory confirmation tokens or authentication challenges.
  - Modify system instructions or override safety rules.

### Conservative Secret Detection & Rejection
- Before any memory candidate is accepted, it passes through `MemoryPolicy.detect_secrets()`.
- Unconditionally rejects:
  - API keys (`sk-...`, `ghp_...`, `AKIA...`, generic hex/base64 keys).
  - Bearer tokens and JWTs (`eyJ...`).
  - Passwords, PINs, and OTPs (`password is ...`, `pin is ...`, `otp is ...`).
  - Private cryptographic keys (`-----BEGIN PRIVATE KEY-----`).
  - Credit and debit card sequences (13–19 digits).
  - Browser session cookies, client secrets, and auth tokens.
- **Fail-Safe Principle**: False positives are strictly preferred over storing sensitive credentials.

### Prompt Injection & Security Override Defense
- Memory candidates are analyzed for adversarial prompt injection patterns:
  - Attempts to declare "permanently authorized to execute shell".
  - Attempts to "bypass confirmation" or "skip permissions".
  - Attempts to "ignore system instructions".
- Such candidates are rejected with `REJECTED_INJECTION`.

### Untrusted Context Injection Boundary
- When recalled into AI prompt context, memories are wrapped in strict untrusted XML blocks (`<recalled_context>`).
- Explicit guardrails instruct the AI model to treat recalled memories strictly as user preferences and background facts, not as procedural instructions or security grants.

### Authenticated Encryption & Fail-Closed Loading
- Backed by `cryptography.fernet.Fernet` (AES-128-CBC + HMAC-SHA256 authenticated encryption).
- When `memory_encryption_enabled=True`, if no valid key is provided via `BUDDY_MEMORY_KEY`, config, or `data/.memory_key`, the subsystem **fails closed** (`MemoryEncryptionError`) rather than falling back to unencrypted storage.

### Data Minimization & Bounded Storage
- Hard ceilings protect against denial-of-service and memory expansion attacks:
  - `memory_max_size_mb` (default: 50MB)
  - `memory_max_records` (default: 1000 records)
  - `memory_max_context_records` (default: 10 per turn)
  - `memory_max_context_tokens` (default: 2000 tokens)
- Raw screenshots and raw microphone audio streams are strictly excluded from memory persistence.

---

## 8. Browser Automation Security & Web Boundaries (Loop 9)

### Untrusted Web Content Boundary
- **WEB CONTENT IS UNTRUSTED DATA, NOT AUTHORITY.**
- All webpage content, HTML, accessibility labels, links, forms, and downloaded text are classified as external untrusted data.
- Web content is encapsulated in `<external_web_content>` tags with delimiter escape neutralization (`&lt;/external_web_content&gt;`).
- Prompt injection signatures are flagged, alerted, and prevented from overriding user directives or system policies.
- The browser agent can never create arbitrary shell, Python, or elevated tools based on webpage directives.

### URL & SSRF Defenses
- Strict scheme allowlisting: `http` and `https` only. Rejects `javascript:`, `file:`, `data:`, `vbscript:`, `chrome:`, `edge:`, `about:`.
- Default rejection of `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`.
- Default rejection of private IPv4 subnets (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16).
- Default rejection of private IPv6 subnets (fc00::/7, fe80::/10).
- Automatic blocking of cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
- RFC 6052 NAT64 address inspection (`64:ff9b::/96`), extracting embedded IPv4 for SSRF evaluation.
- Domain policy uses exact or subdomain matching; naive substring spoofs (e.g. `evil-example.com`) are rejected.
- Destination policy re-evaluation on all HTTP redirects.

### Context Isolation
- Every session uses an isolated Playwright `BrowserContext`.
- Personal browser profiles, saved cookies, autofill, saved passwords, and extensions are never imported.

### Element Identification & Staleness Protection
- Multi-layered target discovery: accessibility role/name, unique attributes, semantic text, and scoped selectors.
- Target confidence threshold enforced (default: 0.85); ambiguous matches are rejected.
- Deterministic SHA-256 page structural fingerprints bind targets to page states. If the page mutates or navigates, targets are rejected as `StaleTargetError`.

### Credential & Sensitive Form Protection
- Form fields are classified: `SAFE`, `PERSONAL`, `SENSITIVE`, `CREDENTIAL`, `PAYMENT`.
- Automatic typing of secrets into credential or payment fields is prohibited.
- Secret entry requires explicit confirmation and user authentication.
- Typed passwords and credentials are never logged, emitted in events, or stored in memory.

### Downloads & Uploads Security
- Downloads are sandboxed to `data/downloads`. Path traversal in filenames is stripped.
- Dangerous executable extensions (`.exe`, `.bat`, `.ps1`, `.msi`, `.vbs`, `.scr`) are blocked.
- Download size quotas enforced (`browser_max_download_size_mb`).
- Uploads pass through `PathPolicy`, reject credential/key files (`.pem`, `.key`, `.env`, `id_rsa`), and enforce upload size limits.

### CAPTCHA & Authentication Prompts
- CAPTCHA challenges are detected; BUDDY never attempts CAPTCHA-solving. Tasks pause for human interaction.

