"""Native Windows GUI File Dialogs for NEXUS file operations."""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger("nexus.file_dialog")


def open_native_save_dialog(
    default_filename: str = "spreadsheet.xlsx",
    title: str = "Save File As",
) -> Optional[str]:
    """
    Open native Windows File Explorer Save File dialog using tkinter GUI.
    Returns the absolute path selected by the user, or None if cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        file_types = [("All Files", "*.*")]
        def_ext = None
        if default_filename.endswith(".xlsx"):
            file_types = [("Excel Files (*.xlsx)", "*.xlsx"), ("All Files (*.*)", "*.*")]
            def_ext = ".xlsx"
        elif default_filename.endswith(".docx"):
            file_types = [("Word Documents (*.docx)", "*.docx"), ("All Files (*.*)", "*.*")]
            def_ext = ".docx"
        elif default_filename.endswith(".pptx"):
            file_types = [("PowerPoint Presentations (*.pptx)", "*.pptx"), ("All Files (*.*)", "*.*")]
            def_ext = ".pptx"

        from backend.core.paths import get_active_desktop
        initial_dir = str(get_active_desktop())

        selected_path = filedialog.asksaveasfilename(
            title=title,
            initialfile=default_filename,
            initialdir=initial_dir,
            filetypes=file_types,
            defaultextension=def_ext,
        )
        root.destroy()


        if selected_path and str(selected_path).strip():
            logger.info(f"User selected path via File Explorer: {selected_path}")
            return str(selected_path).strip()
        return None
    except Exception as err:
        logger.error(f"Failed to open native file dialog: {err}")
        return None


def open_native_folder_dialog(
    title: str = "Select Folder to Store Presentation",
) -> Optional[str]:
    """
    Open native Windows File Explorer Folder Browser dialog using tkinter GUI.
    Returns the absolute folder path selected by the user, or None if cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        from backend.core.paths import get_active_desktop
        initial_dir = str(get_active_desktop())

        selected_dir = filedialog.askdirectory(
            title=title,
            initialdir=initial_dir,
        )
        root.destroy()

        if selected_dir and str(selected_dir).strip():
            logger.info(f"User selected folder via File Explorer: {selected_dir}")
            return str(selected_dir).strip()
        return None
    except Exception as err:
        logger.error(f"Failed to open native folder dialog: {err}")
        return None

