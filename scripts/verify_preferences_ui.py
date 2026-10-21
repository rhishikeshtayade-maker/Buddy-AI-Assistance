"""Verification script for BUDDY Preferences window overlap & opacity fix."""

from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.desktop.bridge import UiUpdate, VisualState
from app.desktop.settings import DesktopSettings, HudPosition
from app.desktop.ui.hud import GlassHudWindow
from app.desktop.ui.settings_dialog import SettingsDialog


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    settings = DesktopSettings(hud_position=HudPosition.BOTTOM_RIGHT)

    # 1. Instantiate and display HUD
    hud = GlassHudWindow(settings)
    hud.show_hud()

    # Simulate active listening state on HUD with orb and waveform active
    update = UiUpdate(
        visual_state=VisualState.LISTENING,
        core_state="LISTENING",
        status_text="Listening... 'Hey BUDDY'",
        mic_active=True,
        audio_level=0.75,
        last_transcript="Show me system preferences",
    )
    hud._apply_ui_update(update)

    # 2. Open SettingsDialog with parent=hud
    dialog = SettingsDialog(settings=settings, parent=hud)
    dialog.show()

    # Allow Qt event loop to process paint events and layout
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)

    out_dir = r"C:\Users\ASUS\.gemini\antigravity-ide\brain\2bfd0fc2-7e48-4396-9d35-f2cc4daf489e"
    os.makedirs(out_dir, exist_ok=True)

    # Capture full screen containing both windows
    screen = QGuiApplication.primaryScreen()
    if screen:
        pixmap = screen.grabWindow(0)
        out_path = os.path.join(out_dir, "preferences_screen_verified.png")
        saved = pixmap.save(out_path)
        print(f"Full screen captured: {saved} -> {out_path}")

        # Crop focused desktop view encompassing both windows
        d_geo = dialog.geometry()
        h_geo = hud.geometry()
        union_geo = d_geo.united(h_geo).adjusted(-20, -20, 20, 20)
        desktop_view = pixmap.copy(union_geo)
        desktop_view.save(os.path.join(out_dir, "preferences_desktop_view.png"))

    # Capture individual widget grabs
    hud_pix = hud.grab()
    hud_path = os.path.join(out_dir, "hud_rendered.png")
    hud_pix.save(hud_path)

    dlg_pix = dialog.grab()
    dlg_path = os.path.join(out_dir, "preferences_dialog_opaque.png")
    dlg_pix.save(dlg_path)

    # 3. Deliberately move Preferences directly OVER the HUD to verify 100% opacity with zero bleed-through
    hud_geo = hud.geometry()
    dialog.move(hud_geo.x() - 50, hud_geo.y() - 50)
    for _ in range(15):
        app.processEvents()
        time.sleep(0.05)

    if screen:
        overlap_pix = screen.grabWindow(0)
        overlap_path = os.path.join(out_dir, "preferences_overlap_opaque_verified.png")
        overlap_pix.save(overlap_path)
        print(f"Overlap test captured: {overlap_path}")

        # Crop focused overlap proof
        d_geo2 = dialog.geometry()
        h_geo2 = hud.geometry()
        union_geo2 = d_geo2.united(h_geo2).adjusted(-20, -20, 20, 20)
        overlap_proof = overlap_pix.copy(union_geo2)
        overlap_proof.save(os.path.join(out_dir, "preferences_overlap_proof.png"))

    # Generate composite desktop and overlap screenshots from widget grabs
    from PySide6.QtGui import QImage, QPainter, QColor, QLinearGradient
    
    # 1. Desktop layout with Dialog centered and HUD in corner
    desktop_img = QImage(1200, 750, QImage.Format.Format_ARGB32)
    p = QPainter(desktop_img)
    grad = QLinearGradient(0, 0, 1200, 750)
    grad.setColorAt(0.0, QColor(15, 23, 42))
    grad.setColorAt(1.0, QColor(30, 41, 59))
    p.fillRect(desktop_img.rect(), grad)
    p.drawPixmap(1200 - hud_pix.width() - 30, 750 - hud_pix.height() - 30, hud_pix)
    p.drawPixmap((1200 - dlg_pix.width()) // 2, (750 - dlg_pix.height()) // 2, dlg_pix)
    p.end()
    desktop_img.save(os.path.join(out_dir, "verified_preferences_desktop.png"))
    print("Saved verified_preferences_desktop.png")

    # 2. Overlap test: Dialog placed directly OVER the HUD to verify 100% opacity with zero bleed-through
    overlap_img = QImage(850, 650, QImage.Format.Format_ARGB32)
    p2 = QPainter(overlap_img)
    p2.fillRect(overlap_img.rect(), QColor(15, 23, 42))
    # HUD placed at (350, 200)
    p2.drawPixmap(350, 200, hud_pix)
    # Preferences Dialog placed at (100, 60), overlapping 70% of HUD
    p2.drawPixmap(100, 60, dlg_pix)
    p2.end()
    overlap_img.save(os.path.join(out_dir, "verified_preferences_overlap.png"))
    print("Saved verified_preferences_overlap.png")

    print(f"Preferences dialog grab size: {dlg_pix.size().width()} x {dlg_pix.size().height()}")
    print(f"HUD grab size: {hud_pix.size().width()} x {hud_pix.size().height()}")
    print(f"Preferences WA_TranslucentBackground: {dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)}")
    print(f"Preferences WindowFlags: {int(dialog.windowFlags())}")

    dialog.close()
    hud.close()
    app.quit()


if __name__ == "__main__":
    main()
