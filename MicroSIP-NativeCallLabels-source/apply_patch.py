#!/usr/bin/env python3
"""Patch MicroSIP's Windows/MFC source with an in-dialog incoming SIP line label
and disable official update checks (so an installer cannot overwrite the patch).

Usage:
    python apply_patch.py "C:\\src\\MicroSIP"
    python apply_patch.py "C:\\src\\MicroSIP" --undo

Changes ONLY these files (after validation):
 - Resource.h
 - res/dialog.rc2
 - RinginDlg.cpp
 - RinginDlg.h
 - mainDlg.cpp
 - microsip.cpp
 - CallLineLabel.h (created)

Backups use .call-label.bak. Does not handle compiling MicroSIP.
Already-patched files (containing the marker) are skipped so an older
call-label install can pick up the update-disable pieces.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import shutil
import sys

MARKER = "MICROSIP_CALL_LABELS_V1"
FILES = (
    "Resource.h",
    "res/dialog.rc2",
    "RinginDlg.cpp",
    "RinginDlg.h",
    "mainDlg.cpp",
    "microsip.cpp",
)


def one_replace(text: str, search: str, replacement: str, filename: str, regex: bool = False) -> str:
    if regex:
        revised, count = re.subn(search, replacement, text, count=1, flags=re.MULTILINE)
    else:
        count = text.count(search)
        revised = text.replace(search, replacement, 1)
    if count != 1:
        raise ValueError(f"{filename}: expected one anchor for {search!r}, found {count}")
    return revised


def modify(files: dict[str, str]) -> dict[str, str]:
    changed = dict(files)

    if "Resource.h" in changed:
        key = "Resource.h"
        changed[key] = one_replace(
            changed[key],
            "#define IDC_RINGIN_TEXT",
            f"#define IDC_RINGIN_LINE\t64000 // {MARKER}\n#define IDC_RINGIN_TEXT",
            key,
        )

    if "res/dialog.rc2" in changed:
        key = "res/dialog.rc2"
        changed[key] = one_replace(
            changed[key],
            "#define IDD_RINGIN_OFFSET_INITIAL 14",
            f"#define IDD_RINGIN_OFFSET_INITIAL 34 // {MARKER}: space for a separate SIP label",
            key,
        )
        changed[key] = one_replace(
            changed[key],
            'RTEXT           "", IDC_RINGIN_NAME_BLIND, 0, 0, 0, 0, WS_TABSTOP',
            'RTEXT           "", IDC_RINGIN_NAME_BLIND, 0, 0, 0, 0, WS_TABSTOP\n'
            f'CTEXT           "ACCOUNT", IDC_RINGIN_LINE, 5, 9, _GLOBAL_RINGIN_WIDTH - 10, 17 // {MARKER}',
            key,
        )

    if "RinginDlg.h" in changed:
        key = "RinginDlg.h"
        changed[key] = one_replace(
            changed[key],
            "CFont m_font_ignore;",
            f"CFont m_font_ignore;\n\tCFont m_font_line; // {MARKER}",
            key,
        )

    if "RinginDlg.cpp" in changed:
        key = "RinginDlg.cpp"
        changed[key] = one_replace(
            changed[key],
            '#include "RinginDlg.h"',
            f'#include "RinginDlg.h"\n#include "CallLineLabel.h" // {MARKER}',
            key,
        )
        changed[key] = one_replace(
            changed[key],
            "TranslateDialog(this->m_hWnd);",
            """TranslateDialog(this->m_hWnd);

    // MICROSIP_CALL_LABELS_V1: active account label (MicroSIP.ini AccountN label=).
    // Show it inside the incoming call dialog AND in the title bar.
    CString lineLabel = CallLineLabel::Read();
    CString dialogTitle;
    GetWindowText(dialogTitle);
    SetWindowText(dialogTitle + _T(" - ") + lineLabel);
    if (CWnd* lineField = GetDlgItem(IDC_RINGIN_LINE)) {
        lineField->SetWindowText(lineLabel);
    }""",
            key,
        )
        changed[key] = one_replace(
            changed[key],
            "CFont* font = this->GetFont();",
            "CFont* font = this->GetFont();",
            key,
        )  # validation anchor
        # Insert font preparation only once after LOGFONT has been initialized.
        changed[key] = one_replace(
            changed[key],
            "font->GetLogFont(&lf);",
            """font->GetLogFont(&lf);

    // MICROSIP_CALL_LABELS_V1: emphasize the line without changing caller name.
    LOGFONT labelFont = lf;
    labelFont.lfHeight = -MulDiv(16, dpiY, 96);
    labelFont.lfWeight = FW_BOLD;
    m_font_line.CreateFontIndirect(&labelFont);
    if (CWnd* lineField = GetDlgItem(IDC_RINGIN_LINE)) {
        lineField->SetFont(&m_font_line);
    }""",
            key,
        )

    if "mainDlg.cpp" in changed:
        key = "mainDlg.cpp"
        changed[key] = one_replace(
            changed[key],
            "void CmainDlg::CheckUpdates()\n{",
            "void CmainDlg::CheckUpdates()\n"
            "{\n"
            f"    // {MARKER}: patched builds must not self-update "
            "(official installer overwrites the patch).\n"
            "    return;",
            key,
        )

    if "microsip.cpp" in changed:
        key = "microsip.cpp"
        changed[key] = one_replace(
            changed[key],
            "timeBuild = _GLOBAL_TIMESTAMP;\n"
            "        if (time > timeBuild + 86400 * lifeTime3) {",
            "timeBuild = _GLOBAL_TIMESTAMP;\n"
            f"        // {MARKER}: skip EOL/update nag so patched builds stay usable.\n"
            "        if (false && time > timeBuild + 86400 * lifeTime3) {",
            key,
        )

    return changed


def _decode(path: Path) -> tuple[str, bytes, str, str]:
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
    newline = "\r\n" if "\r\n" in decoded else "\n"
    normalized = decoded.replace("\r\n", "\n")
    return normalized, raw, encoding, newline


def run(source: Path, undo: bool):
    paths = {name: source / name for name in FILES}
    module_dst = source / "CallLineLabel.h"
    if undo:
        missing = [name for name, path in paths.items() if not Path(str(path) + ".call-label.bak").is_file()]
        if missing:
            raise ValueError("Cannot undo: backups missing: " + ", ".join(missing))
        for name, path in paths.items():
            shutil.copy2(str(path) + ".call-label.bak", path)
        if module_dst.is_file() and "MicroSIP Native Call Labels" in module_dst.read_text(
            encoding="utf-8", errors="ignore"
        ):
            module_dst.unlink()
        print("Restored original sources from .call-label.bak files.")
        return

    for name, path in paths.items():
        if not path.is_file():
            raise ValueError(
                f"Missing {name}. Point to the folder with MicroSIP source code, "
                "NOT installed MicroSIP."
            )

    # MFC projects and source files frequently use Windows-1252 or UTF-8 with BOM.
    # Keep original file byte encoding, BOM and line ending style.
    to_patch: dict[str, tuple[str, bytes, str, str]] = {}
    skipped: list[str] = []
    for name, path in paths.items():
        normalized, raw, encoding, newline = _decode(path)
        if MARKER in normalized:
            skipped.append(name)
            continue
        to_patch[name] = (normalized, raw, encoding, newline)

    src_module = Path(__file__).with_name("CallLineLabel.h")
    if not src_module.is_file():
        raise ValueError("Missing CallLineLabel.h next to apply_patch.py")
    need_module = not module_dst.is_file()

    if not to_patch and not need_module:
        raise ValueError("All target files already patched; nothing to do.")

    changed = modify({name: meta[0] for name, meta in to_patch.items()}) if to_patch else {}

    for name, path in paths.items():
        if name not in to_patch:
            continue
        if Path(str(path) + ".call-label.bak").exists():
            raise ValueError(f"Backup already exists: {path}. Refusing to overwrite.")

    for name, path in paths.items():
        if name not in to_patch:
            continue
        _orig_text, _orig_bytes, encoding, newline = to_patch[name]
        shutil.copy2(path, str(path) + ".call-label.bak")
        path.write_bytes(changed[name].replace("\n", newline).encode(encoding))

    if need_module:
        shutil.copy2(src_module, module_dst)

    patched = sorted(to_patch.keys())
    if need_module:
        patched.append("CallLineLabel.h")
    print("Patch installed into MicroSIP sources. Next: compile MicroSIP in Visual Studio.")
    print("Incoming call dialog will show the active account label from MicroSIP.ini.")
    print("Official update checks and EOL update nags are disabled.")
    if patched:
        print("Patched: " + ", ".join(patched))
    if skipped:
        print("Already patched (skipped): " + ", ".join(skipped))


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
