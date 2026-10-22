"""Synthetic smoke tests for the source patch installer (no Windows/MFC compilation)."""
from pathlib import Path
import tempfile
from apply_patch import run, FILES, MARKER

FIXTURES = {
    "Resource.h": "#define IDC_RINGIN_TEXT\t1003\r\n#define IDC_ANSWER\t1000\r\n",
    "res/dialog.rc2": (
        "#define IDD_RINGIN_OFFSET_INITIAL 14\r\n"
        'RTEXT           "", IDC_RINGIN_NAME_BLIND, 0, 0, 0, 0, WS_TABSTOP\r\n'
    ),
    "RinginDlg.cpp": (
        '#include "RinginDlg.h"\r\n'
        "TranslateDialog(this->m_hWnd);\r\n"
        "CFont* font = this->GetFont();\r\n"
        "font->GetLogFont(&lf);\r\n"
    ),
    "RinginDlg.h": "CFont m_font_ignore;\r\n",
    "mainDlg.cpp": "void CmainDlg::CheckUpdates()\r\n{\r\n    CString url;\r\n",
    "microsip.cpp": (
        "timeBuild = _GLOBAL_TIMESTAMP;\r\n"
        "        if (time > timeBuild + 86400 * lifeTime3) {\r\n"
    ),
}


def _write_tree(root: Path, fixtures: dict[str, str]) -> None:
    for name, value in fixtures.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode("utf-8"))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    _write_tree(root, FIXTURES)
    run(root, False)
    for name in FILES:
        path = root / name
        assert MARKER in path.read_bytes().decode("utf-8"), name
        assert b"\r\n" in path.read_bytes(), name
    assert (root / "CallLineLabel.h").is_file()
    assert b"return;" in (root / "mainDlg.cpp").read_bytes()
    assert b"if (false &&" in (root / "microsip.cpp").read_bytes()
    try:
        run(root, False)
    except ValueError:
        pass
    else:
        raise AssertionError("Must refuse double application")
    run(root, True)
    for name, value in FIXTURES.items():
        assert (root / name).read_bytes() == value.encode("utf-8"), name
    assert not (root / "CallLineLabel.h").exists()

# Incremental: call-label already present, update-disable not yet.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    partial = dict(FIXTURES)
    partial["Resource.h"] = (
        f"#define IDC_RINGIN_LINE\t64000 // {MARKER}\r\n"
        "#define IDC_RINGIN_TEXT\t1003\r\n"
    )
    partial["RinginDlg.h"] = f"CFont m_font_ignore;\r\n\tCFont m_font_line; // {MARKER}\r\n"
    partial["RinginDlg.cpp"] = (
        f'#include "RinginDlg.h"\r\n#include "CallLineLabel.h" // {MARKER}\r\n'
        "TranslateDialog(this->m_hWnd);\r\n"
        "CFont* font = this->GetFont();\r\n"
        "font->GetLogFont(&lf);\r\n"
    )
    partial["res/dialog.rc2"] = (
        f"#define IDD_RINGIN_OFFSET_INITIAL 34 // {MARKER}: space for a separate SIP label\r\n"
        'RTEXT           "", IDC_RINGIN_NAME_BLIND, 0, 0, 0, 0, WS_TABSTOP\r\n'
        f'CTEXT           "ACCOUNT", IDC_RINGIN_LINE, 5, 9, _GLOBAL_RINGIN_WIDTH - 10, 17 // {MARKER}\r\n'
    )
    _write_tree(root, partial)
    (root / "CallLineLabel.h").write_text(
        f"/* MicroSIP Native Call Labels */\n// {MARKER}\n", encoding="utf-8"
    )
    run(root, False)
    assert MARKER in (root / "mainDlg.cpp").read_text(encoding="utf-8")
    assert MARKER in (root / "microsip.cpp").read_text(encoding="utf-8")
    assert b"return;" in (root / "mainDlg.cpp").read_bytes()
    # Previously patched files must stay untouched (no new .bak for them).
    assert not (root / "Resource.h.call-label.bak").exists()
    assert (root / "mainDlg.cpp.call-label.bak").exists()
    assert (root / "microsip.cpp.call-label.bak").exists()

print("PASS: apply, idempotency check, undo, CRLF integrity, incremental update-disable")
