"""PreToolUse hook for Read: Auto-convert .nessus (Tenable XML) to Markdown.

Intercepts Read tool calls on .nessus files, converts them to .md with a
findings summary and per-severity tables, caches in ~/Documents/converted-nessus/,
and blocks the Read with a redirect to the .md file.

Mirrors pdf-to-text.py: sentinel header, freshness check, subprocess isolation,
paths via argv (not f-string interpolation).

Cache dir: ~/Documents/converted-nessus/
  Mirrors source path structure relative to Documents when applicable.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_HOME = str(Path.home())


def _resolve_python_exe():
    """Pick the Python interpreter for the conversion subprocess. See
    cklb-to-md.py docstring of the same name for the priority rationale
    (env override → author's local path → sys.executable). Resolves the
    Windows-CI WinError 2 class."""
    explicit = os.environ.get("PYTHON_EXE")
    if explicit:
        return explicit
    if sys.platform == "win32":
        local = Path(_HOME, "AppData/Local/Programs/Python/Python312/python.exe")
        if local.exists():
            return str(local)
    return sys.executable


PYTHON_312 = _resolve_python_exe()

SENTINEL = "<!-- nessus-to-md-hook -->"
CACHE_DIR = str(Path(_HOME, "Documents/converted-nessus"))
DOCUMENTS_ROOT = str(Path(_HOME, "Documents"))

CONVERT_SCRIPT = r"""
import os
import sys
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

SENTINEL = "<!-- nessus-to-md-hook -->"
SEVERITY_NAMES = {0: "Info", 1: "Low", 2: "Medium", 3: "High", 4: "Critical"}

nessus_path = sys.argv[1]
md_path = sys.argv[2]

os.makedirs(os.path.dirname(md_path), exist_ok=True)

try:
    tree = ET.parse(nessus_path)
except ET.ParseError as e:
    print(f"PARSE_ERROR: {e}")
    sys.exit(1)

root = tree.getroot()
report = root.find("Report")
if report is None:
    print("NO_REPORT")
    sys.exit(1)

report_name = report.get("name", "unknown")
hosts = report.findall("ReportHost")

# Collect all findings with host context
findings = []  # (severity_int, host, port, proto, plugin_id, plugin_name, cve, cvss3)
host_summaries = []  # (host, os, ip, total_items)

for host in hosts:
    host_name = host.get("name", "unknown")
    props = {}
    hp = host.find("HostProperties")
    if hp is not None:
        for tag in hp.findall("tag"):
            key = tag.get("name", "")
            if key:
                props[key] = (tag.text or "").strip()
    host_os = props.get("operating-system", "").splitlines()[0] if props.get("operating-system") else ""
    host_ip = props.get("host-ip", "")
    items = host.findall("ReportItem")
    host_summaries.append((host_name, host_ip, host_os, len(items)))
    for item in items:
        try:
            sev = int(item.get("severity", "0"))
        except ValueError:
            sev = 0
        port = item.get("port", "")
        proto = item.get("protocol", "")
        plugin_id = item.get("pluginID", "")
        plugin_name = item.get("pluginName", "")
        cve_elem = item.find("cve")
        cve = (cve_elem.text or "").strip() if cve_elem is not None else ""
        cvss3_elem = item.find("cvss3_base_score")
        cvss3 = (cvss3_elem.text or "").strip() if cvss3_elem is not None else ""
        findings.append((sev, host_name, port, proto, plugin_id, plugin_name, cve, cvss3))

# Severity counts
sev_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
for f in findings:
    sev_counts[f[0]] = sev_counts.get(f[0], 0) + 1

def esc(s):
    if s is None:
        return ""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()

lines = []
lines.append(SENTINEL)
lines.append(f"<!-- source: {nessus_path} -->")
lines.append("")
lines.append(f"# Nessus Scan: {esc(report_name)}")
lines.append("")
lines.append(f"- Hosts scanned: {len(hosts)}")
lines.append(f"- Total findings: {len(findings)}")
lines.append("")
lines.append("## Severity Summary")
lines.append("")
lines.append("| Severity | Count |")
lines.append("|---|---:|")
for s in (4, 3, 2, 1, 0):
    lines.append(f"| {SEVERITY_NAMES[s]} | {sev_counts.get(s, 0)} |")
lines.append("")
lines.append("## Hosts")
lines.append("")
lines.append("| Host | IP | OS | Findings |")
lines.append("|---|---|---|---:|")
for h in host_summaries:
    lines.append(f"| {esc(h[0])} | {esc(h[1])} | {esc(h[2])} | {h[3]} |")
lines.append("")

# Findings tables per severity (Critical/High/Medium only; Low/Info in collapsed list)
findings.sort(key=lambda r: (-r[0], r[1], r[4]))
for threshold, label in [(4, "Critical"), (3, "High"), (2, "Medium")]:
    group = [f for f in findings if f[0] == threshold]
    if not group:
        continue
    lines.append(f"## {label} Findings ({len(group)})")
    lines.append("")
    lines.append("| Host | Port/Proto | Plugin ID | Plugin Name | CVE | CVSSv3 |")
    lines.append("|---|---|---|---|---|---|")
    for f in group:
        _sev, host, port, proto, pid, pname, cve, cvss3 = f
        pp = f"{port}/{proto}" if port else ""
        lines.append(f"| {esc(host)} | {esc(pp)} | {esc(pid)} | {esc(pname)} | {esc(cve)} | {esc(cvss3)} |")
    lines.append("")

low_info = [f for f in findings if f[0] <= 1]
if low_info:
    lines.append(f"## Low / Info ({len(low_info)})")
    lines.append("")
    lines.append("| Severity | Host | Port/Proto | Plugin ID | Plugin Name |")
    lines.append("|---|---|---|---|---|")
    for f in low_info:
        sev, host, port, proto, pid, pname, _cve, _cvss3 = f
        pp = f"{port}/{proto}" if port else ""
        lines.append(f"| {SEVERITY_NAMES[sev]} | {esc(host)} | {esc(pp)} | {esc(pid)} | {esc(pname)} |")
    lines.append("")

with open(md_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))

