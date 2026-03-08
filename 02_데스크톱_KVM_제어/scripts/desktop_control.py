import argparse
import ctypes
import json
import string
import sys
import time
from ctypes import wintypes


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

SW_RESTORE = 9

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


ULONG_PTR = ctypes.c_size_t


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("u", INPUT_UNION),
    ]


user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = ctypes.c_uint
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.SetCursorPos.restype = wintypes.BOOL
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
user32.GetWindowRect.restype = wintypes.BOOL
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetFocus.argtypes = (wintypes.HWND,)
user32.SetFocus.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(ctypes.c_ulong))
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.AttachThreadInput.argtypes = (ctypes.c_ulong, ctypes.c_ulong, wintypes.BOOL)
user32.AttachThreadInput.restype = wintypes.BOOL


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


VK_BY_NAME = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
}

for digit in string.digits:
    VK_BY_NAME[digit] = ord(digit)

for letter in string.ascii_lowercase:
    VK_BY_NAME[letter] = ord(letter.upper())

for idx in range(1, 13):
    VK_BY_NAME[f"f{idx}"] = 0x6F + idx


def set_dpi_aware() -> None:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def json_out(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def send_inputs(inputs: list[INPUT]) -> None:
    count = len(inputs)
    if count == 0:
        return
    array_type = INPUT * count
    sent = user32.SendInput(count, array_type(*inputs), ctypes.sizeof(INPUT))
    if sent != count:
        raise OSError(ctypes.get_last_error(), "SendInput failed")


def keyboard_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0))


def mouse_input(flags: int) -> INPUT:
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0))


def get_cursor_pos() -> tuple[int, int]:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise OSError(ctypes.get_last_error(), "GetCursorPos failed")
    return point.x, point.y


def set_cursor_pos(x: int, y: int) -> None:
    if not user32.SetCursorPos(x, y):
        raise OSError(ctypes.get_last_error(), "SetCursorPos failed")


def move_cursor(x: int, y: int, duration_ms: int, steps: int) -> None:
    start_x, start_y = get_cursor_pos()
    if duration_ms <= 0 or steps <= 1:
        set_cursor_pos(x, y)
        return

    for idx in range(1, steps + 1):
        ratio = idx / steps
        current_x = round(start_x + ((x - start_x) * ratio))
        current_y = round(start_y + ((y - start_y) * ratio))
        set_cursor_pos(current_x, current_y)
        time.sleep(duration_ms / steps / 1000)


def click_mouse(button: str, double: bool) -> None:
    flags_by_button = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }
    down, up = flags_by_button[button]
    send_inputs([mouse_input(down), mouse_input(up)])
    if double:
        time.sleep(0.06)
        send_inputs([mouse_input(down), mouse_input(up)])


def type_text(text: str, interval_ms: int) -> None:
    for char in text:
        scan = ord(char)
        send_inputs(
            [
                keyboard_input(scan=scan, flags=KEYEVENTF_UNICODE),
                keyboard_input(scan=scan, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ]
        )
        if interval_ms > 0:
            time.sleep(interval_ms / 1000)


def resolve_vk(name: str) -> int:
    key = name.strip().lower()
    if key not in VK_BY_NAME:
        raise ValueError(f"Unsupported key name: {name}")
    return VK_BY_NAME[key]


def press_combo(combo: str) -> None:
    keys = [part.strip() for part in combo.split("+") if part.strip()]
    if not keys:
        raise ValueError("No keys provided")

    vk_codes = [resolve_vk(item) for item in keys]
    downs = [keyboard_input(vk=vk) for vk in vk_codes]
    ups = [keyboard_input(vk=vk, flags=KEYEVENTF_KEYUP) for vk in reversed(vk_codes)]
    send_inputs(downs + ups)


def list_windows(title_filter: str) -> list[dict]:
    windows: list[dict] = []
    filter_lower = title_filter.lower()

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        title = buffer.value.strip()
        if not title:
            return True
        if filter_lower and filter_lower not in title.lower():
            return True

        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True

        windows.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
            }
        )
        return True

    if not user32.EnumWindows(EnumWindowsProc(callback), 0):
        raise OSError(ctypes.get_last_error(), "EnumWindows failed")

    return windows


def focus_window(contains: str) -> dict:
    matches = list_windows(contains)
    if not matches:
        raise RuntimeError(f"No visible window matched: {contains}")

    target = matches[0]
    hwnd = wintypes.HWND(target["hwnd"])
    user32.ShowWindow(hwnd, SW_RESTORE)

    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    attached_foreground = False
    attached_target = False

    try:
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(user32.AttachThreadInput(foreground_thread, current_thread, True))
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(target_thread, current_thread, True))

        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached_foreground:
            user32.AttachThreadInput(foreground_thread, current_thread, False)
        if attached_target:
            user32.AttachThreadInput(target_thread, current_thread, False)

    time.sleep(0.15)
    return target


def screen_size() -> dict:
    return {
        "primary": {
            "width": user32.GetSystemMetrics(SM_CXSCREEN),
            "height": user32.GetSystemMetrics(SM_CYSCREEN),
        },
        "virtual": {
            "left": user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            "top": user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            "width": user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            "height": user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("screen-size")
    subparsers.add_parser("cursor-pos")

    list_parser = subparsers.add_parser("list-windows")
    list_parser.add_argument("--contains", default="")

    focus_parser = subparsers.add_parser("focus-window")
    focus_parser.add_argument("--contains", required=True)

    move_parser = subparsers.add_parser("move")
    move_parser.add_argument("--x", type=int, required=True)
    move_parser.add_argument("--y", type=int, required=True)
    move_parser.add_argument("--duration-ms", type=int, default=0)
    move_parser.add_argument("--steps", type=int, default=20)

    click_parser = subparsers.add_parser("click")
    click_parser.add_argument("--x", type=int)
    click_parser.add_argument("--y", type=int)
    click_parser.add_argument("--button", choices=["left", "right", "middle"], default="left")
    click_parser.add_argument("--double", action="store_true")

    type_parser = subparsers.add_parser("type")
    type_parser.add_argument("--text", required=True)
    type_parser.add_argument("--interval-ms", type=int, default=10)

    combo_parser = subparsers.add_parser("combo")
    combo_parser.add_argument("--keys", required=True)

    return parser


def main() -> None:
    set_dpi_aware()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "screen-size":
        json_out({"ok": True, "screen": screen_size()})
        return

    if args.command == "cursor-pos":
        x, y = get_cursor_pos()
        json_out({"ok": True, "x": x, "y": y})
        return

    if args.command == "list-windows":
        windows = list_windows(args.contains)
        json_out({"ok": True, "count": len(windows), "windows": windows})
        return

    if args.command == "focus-window":
        target = focus_window(args.contains)
        json_out({"ok": True, "window": target})
        return

    if args.command == "move":
        move_cursor(args.x, args.y, args.duration_ms, args.steps)
        json_out({"ok": True, "x": args.x, "y": args.y})
        return

    if args.command == "click":
        if args.x is not None and args.y is not None:
            set_cursor_pos(args.x, args.y)
            time.sleep(0.03)
        x, y = get_cursor_pos()
        click_mouse(args.button, args.double)
        json_out({"ok": True, "button": args.button, "double": args.double, "x": x, "y": y})
        return

    if args.command == "type":
        type_text(args.text, args.interval_ms)
        json_out({"ok": True, "chars": len(args.text)})
        return

    if args.command == "combo":
        press_combo(args.keys)
        json_out({"ok": True, "keys": args.keys})
        return

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        json_out({"ok": False, "error": str(exc)})
        sys.exit(1)
