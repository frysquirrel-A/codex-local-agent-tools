Study Live Chrome Bridge

Purpose:
- Control the current Chrome page through DOM commands.
- No mouse or keyboard input is needed after the one-time extension install.

Folder contents:
- `live_extension`
- `live_bridge_server.py`
- `start_live_bridge_server.ps1`
- `stop_live_bridge_server.ps1`
- `send_live_page_command.py`
- `send_live_page_command.ps1`

Requirements:
- Windows
- Google Chrome
- Python 3 available on PATH

One-time setup on a new PC:
1. Open Chrome.
2. Go to `chrome://extensions`.
3. Turn on `Developer mode`.
4. Click `Load unpacked`.
5. Select the `live_extension` folder from this package.

Run:
1. Start the bridge server:
   `powershell -ExecutionPolicy Bypass -File .\start_live_bridge_server.ps1`
2. Open Chrome on any normal `http` or `https` page.
3. Send commands:
   `.\send_live_page_command.ps1 ping`
   `.\send_live_page_command.ps1 dom-summary`
   `.\send_live_page_command.ps1 navigate --url https://www.wikipedia.org/`
   `.\send_live_page_command.ps1 set-text --selector "input[name='search']" --text "hello"`
   `.\send_live_page_command.ps1 prompt-send --selector "textarea" --send-selector "button[type='submit']" --text "hello"`
4. Stop the bridge server:
   `powershell -ExecutionPolicy Bypass -File .\stop_live_bridge_server.ps1`

Notes:
- This package does not need a copied Chrome profile.
- This package does not need Chrome shortcut modifications.
- The current implementation uses only the Python standard library plus the unpacked Chrome extension.
- The extension heartbeat is tuned for lower latency than the original study prototype.
- `prompt-send` reduces one full round trip by setting text and clicking send inside the page context.
