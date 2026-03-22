#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_APP = "Google Chrome"


class BridgeError(RuntimeError):
    pass


def run_osascript(script: str, *, language: str = "AppleScript", args: list[str] | None = None) -> str:
    suffix = ".js" if language == "JavaScript" else ".applescript"
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        cmd = ["osascript"]
        if language == "JavaScript":
            cmd.extend(["-l", "JavaScript"])
        cmd.append(str(script_path))
        if args:
            cmd.extend(args)
        proc = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        script_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        raise BridgeError(message or f"osascript failed with exit code {proc.returncode}")

    return proc.stdout.strip()


def get_session() -> dict:
    script = f"""
const chrome = Application("{CHROME_APP}");
const result = {{
  browser: "{CHROME_APP}",
  running: chrome.running(),
  windows: []
}};

if (chrome.running()) {{
  const windows = chrome.windows();
  for (let wi = 0; wi < windows.length; wi++) {{
    const w = windows[wi];
    const tabs = w.tabs();
    const activeId = tabs.length > 0 ? String(w.activeTab().id()) : null;
    result.windows.push({{
      windowIndex: wi + 1,
      front: wi === 0,
      tabs: tabs.map((t, ti) => ({{
        windowIndex: wi + 1,
        tabIndex: ti + 1,
        id: String(t.id()),
        title: t.title(),
        url: t.url(),
        active: String(t.id()) === activeId
      }}))
    }});
  }}
}}

JSON.stringify(result);
"""
    return json.loads(run_osascript(script, language="JavaScript"))


def flatten_tabs(session: dict) -> list[dict]:
    tabs: list[dict] = []
    for window in session.get("windows", []):
        tabs.extend(window.get("tabs", []))
    return tabs


def get_active_tab(session: dict | None = None) -> dict | None:
    session = session or get_session()
    for tab in flatten_tabs(session):
        if tab.get("active"):
            return tab
    return None


def check_js_apple_events() -> dict:
    script = f"""
tell application "{CHROME_APP}"
  if not running then error "{CHROME_APP} is not running."
  return execute active tab of front window javascript "document.title"
end tell
"""
    try:
        result = run_osascript(script)
        return {"enabled": True, "result": result}
    except BridgeError as exc:
        message = str(exc)
        if "Executing JavaScript through AppleScript is turned off" in message or "Allow JavaScript from Apple Events" in message:
            return {
                "enabled": False,
                "reason": "Enable View > Developer > Allow JavaScript from Apple Events in Chrome."
            }
        return {"enabled": False, "reason": message}


def emit(payload: object, *, pretty: bool = True) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def require_running(session: dict) -> None:
    if not session.get("running"):
        raise BridgeError(f"{CHROME_APP} is not running.")


def find_matches(session: dict, *, tab_id: str | None, title_contains: str | None, url_contains: str | None) -> list[dict]:
    tabs = flatten_tabs(session)
    if tab_id:
        return [tab for tab in tabs if tab["id"] == tab_id]

    title_query = title_contains.lower() if title_contains else None
    url_query = url_contains.lower() if url_contains else None

    if title_query or url_query:
        matches = []
        for tab in tabs:
            title = tab["title"].lower()
            url = tab["url"].lower()
            if title_query and title_query not in title:
                continue
            if url_query and url_query not in url:
                continue
            matches.append(tab)
        return matches

    active = get_active_tab(session)
    return [active] if active else []


def choose_one(matches: list[dict], *, allow_first: bool) -> dict:
    if not matches:
        raise BridgeError("No matching Chrome tab found.")
    if len(matches) == 1 or allow_first:
        return matches[0]

    summary = [
        {
            "id": tab["id"],
            "windowIndex": tab["windowIndex"],
            "tabIndex": tab["tabIndex"],
            "title": tab["title"],
            "url": tab["url"],
        }
        for tab in matches[:10]
    ]
    raise BridgeError(
        "Multiple matching tabs found. Narrow the search or pass --first.\n"
        + json.dumps(summary, indent=2, ensure_ascii=False)
    )


def activate_tab(tab: dict) -> dict:
    script = f"""
on run argv
  set targetWindow to item 1 of argv as integer
  set targetTab to item 2 of argv as integer
  tell application "{CHROME_APP}"
    if not running then error "{CHROME_APP} is not running."
    set active tab index of window targetWindow to targetTab
    set index of window targetWindow to 1
    activate
    return "ok"
  end tell
end run
"""
    run_osascript(script, args=[str(tab["windowIndex"]), str(tab["tabIndex"])])
    session = get_session()
    active = get_active_tab(session)
    if not active:
        raise BridgeError("Activated tab, but could not read the new active tab state.")
    return active


