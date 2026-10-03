# BUDDY Tool System Specification

## 1. Tool Protocol Definition

Every capability in BUDDY is implemented as an isolated tool inheriting from `BaseTool`. Tools provide rigorous JSON Schema contracts, explicit risk definitions, and verification hooks.

```python
class BaseTool(ABC):
    name: str
    description: str
    risk_level: RiskLevel
    requires_confirmation: bool
    requires_auth: bool
    timeout_seconds: float = 10.0

    @abstractmethod
    async def execute(self, params: BaseModel) -> ToolResult:
        ...

    @abstractmethod
    async def verify(self, params: BaseModel, result: ToolResult) -> bool:
        ...
```

---

## 2. Core Tool Categories

1. **Applications (`app/tools/applications.py`)**:
   - `open_application`: Launch validated application path or standard registered app name.
   - `close_application`: Graceful or forced termination of target process.
   - `list_running_applications`: Enumerate active desktop windows and processes.

2. **Filesystem (`app/tools/filesystem.py`)**:
   - Sandboxed path traversal checks (`assert_path_allowed`).
   - `read_file`, `create_file`, `move_file`, `delete_file`.
   - Protected path blocklist (`C:\Windows`, `C:\Recovery`, `.env`, system libraries).

3. **System Diagnostics (`app/tools/system.py`)**:
   - `get_battery_status`, `get_cpu_ram_usage`, `get_storage_info`, `get_network_status`.

4. **Browser Controls (`app/tools/browser.py`)**:
   - `open_url`, `search_web`, `extract_page_text`.

5. **Developer Tools (`app/tools/developer.py`)**:
   - Approved build/test commands within verified project directories.
