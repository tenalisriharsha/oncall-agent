"""Capture real terminal screenshots of the CLI for the README.

Runs each command for real with the installed console script, captures
its actual stdout/stderr and exit code, and renders that captured text
(unedited) into a dark terminal-window HTML template that gets
screenshotted with a headless browser. Nothing here hand-types or
rewrites command output.

This script is a one-off dev tool for generating docs/screenshots/, not
part of the shipped package.
"""

from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

from ansi2html import Ansi2HTMLConverter
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / ".venv" / "bin" / "oncall-agent"
OUT_DIR = REPO_ROOT / "docs" / "screenshots"

ENV = {
    "COLUMNS": "104",
    "LINES": "40",
    "TERM": "xterm-256color",
    "FORCE_COLOR": "1",
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
}

CONVERTER = Ansi2HTMLConverter(dark_bg=True, scheme="xterm", inline=True)

TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    margin: 0;
    background: #0d1117;
    display: flex;
    justify-content: center;
    padding: 24px;
  }}
  .window {{
    width: 980px;
    background: #0d1117;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 0 0 1px #30363d;
    font-family: "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  }}
  .titlebar {{
    background: #161b22;
    padding: 10px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid #30363d;
  }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
  .dot.red {{ background: #ff5f56; }}
  .dot.yellow {{ background: #ffbd2e; }}
  .dot.green {{ background: #27c93f; }}
  .label {{
    color: #8b949e;
    font-size: 12px;
    margin-left: 8px;
  }}
  .body {{
    padding: 18px 20px 22px 20px;
    color: #c9d1d9;
    font-size: 13.5px;
    line-height: 1.55;
    white-space: pre;
    overflow-x: auto;
  }}
  .prompt {{
    color: #3fb950;
    font-weight: bold;
  }}
  .cmd {{
    color: #e6edf3;
  }}
  .exit-ok {{ color: #3fb950; }}
  .exit-err {{ color: #f85149; }}
</style>
</head>
<body>
  <div class="window">
    <div class="titlebar">
      <div class="dot red"></div>
      <div class="dot yellow"></div>
      <div class="dot green"></div>
      <div class="label">{label}</div>
    </div>
    <div class="body"><span class="prompt">$</span> <span class="cmd">{command}</span>
{output}
{exit_line}</div>
  </div>
</body>
</html>
"""


def run_capture(args: list[str], label: str, filename: str) -> None:
    command_display = "oncall-agent " + " ".join(args)
    result = subprocess.run(
        [str(BIN), *args],
        cwd=REPO_ROOT,
        env=ENV,
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    body_html = CONVERTER.convert(combined, full=False)

    if result.returncode == 0:
        exit_line = f'<span class="exit-ok">[exit {result.returncode}]</span>'
    else:
        exit_line = f'<span class="exit-err">[exit {result.returncode}]</span>'

    page_html = TEMPLATE.format(
        label=html.escape(label),
        command=html.escape(command_display),
        output=body_html,
        exit_line=exit_line,
    )

    html_path = OUT_DIR / f"{filename}.html"
    html_path.write_text(page_html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1040, "height": 900})
        page.goto(html_path.as_uri())
        window = page.locator(".window")
        png_path = OUT_DIR / f"{filename}.png"
        window.screenshot(path=str(png_path))
        browser.close()

    html_path.unlink()
    print(f"captured {filename}.png (exit={result.returncode})")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    audit_log = "docs-demo-audit.jsonl"
    (REPO_ROOT / audit_log).unlink(missing_ok=True)

    run_capture(["--help"], "oncall-agent --help", "01-cli-help")
    run_capture(["config"], "oncall-agent config", "02-config")
    run_capture(
        ["demo", "--scenario", "deploy-regression", "--audit-log", audit_log],
        "oncall-agent demo --scenario deploy-regression",
        "03-demo-deploy-regression",
    )
    run_capture(
        ["demo", "--scenario", "oom", "--audit-log", audit_log],
        "oncall-agent demo --scenario oom",
        "04-demo-oom",
    )
    run_capture(
        ["demo", "--scenario", "unknown", "--audit-log", audit_log],
        "oncall-agent demo --scenario unknown",
        "05-demo-unknown",
    )
    run_capture(
        ["audit", "--audit-log", audit_log],
        "oncall-agent audit",
        "06-audit-trail",
    )
    run_capture(
        ["demo", "--scenario", "bogus"],
        "oncall-agent demo --scenario bogus (invalid input)",
        "07-demo-invalid-scenario",
    )

    (REPO_ROOT / audit_log).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
