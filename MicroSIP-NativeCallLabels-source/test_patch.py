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
        'TranslateDialog(this->m_hWnd);\r\n'
        'CFont* font = this->GetFont();\r\n'
        'font->GetLogFont(&lf);\r\n'
    ),
    "RinginDlg.h": "CFont m_font_ignore;\r\n",
}

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    for name, value in FIXTURES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode("utf-8"))
    run(root, False)
    for name in FILES:
        path = root / name
        assert MARKER in path.read_bytes().decode("utf-8")
        assert b"\r\n" in path.read_bytes()
    assert (root / "CallLineLabel.h").is_file()
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
print("PASS: apply, idempotency check, undo, and CRLF integrity")
