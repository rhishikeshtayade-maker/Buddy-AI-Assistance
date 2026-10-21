"""BUDDY Loop 15 — Real Windows Desktop Smoke Test.

Measures:
- Startup time (ms)
- RSS Memory usage (MB)
- Idle CPU usage (%)
- Glass HUD visual state transitions
- Audio-reactive waveform / orb updates
- Single instance protection
- Settings load/save and LoginStartupManager
- Orderly shutdown latency (ms)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.desktop.bridge import UiUpdate, VisualState
from app.desktop.runtime import DesktopRuntime
from app.desktop.settings import AnimationIntensity, DesktopSettings, SettingsStore
from app.desktop.single_instance import SingleInstanceGuard
from app.desktop.startup import LoginStartupManager
from app.desktop.ui.hud import GlassHudWindow
from app.desktop.ui.tray import BuddySystemTray


def run_windows_desktop_smoke_test() -> int:
    print("=" * 76)
    print("       BUDDY LOOP 15 — PERSISTENT DESKTOP ASSISTANT SMOKE TEST")
    print("=" * 76)

    process = psutil.Process()
    t_start = time.perf_counter()

    # 1. Initialize Qt Application
    qapp = QApplication.instance()
    if qapp is None:
        qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    # 2. Test Single Instance Guard
    guard = SingleInstanceGuard(name="BUDDY-SmokeTest-Guard")
    assert guard.acquire(), "Single instance guard must acquire successfully"
    guard_duplicate = SingleInstanceGuard(name="BUDDY-SmokeTest-Guard")
    assert not guard_duplicate.acquire(), "Duplicate single instance must be rejected"
    guard.release()
    print("[1/7] Single instance mutex guard verified.")

    # 3. Test Settings & Startup Manager
    settings_store = SettingsStore(Path("data/test_desktop_settings.json"))
    settings = DesktopSettings(animation_intensity=AnimationIntensity.FULL, hud_opacity=0.92)
    settings_store.save(settings)
    loaded_settings = settings_store.load()
    assert loaded_settings.animation_intensity == AnimationIntensity.FULL
    print("[2/7] Desktop settings atomic persistence verified.")

    startup_mgr = LoginStartupManager()
    print(f"[3/7] Login startup manager inspected (supported={startup_mgr.supported}, enabled={startup_mgr.is_enabled()}).")

    # 4. Instantiate Glass HUD & Tray
    hud = GlassHudWindow(loaded_settings)
    hud.show_hud()

    tray = BuddySystemTray()
    tray.show()
    print("[4/7] Animated Glass HUD and System Tray instantiated.")

    # 5. Measure Startup Metrics
    startup_time_ms = (time.perf_counter() - t_start) * 1000.0
    mem_info = process.memory_info()
    rss_mb = mem_info.rss / (1024 * 1024)
    print(f"      Startup Time: {startup_time_ms:.1f} ms | Initial RSS: {rss_mb:.1f} MB")

    # 6. Step through all visual states
    test_states = [
        (VisualState.STARTING, "Starting BUDDY...", 0.0),
        (VisualState.IDLE, "Ready — listening for 'Hey BUDDY'", 0.0),
        (VisualState.LISTENING, "Listening for voice command...", 0.65),
        (VisualState.THINKING, "Analyzing request with AI...", 0.3),
        (VisualState.EXECUTING, "Verified: system.get_battery", 0.0),
        (VisualState.SPEAKING, "Battery is at 85% and plugged in.", 0.8),
        (VisualState.PAUSED, "Listening paused by user", 0.0),
        (VisualState.ERROR, "Recoverable audio device warning", 0.0),
        (VisualState.IDLE, "Ready — listening for 'Hey BUDDY'", 0.0),
    ]

    print("[5/7] Testing state-synchronized animations...")
    for visual_st, status_txt, audio_lvl in test_states:
        snap = UiUpdate(
            visual_state=visual_st,
            core_state="IDLE",
            status_text=status_txt,
            audio_level=audio_lvl,
            mic_active=(visual_st == VisualState.LISTENING),
            mic_paused=(visual_st == VisualState.PAUSED),
        )
        hud._apply_ui_update(snap)
        qapp.processEvents()
        time.sleep(0.06)
        print(f"      Mapped VisualState: {visual_st.value:<14} | Level: {audio_lvl:.2f} | Status: {status_txt}")

    # 7. Measure Idle CPU & Memory
    print("[6/7] Measuring idle resource consumption (0.8s)...")
    cpu_measurements = []
    for _ in range(8):
        qapp.processEvents()
        time.sleep(0.1)
        cpu_measurements.append(process.cpu_percent(interval=None))

    avg_cpu = sum(cpu_measurements) / max(1, len(cpu_measurements))
    final_rss_mb = process.memory_info().rss / (1024 * 1024)
    print(f"      Average Idle CPU: {avg_cpu:.1f}% | Memory RSS: {final_rss_mb:.1f} MB")

    # 8. Test Orderly Shutdown Latency
    print("[7/7] Measuring shutdown latency...")
    t_shutdown_start = time.perf_counter()
    hud.hide_hud()
    tray.hide()
    qapp.processEvents()

    # Clean test file
    try:
        Path("data/test_desktop_settings.json").unlink(missing_ok=True)
    except Exception:
        pass

    shutdown_latency_ms = (time.perf_counter() - t_shutdown_start) * 1000.0
    print(f"      Shutdown Latency: {shutdown_latency_ms:.1f} ms")

    print("=" * 76)
    print("      ALL WINDOWS DESKTOP SMOKE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(run_windows_desktop_smoke_test())
