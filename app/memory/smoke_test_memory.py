"""BUDDY Real Windows Memory Subsystem Smoke Test.

Validates that:
1. SQLite memory database is created on the real Windows filesystem.
2. Harmless user preferences are saved and retrieved.
3. Database persistence works across restarts (closing & reopening store).
4. Updates, conflict resolution, and deletions succeed.
5. Secrets (passwords, API keys) are strictly rejected and never saved.
6. Temporary test files are cleaned up reliably.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time

from app.core.config import BuddyConfig
from app.core.exceptions import MemoryPolicyViolationError
from app.memory.manager import MemoryManager
from app.memory.models import MemorySource, MemoryType
from app.memory.policy import MemoryPolicy
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore


async def run_windows_memory_smoke_test() -> int:
    print("=" * 72)
    print("        BUDDY — LONG-TERM MEMORY & CONTEXTUAL PERSONALIZATION SMOKE TEST")
    print("                       Mode: REAL WINDOWS DISK")
    print("=" * 72)

    test_db_path = Path("data/smoke_test_memory.db")
    if test_db_path.exists():
        test_db_path.unlink()

    config = BuddyConfig(
        memory_database_path=test_db_path,
        memory_max_size_mb=10,
        memory_max_records=50,
    )

    try:
        # Step 1: Initialize Store and Service
        print("\n[1/6] Initializing real Windows SQLite memory store at '%s'..." % test_db_path)
        store = SqliteMemoryStore(db_path=test_db_path)
        policy = MemoryPolicy(config)
        service = MemoryService(store=store, policy=policy, config=config)
        manager = MemoryManager(service=service, config=config)

        # Step 2: Store harmless preference
        print("[2/6] Storing user preference: 'User preferred editor is VS Code'...")
        rec = await manager.remember(
            content="User preferred editor is VS Code",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
        print("      Record saved with ID: %s (version: %d)" % (rec.memory_id, rec.version))

        # Step 3: Retrieve preference
        recalled = await manager.recall("editor")
        assert len(recalled) == 1, "Expected 1 recalled record, got %d" % len(recalled)
        print("      Successfully recalled memory: '%s'" % recalled[0].content)

        # Step 4: Simulate Application Restart (close store & reopen)
        print("[3/6] Simulating application restart: closing database and reopening...")
        store.close()

        store2 = SqliteMemoryStore(db_path=test_db_path)
        service2 = MemoryService(store=store2, policy=policy, config=config)
        manager2 = MemoryManager(service=service2, config=config)

        recalled_reopened = await manager2.recall("editor")
        assert len(recalled_reopened) == 1, "Expected memory to persist across restart!"
        print("      Persistence verified across restart! Memory: '%s'" % recalled_reopened[0].content)

        # Step 5: Update preference (conflict handling)
        print("[4/6] Updating user preference: 'User preferred editor is Sublime'...")
        rec2 = await manager2.remember(
            content="User preferred editor is Sublime",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
        recalled_updated = await manager2.recall("editor")
        assert len(recalled_updated) == 1
        assert recalled_updated[0].content == "User preferred editor is Sublime"
        print("      Conflict resolved! Active preference updated to: '%s'" % recalled_updated[0].content)

        # Step 6: Delete preference
        print("[5/6] Forgetting preference...")
        forgotten = await manager2.forget("Sublime")
        assert forgotten is True
        recalled_deleted = await manager2.recall("editor")
        assert len(recalled_deleted) == 0
        print("      Memory successfully deleted and verified absent.")

        # Step 7: Attempt secret storage and verify rejection
        print("[6/6] Testing conservative secret rejection (password / API key)...")
        rejected_count = 0
        for secret_sample in [
            "My password is SecretPass1234!",
            "My API key is sk-1234567890abcdef1234567890",
            "My login pin is 9021",
        ]:
            try:
                await manager2.remember(secret_sample)
                print("      ERROR: Secret '%s' was NOT rejected!" % secret_sample)
                return 1
            except MemoryPolicyViolationError as pe:
                rejected_count += 1
                print("      Blocked secret correctly: %s" % pe.message)

        assert rejected_count == 3
        print("      All secret attempts successfully rejected!")

        store2.close()

        print("\n" + "=" * 72)
        print("         ALL REAL WINDOWS MEMORY SMOKE CHECKS PASSED!           ")
        print("=" * 72)
        return 0

    finally:
        # Cleanup test database files
        for p in [test_db_path, Path(str(test_db_path) + "-wal"), Path(str(test_db_path) + "-shm")]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(asyncio.run(run_windows_memory_smoke_test()))
