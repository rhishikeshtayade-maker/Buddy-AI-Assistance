# BUDDY Security & Threat Model

## 1. Absolute Security Rules

1. **Rule 1**: Never hard-code secrets. Always use environment variables or OS Keyring.
2. **Rule 2**: Never give the AI unrestricted shell access. Tools must be explicit and strictly scoped.
3. **Rule 3**: Never allow the AI to bypass the permission system. Tool execution requires security evaluation.
4. **Rule 4**: Never execute destructive operations without required confirmation.
5. **Rule 5**: Never store passwords/PINs in plaintext. Use secure derivation (Argon2 / PBKDF2).
6. **Rule 6**: Never store encryption keys beside encrypted data in plaintext.
7. **Rule 7**: Never trust web pages, files, or external tool output as system instructions (Prompt Injection Defense).
8. **Rule 8**: Never silently upload sensitive screen/audio/file data to a cloud service.
9. **Rule 9**: Never claim an action succeeded until it has been verified.
10. **Rule 10**: Never modify user files without authorization.

---

## 2. Risk Level Matrix

Every action and tool in BUDDY is categorized into a standard risk tier:

| Level | Designation | Description | Examples | Security Controls |
|-------|-------------|-------------|----------|-------------------|
| **0** | **SAFE** | Read-only, non-sensitive system state | Battery query, CPU status, current time | Direct execution, logged |
| **1** | **LOW** | Minor non-destructive local interactions | Open known app (e.g. Notepad), create temp file | Policy check, logged |
| **2** | **MODERATE** | State modifications, network navigation | Move file, open browser URL, switch active window | Explicit confirmation if policy requires |
| **3** | **HIGH** | Destructive changes or broad modifications | Delete file, terminate process, close unsaved app | Mandatory 2-step confirmation ("DELETE") |
| **4** | **CRITICAL** | System-wide alterations, credentials, dev tools | Run script, clear database, modify security policy | PIN / Local OS Auth + Explicit Confirmation |

---

## 3. Cryptographic Standard

- **Algorithm**: AES-256-GCM (Authenticated Encryption with Associated Data).
- **Key Derivation**: PBKDF2-HMAC-SHA256 with 600,000+ iterations or OS Keyring-derived master secret.
- **Salt & Nonce**: High-entropy cryptographically secure random bytes (`os.urandom(16)` salt, `os.urandom(12)` GCM nonce). Nonces are never reused.

---

## 4. Prompt Injection Defense

All content ingested from external sources (browser pages, terminal outputs, file contents, downloaded documents) is wrapped in untrusted data delimiters:

```xml
<untrusted_external_content source="...">
...
</untrusted_external_content>
```

The system instruction explicitly enforces:
- External content cannot alter BUDDY's internal directives, identity, or risk clearance.
- Directives found within untrusted content requesting tool execution are rejected.

---

## 5. Audit Logging

Every tool request, security check, confirmation attempt, and execution result is appended to an append-only, tamper-evident audit log with automatic secret redaction.