print("OK")
"""


def _get_md_path(src_path):
    norm_src = os.path.normpath(src_path).replace("\\", "/")
    norm_root = os.path.normpath(DOCUMENTS_ROOT).replace("\\", "/")
    if norm_src.lower().startswith(norm_root.lower() + "/"):
        rel = norm_src[len(norm_root) + 1:]
    else:
        rel = os.path.basename(norm_src)
    rel_md = os.path.splitext(rel)[0] + ".md"
    return os.path.join(CACHE_DIR, rel_md).replace("\\", "/")


def block(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def warn(message):
    print(message, file=sys.stderr)
    sys.exit(0)


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if hook_input.get("tool_name") != "Read":
        sys.exit(0)

    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path.lower().endswith(".nessus"):
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    md_path = _get_md_path(file_path)

    if os.path.isfile(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
        except (OSError, UnicodeDecodeError):
            first_line = ""

        if first_line == SENTINEL:
            src_mtime = os.path.getmtime(file_path)
            md_mtime = os.path.getmtime(md_path)
            md_size = os.path.getsize(md_path)
            if md_mtime >= src_mtime and md_size > len(SENTINEL) + 10:
                block(
                    f"Nessus auto-converted to Markdown (cached, {md_size:,} bytes). "
                    f"Read this file instead: {md_path}"
                )
        else:
            warn(
                f"Existing .md file found at {md_path} (not auto-generated). "
                "Skipping Nessus conversion to avoid overwriting. "
                "Delete or rename the .md file to enable auto-conversion."
            )

    try:
        src_size = os.path.getsize(file_path)
        src_mb = src_size / 1024 / 1024

        proc = subprocess.run(
            [PYTHON_312, "-c", CONVERT_SCRIPT, file_path, md_path],
            capture_output=True,
            text=True,
            timeout=295,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0 and "OK" in proc.stdout:
            md_size = os.path.getsize(md_path) if os.path.isfile(md_path) else 0
            block(
                f"Nessus auto-converted to Markdown ({md_size:,} bytes from {src_mb:.1f}MB .nessus). "
                f"Read this file instead: {md_path}"
            )

        if os.path.isfile(md_path):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    if f.readline().strip() == SENTINEL:
                        os.remove(md_path)
            except OSError:
                pass

        if proc.stderr:
            err_msg = proc.stderr.strip()[:200]
            warn(
                f"Nessus-to-Markdown conversion failed: {err_msg}. "
                "Falling back to native Read."
            )

    except subprocess.TimeoutExpired:
        if os.path.isfile(md_path):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    if f.readline().strip() == SENTINEL:
                        os.remove(md_path)
            except OSError:
                pass
        warn(
            f"Nessus conversion timed out (>295s, {src_mb:.1f}MB). "
            "Falling back to native Read."
        )
    except (FileNotFoundError, OSError) as e:
        warn(f"Nessus conversion error: {e}. Falling back to native Read.")

    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: any unhandled exception must fail open (exit 0) so a
    # converter bug never disrupts the underlying Read.
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
