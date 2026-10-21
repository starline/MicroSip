#!/usr/bin/env python3
"""Patch MicroSIP's Windows/MFC source with an in-dialog incoming SIP line label.

Usage:
    python apply_patch.py "C:\\src\\MicroSIP"
    python apply_patch.py "C:\\src\\MicroSIP" --undo

Changes ONLY these files (after validation):
 - Resource.h
 - res/dialog.rc2
 - RinginDlg.cpp
 - RinginDlg.h
 - CallLineLabel.h (created)

Backups use .call-label.bak. Does not handle compiling MicroSIP.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import shutil
import sys

MARKER = "MICROSIP_CALL_LABELS_V1"
FILES = ("Resource.h", "res/dialog.rc2", "RinginDlg.cpp", "RinginDlg.h")


def one_replace(text: str, search: str, replacement: str, filename: str, regex: bool = False) -> str:
    if regex:
        revised, count = re.subn(search, replacement, text, count=1, flags=re.MULTILINE)
    else:
        count = text.count(search)
        revised = text.replace(search, replacement, 1)
    if count != 1:
        raise ValueError(f"{filename}: expected one anchor for {search!r}, found {count}")
    return revised


def modify(files: dict[str, str]):
    changed = dict(files)
    key = "Resource.h"
    changed[key] = one_replace(changed[key], "#define IDC_RINGIN_TEXT", 
        f"#define IDC_RINGIN_LINE\t64000 // {MARKER}\n#define IDC_RINGIN_TEXT", key)

    key = "res/dialog.rc2"
    changed[key] = one_replace(changed[key],
        "#define IDD_RINGIN_OFFSET_INITIAL 14",
        f"#define IDD_RINGIN_OFFSET_INITIAL 34 // {MARKER}: space for a separate SIP label",
        key)
    changed[key] = one_replace(changed[key],
        'RTEXT           "", IDC_RINGIN_NAME_BLIND, 0, 0, 0, 0, WS_TABSTOP',
        'RTEXT           "", IDC_RINGIN_NAME_BLIND, 0, 0, 0, 0, WS_TABSTOP\n'
        f'CTEXT           "ACCOUNT", IDC_RINGIN_LINE, 5, 9, _GLOBAL_RINGIN_WIDTH - 10, 17 // {MARKER}', key)

    key = "RinginDlg.h"
    changed[key] = one_replace(changed[key],
        "CFont m_font_ignore;",
        f"CFont m_font_ignore;\n\tCFont m_font_line; // {MARKER}", key)

    key = "RinginDlg.cpp"
    changed[key] = one_replace(changed[key],
        '#include "RinginDlg.h"',
        f'#include "RinginDlg.h"\n#include "CallLineLabel.h" // {MARKER}', key)
    changed[key] = one_replace(changed[key],
        'TranslateDialog(this->m_hWnd);',
        '''TranslateDialog(this->m_hWnd);

    // MICROSIP_CALL_LABELS_V1: active account label (MicroSIP.ini AccountN label=).
    // Show it inside the incoming call dialog AND in the title bar.
    CString lineLabel = CallLineLabel::Read();
    CString dialogTitle;
    GetWindowText(dialogTitle);
    SetWindowText(dialogTitle + _T(" - ") + lineLabel);
    if (CWnd* lineField = GetDlgItem(IDC_RINGIN_LINE)) {
        lineField->SetWindowText(lineLabel);
    }''', key)
    changed[key] = one_replace(changed[key],
        'CFont* font = this->GetFont();',
        'CFont* font = this->GetFont();', key)   # validation anchor
    # Insert font preparation only once after LOGFONT has been initialized.
    changed[key] = one_replace(changed[key],
        'font->GetLogFont(&lf);',
        '''font->GetLogFont(&lf);

    // MICROSIP_CALL_LABELS_V1: emphasize the line without changing caller name.
    LOGFONT labelFont = lf;
    labelFont.lfHeight = -MulDiv(16, dpiY, 96);
    labelFont.lfWeight = FW_BOLD;
    m_font_line.CreateFontIndirect(&labelFont);
    if (CWnd* lineField = GetDlgItem(IDC_RINGIN_LINE)) {
        lineField->SetFont(&m_font_line);
    }''', key)
    return changed


def run(source: Path, undo: bool):
    paths = {name: source / name for name in FILES}
    module_dst = source / "CallLineLabel.h"
    if undo:
        missing = [name for name, path in paths.items() if not Path(str(path) + ".call-label.bak").is_file()]
        if missing:
            raise ValueError("Cannot undo: backups missing: " + ", ".join(missing))
        for name, path in paths.items():
            shutil.copy2(str(path) + ".call-label.bak", path)
        if module_dst.is_file() and MARKER not in module_dst.read_text(encoding="utf-8", errors="ignore"):
            # The module itself is recognized by its unique introductory comment.
            if "MicroSIP Native Call Labels" in module_dst.read_text(encoding="utf-8", errors="ignore"):
                module_dst.unlink()
        elif module_dst.is_file() and "MicroSIP Native Call Labels" in module_dst.read_text(encoding="utf-8", errors="ignore"):
            module_dst.unlink()
        print("Restored original sources from .call-label.bak files.")
        return

    for name, path in paths.items():
        if not path.is_file():
            raise ValueError(f"Missing {name}. Point to the folder with MicroSIP source code, NOT installed MicroSIP.")
    if module_dst.exists():
        raise ValueError("CallLineLabel.h already exists: refusing to overwrite it.")
    # MFC projects and source files frequently use Windows-1252 or UTF-8 with BOM.
    # Keep original file byte encoding, BOM and line ending style.
    originals: dict[str, tuple[str, bytes, str, str]] = {}
    for name, path in paths.items():
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"
        else:
            try:
                raw.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                encoding = "cp1252"
        decoded = raw.decode(encoding)
        if MARKER in decoded:
            raise ValueError(f"{name} already patched; refusing to apply twice.")
        newline = "\r\n" if "\r\n" in decoded else "\n"
        normalized = decoded.replace("\r\n", "\n")
        originals[name] = (normalized, raw, encoding, newline)
    changed = modify({name: meta[0] for name, meta in originals.items()})
    # All anchors successfully validated before ANY disk changes.
    src_module = Path(__file__).with_name("CallLineLabel.h")
    if not src_module.is_file():
        raise ValueError("Missing CallLineLabel.h next to apply_patch.py")
    for name, path in paths.items():
        if Path(str(path) + ".call-label.bak").exists():
            raise ValueError(f"Backup already exists: {path}. Refusing to overwrite.")
    for name, path in paths.items():
        orig_text, orig_bytes, encoding, newline = originals[name]
        shutil.copy2(path, str(path) + ".call-label.bak")
        path.write_bytes(changed[name].replace("\n", newline).encode(encoding))
    shutil.copy2(src_module, module_dst)
    print("Patch installed into MicroSIP sources. Next: compile MicroSIP in Visual Studio.")
    print("Incoming call dialog will show the active account label from MicroSIP.ini.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path, help="Path to MicroSIP SOURCE tree")
    p.add_argument("--undo", action="store_true", help="Restore .call-label.bak files")
    a = p.parse_args()
    try:
        run(a.source.resolve(), a.undo)
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
