---
name: desktop-kvm-control
description: Use when a task requires Windows desktop or KVM-style control outside browser DOM automation, including listing or focusing windows, moving the mouse, clicking by coordinate, typing text, sending key combos, capturing the current screen, or printing PDFs through local tools.
---

# Desktop KVM Control

Use this skill for OS-level control on Windows when browser DOM automation is not enough.

Prefer higher-level APIs first. Use desktop or KVM control only when the target is a native app, a browser page that cannot be driven through DOM, or a one-time bootstrap step such as loading an unpacked extension.

## Available scripts

- `scripts/desktop_control.py`
  - `screen-size`
  - `cursor-pos`
  - `list-windows [--contains TEXT]`
  - `focus-window --contains TEXT`
  - `move --x INT --y INT [--duration-ms INT] [--steps INT]`
  - `click [--x INT --y INT] [--button left|right|middle] [--double]`
  - `type --text TEXT [--interval-ms INT]`
  - `combo --keys ctrl+l`
- `scripts/capture_screen.ps1`
  - Captures the current desktop to a PNG file.
  - Tries the full virtual desktop first and falls back to the primary screen if the session rejects virtual-screen capture.
- `scripts/print_pdf_via_sumatra.ps1`
  - Verified best path for this PC
  - Prints a PDF directly to the named printer with SumatraPDF CLI and verifies that a new Windows print-queue job appears
- `scripts/print_pdf_via_hpdf.ps1`
  - UI fallback path
  - Opens the PDF in HanPDF, focuses the document canvas, sends `Ctrl+P`, waits for the HanPDF print dialog, presses `Enter`, and verifies the Windows print queue
- `scripts/guarded_desktop_action.ps1`
  - Reads `config/action_policy.json`
  - Requests local approval for non-read-only actions before executing them

## Working pattern

1. Inspect state first.
   - Use `list-windows` to find the target window.
   - Use `capture_screen.ps1` before risky clicks.
2. Focus the target window before typing or key combos.
3. Prefer `guarded_desktop_action.ps1` for `focus-window`, `move`, `click`, `type`, and `combo`.
4. Prefer deterministic coordinates and explicit window titles.
5. Keep destructive actions rare and deliberate.
6. For local PDF printing on this PC, prefer `print_pdf_via_sumatra.ps1` first.
7. Use `print_pdf_via_hpdf.ps1` only as a fallback when CLI printing is not viable.

## Verified PDF print path on this PC

The most reliable path observed here is:

1. Call `print_pdf_via_sumatra.ps1` with the explicit printer name `SEC842519C6E0ED(C51x Series)`.
2. Let SumatraPDF send the PDF straight to the Windows spooler without opening a viewer window.
3. Verify that the Samsung queue receives a new job.

This is currently more reliable than driving HanPDF's WPF print dialog.

## HanPDF fallback notes

If the CLI path cannot be used, the next best observed fallback is:

1. Open the PDF in HanPDF.
2. Focus the exact PDF window by file name.
3. Click once inside the document canvas to avoid side-pane focus.
4. Send `ctrl+p`.
5. Confirm that the printer list still has `SEC842519C6E0ED(C51x Series)` selected.
6. Use the print action after a short settle delay.
7. Verify that the Samsung queue receives a new job.

Gemini review for this failure mode suggested re-selecting the printer item, adding a short delay, and using button-level automation only as a fallback to the direct CLI path.

## Examples

```powershell
python .\scripts\desktop_control.py list-windows --contains Chrome
python .\scripts\desktop_control.py focus-window --contains Chrome
python .\scripts\desktop_control.py move --x 1200 --y 700 --duration-ms 200
python .\scripts\desktop_control.py click --x 1200 --y 700
python .\scripts\desktop_control.py type --text "hello"
python .\scripts\desktop_control.py combo --keys ctrl+l
pwsh .\scripts\guarded_desktop_action.ps1 click --x 1200 --y 700
powershell -ExecutionPolicy Bypass -File .\scripts\capture_screen.ps1 -OutPath .\captures\screen.png
powershell -ExecutionPolicy Bypass -File .\scripts\print_pdf_via_sumatra.ps1 -PdfPath C:\path\report.pdf
powershell -ExecutionPolicy Bypass -File .\scripts\print_pdf_via_hpdf.ps1 -PdfPath C:\path\report.pdf
```

## Notes

- `type` uses Unicode keyboard events and is suitable for Korean text input.
- `combo` is for shortcut-style keys such as `ctrl+l`, `ctrl+shift+esc`, and `alt+tab`.
- `capture_screen.ps1` uses only built-in PowerShell and .NET APIs.
