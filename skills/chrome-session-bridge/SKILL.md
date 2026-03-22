---
name: chrome-session-bridge
description: Connect to the user's already-open Google Chrome session on macOS instead of launching an isolated browser. Use when Codex needs to inspect real tabs, read active URLs and titles, switch tabs, open URLs, or optionally run page JavaScript inside the user's existing logged-in Chrome profile. Best for browser tasks where cookies, sessions, or the current open tabs matter and the user wants work done in their normal browser.
---

# Chrome Session Bridge

Use the user's real Google Chrome session on macOS.

This skill exists for cases where isolated automation is the wrong tool because the user's live tabs, cookies, or logged-in state matter.

## Requirements

- macOS
- `Google Chrome.app` installed
- Chrome already running
- macOS Automation permission allowed for terminal/agent control of Chrome

Optional for deeper page control:

- in Chrome, enable `View > Developer > Allow JavaScript from Apple Events`

Without that Chrome setting, the bridge can still:

- list windows and tabs
- read active tab title and URL
- switch tabs
- open URLs in the current Chrome session

## Safety Model

Observe freely:

- `status`
- `active`
- `list-tabs`

Pause and confirm before:

- opening URLs
- switching away from the user's current page if that could interrupt work
- running JavaScript in a live page
- submitting forms or changing page state through injected JavaScript

Prefer narrow, reversible actions.

## Primary Tool

Use:

```bash
python3 /Users/ibe/Documents/NemoCodex/codex-engineering-skills/skills/chrome-session-bridge/scripts/chrome_bridge.py <command>
```

## Core Workflow

1. check bridge health with `status`
2. inspect tabs with `active` or `list-tabs`
3. locate the target tab by id, title, or URL
4. switch only if needed
5. if the task needs DOM-level inspection or interaction, test whether JavaScript from Apple Events is enabled
6. run the smallest page script needed and report the result clearly

## Commands

### Status

```bash
python3 .../chrome_bridge.py status
```

Use first. It reports:

- whether Chrome is running
- active tab details
- whether JavaScript from Apple Events is enabled

### Active Tab

```bash
python3 .../chrome_bridge.py active
```

Returns the frontmost active tab as JSON.

### List Tabs

```bash
python3 .../chrome_bridge.py list-tabs
python3 .../chrome_bridge.py list-tabs --query reddit
```

Use `--query` to filter by title or URL.

### Activate A Tab

```bash
python3 .../chrome_bridge.py activate --tab-id 2051335149
python3 .../chrome_bridge.py activate --title-contains "Reddit"
python3 .../chrome_bridge.py activate --url-contains "reddit.com/settings"
```

If the match is ambiguous, narrow the query instead of guessing.

### Open A URL In The Real Session

```bash
python3 .../chrome_bridge.py open --url "https://www.reddit.com/" --mode new-tab
python3 .../chrome_bridge.py open --url "https://www.reddit.com/" --mode replace-active
```

Prefer `new-tab` unless the user clearly wants the current tab replaced.

### Evaluate Page JavaScript

```bash
python3 .../chrome_bridge.py eval-js --expression "document.title"
python3 .../chrome_bridge.py eval-js --title-contains "Reddit" --expression "location.href"
```

Use this only when:

- the user wants deeper inspection or page interaction
- Chrome has `Allow JavaScript from Apple Events` enabled

If JavaScript execution is disabled, the script returns a clear setup message instead of pretending it worked.

## Working Style

When using this skill:

- mention that you are using the real Chrome session
- name the exact tab you inspected or switched to
- distinguish clearly between read-only inspection and state-changing actions
- report browser results with concrete evidence such as title, URL, tab id, and returned script values

## Limits

This skill does not magically bypass every browser restriction.

Important limits:

- it is built for `Google Chrome` on macOS
- DOM scripting depends on Chrome's Apple Events JavaScript setting
- it does not automatically understand page semantics without either tab metadata or explicit JS inspection

If the bridge fails, first check:

1. Chrome is running
2. macOS Automation permission has been granted
3. Chrome's JavaScript from Apple Events setting is enabled when DOM scripting is required