def open_url(url: str, mode: str) -> dict:
    script = f"""
on run argv
  set targetMode to item 1 of argv
  set targetUrl to item 2 of argv
  tell application "{CHROME_APP}"
    activate
    if (count of windows) = 0 then make new window
    if targetMode is "replace-active" then
      set URL of active tab of front window to targetUrl
    else
      tell front window
        make new tab with properties {{URL:targetUrl}}
        set active tab index to (count of tabs)
      end tell
    end if
    return "ok"
  end tell
end run
"""
    run_osascript(script, args=[mode, url])
    session = get_session()
    active = get_active_tab(session)
    if not active:
        raise BridgeError("Opened URL, but could not read the active tab afterward.")
    return active


def eval_js(expression: str) -> object:
    script = f"""
on run argv
  set jsExpr to item 1 of argv
  tell application "{CHROME_APP}"
    if not running then error "{CHROME_APP} is not running."
    return execute active tab of front window javascript jsExpr
  end tell
end run
"""
    try:
        raw = run_osascript(script, args=[expression])
    except BridgeError as exc:
        message = str(exc)
        if "Executing JavaScript through AppleScript is turned off" in message or "Allow JavaScript from Apple Events" in message:
            raise BridgeError("Chrome has JavaScript from Apple Events disabled. Enable View > Developer > Allow JavaScript from Apple Events.") from exc
        raise

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge to an already-open Google Chrome session on macOS.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Report Chrome status, active tab, and JS bridge availability.")
    subparsers.add_parser("active", help="Return the active tab in the frontmost Chrome window.")

    list_parser = subparsers.add_parser("list-tabs", help="List open Chrome tabs.")
    list_parser.add_argument("--query", help="Filter tabs by title or URL substring.")

    for name in ("activate", "eval-js"):
        cmd = subparsers.add_parser(name, help=f"{name.replace('-', ' ').title()} against a selected tab.")
        cmd.add_argument("--tab-id", help="Exact Chrome tab id to target.")
        cmd.add_argument("--title-contains", help="Case-insensitive title substring.")
        cmd.add_argument("--url-contains", help="Case-insensitive URL substring.")
        cmd.add_argument("--first", action="store_true", help="Use the first match when multiple tabs match.")
        if name == "eval-js":
            cmd.add_argument("--expression", required=True, help="JavaScript expression to evaluate in the active target tab.")

    open_parser = subparsers.add_parser("open", help="Open a URL in the existing Chrome session.")
    open_parser.add_argument("--url", required=True, help="URL to open.")
    open_parser.add_argument("--mode", choices=("new-tab", "replace-active"), default="new-tab")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "status":
            session = get_session()
            payload = {
                "browser": CHROME_APP,
                "running": session.get("running", False),
                "windowCount": len(session.get("windows", [])),
                "tabCount": len(flatten_tabs(session)),
                "activeTab": get_active_tab(session),
                "javascriptFromAppleEvents": check_js_apple_events() if session.get("running") and session.get("windows") else {"enabled": False, "reason": f"{CHROME_APP} has no open windows."},
            }
            emit(payload)
            return 0

        session = get_session()
        require_running(session)

        if args.command == "active":
            active = get_active_tab(session)
            if not active:
                raise BridgeError("No active Chrome tab found.")
            emit(active)
            return 0

        if args.command == "list-tabs":
            tabs = flatten_tabs(session)
            if args.query:
                query = args.query.lower()
                tabs = [tab for tab in tabs if query in tab["title"].lower() or query in tab["url"].lower()]
            emit(tabs)
            return 0

        if args.command == "activate":
            matches = find_matches(
                session,
                tab_id=args.tab_id,
                title_contains=args.title_contains,
                url_contains=args.url_contains,
            )
            chosen = choose_one(matches, allow_first=args.first)
            emit({"activated": activate_tab(chosen)})
            return 0

        if args.command == "open":
            emit({"activeTab": open_url(args.url, args.mode)})
            return 0

        if args.command == "eval-js":
            matches = find_matches(
                session,
                tab_id=args.tab_id,
                title_contains=args.title_contains,
                url_contains=args.url_contains,
            )
            chosen = choose_one(matches, allow_first=args.first)
            active = activate_tab(chosen)
            emit({"activeTab": active, "result": eval_js(args.expression)})
            return 0

        parser.error(f"Unknown command: {args.command}")
        return 2
    except BridgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
