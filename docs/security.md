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
