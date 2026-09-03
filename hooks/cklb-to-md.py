"""PreToolUse hook for Read: Auto-convert .cklb (STIG checklist JSON) to Markdown.

Intercepts Read tool calls on .cklb files, converts them to .md with a status
summary and rules table, expands `open` findings with check_content + fix_text,
caches in ~/Documents/converted-cklb/, and blocks the Read with a redirect to the .md.

Converter-hook pattern: sentinel header, freshness check, subprocess isolation,
paths via argv.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_HOME = str(Path.home())


def _resolve_python_exe():
    """Pick the Python interpreter for the conversion subprocess.

    Priority:
      1. $PYTHON_EXE if set (operator override).
      2. The author's local install on Windows if the file exists.
      3. `sys.executable` — the Python running this hook. Guaranteed
         to exist; has whatever module ecosystem is in the current
         environment. Works on every operator's machine and every CI
         runner without per-environment configuration. Prior literal
         `Path(_HOME, "AppData/Local/Programs/Python/Python312/python.exe")`
         broke on the Windows CI runner where Python lives at
         `C:\\hostedtoolcache\\windows\\Python\\3.12.10\\x64\\python.exe`,
         producing WinError 2 (file not found) at every conversion.
    """
    explicit = os.environ.get("PYTHON_EXE")
    if explicit:
        return explicit
    if sys.platform == "win32":
        local = Path(_HOME, "AppData/Local/Programs/Python/Python312/python.exe")
        if local.exists():
            return str(local)
    return sys.executable


PYTHON_312 = _resolve_python_exe()

SENTINEL = "<!-- cklb-to-md-hook -->"
CACHE_DIR = str(Path(_HOME, "Documents/converted-cklb"))
DOCUMENTS_ROOT = str(Path(_HOME, "Documents"))

CONVERT_SCRIPT = r"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

SENTINEL = "<!-- cklb-to-md-hook -->"
STATUSES = ["open", "not_a_finding", "not_applicable", "not_reviewed"]
SEVERITIES = ["high", "medium", "low"]

src_path = sys.argv[1]
md_path = sys.argv[2]

os.makedirs(os.path.dirname(md_path), exist_ok=True)

try:
    with open(src_path, "r", encoding="utf-8") as f:
        data = json.load(f)
except (json.JSONDecodeError, OSError) as e:
    print(f"PARSE_ERROR: {e}")
    sys.exit(1)

def esc(s):
    if s is None:
        return ""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()

def truncate(s, n=500):
    if s is None:
        return ""
    s = str(s).strip()
    if len(s) > n:
        return s[:n].rstrip() + " ..."
    return s

lines = []
lines.append(SENTINEL)
lines.append(f"<!-- source: {src_path} -->")
lines.append("")
lines.append(f"# CKLB: {esc(data.get('title', 'unknown'))}")
lines.append("")

td = data.get("target_data") or {}
if td:
    tgt_bits = []
    for k in ("host_name", "ip_address", "fqdn", "target_type", "role"):
        v = td.get(k)
        if v:
            tgt_bits.append(f"**{k}**: {esc(v)}")
    if tgt_bits:
        lines.append("## Target")
        lines.append("")
        lines.append(" | ".join(tgt_bits))
        lines.append("")

stigs = data.get("stigs", []) or []
for stig in stigs:
    name = stig.get("display_name") or stig.get("stig_name") or "STIG"
    stig_id = stig.get("stig_id", "")
    release = stig.get("release_info", "")
    version = stig.get("version", "")
    rules = stig.get("rules", []) or []

    # Counts
    counts = {s: {sev: 0 for sev in SEVERITIES} for s in STATUSES}
    totals_status = {s: 0 for s in STATUSES}
    totals_sev = {sev: 0 for sev in SEVERITIES}
    for r in rules:
        st = (r.get("status") or "not_reviewed").lower()
        sev = (r.get("severity") or "").lower()
        if st not in counts:
            counts[st] = {sev: 0 for sev in SEVERITIES}
            totals_status[st] = 0
        if sev not in counts[st]:
            counts[st][sev] = 0
        counts[st][sev] += 1
        totals_status[st] = totals_status.get(st, 0) + 1
        if sev in totals_sev:
            totals_sev[sev] += 1

    lines.append(f"## {esc(name)}")
    lines.append("")
    meta = []
    if stig_id:
        meta.append(f"**stig_id**: {esc(stig_id)}")
    if version:
        meta.append(f"**version**: {esc(version)}")
    if release:
        meta.append(f"**release**: {esc(release)}")
    meta.append(f"**rules**: {len(rules)}")
    lines.append(" | ".join(meta))
    lines.append("")

    lines.append("### Status x Severity")
    lines.append("")
    lines.append("| Status | High | Medium | Low | Total |")
    lines.append("|---|---:|---:|---:|---:|")
    for st in STATUSES:
        row = counts.get(st, {})
        lines.append(
            f"| {st} | {row.get('high', 0)} | {row.get('medium', 0)} | "
            f"{row.get('low', 0)} | {totals_status.get(st, 0)} |"
        )
    lines.append(
        f"| **total** | **{totals_sev['high']}** | **{totals_sev['medium']}** | "
        f"**{totals_sev['low']}** | **{len(rules)}** |"
    )
    lines.append("")

    # Full rules table
    lines.append("### Rules")
    lines.append("")
    lines.append("| Group | Rule ID | Severity | Status | Title |")
    lines.append("|---|---|---|---|---|")
    # Sort: open first, then by severity desc, then by group_id
    sev_order = {"high": 0, "medium": 1, "low": 2, "": 3}
    status_order = {"open": 0, "not_reviewed": 1, "not_applicable": 2, "not_a_finding": 3}
    rules_sorted = sorted(
        rules,
        key=lambda r: (
            status_order.get((r.get("status") or "").lower(), 9),
            sev_order.get((r.get("severity") or "").lower(), 9),
            r.get("group_id", ""),
        ),
    )
    for r in rules_sorted:
        lines.append(
            f"| {esc(r.get('group_id', ''))} | {esc(r.get('rule_id', ''))} | "
            f"{esc(r.get('severity', ''))} | {esc(r.get('status', ''))} | "
            f"{esc(r.get('rule_title', ''))} |"
        )
    lines.append("")

    # Detailed blocks for open findings
    opens = [r for r in rules_sorted if (r.get("status") or "").lower() == "open"]
    if opens:
        lines.append(f"### Open Findings Detail ({len(opens)})")
        lines.append("")
        for r in opens:
            lines.append(f"#### {r.get('group_id', '')} / {r.get('rule_id', '')} ({r.get('severity', '')})")
            lines.append("")
            lines.append(f"**Title**: {esc(r.get('rule_title', ''))}")
            lines.append("")
            fd = (r.get("finding_details") or "").strip()
            if fd:
                lines.append("**Finding details**:")
                lines.append("")
                lines.append("```")
                lines.append(truncate(fd, 1500))
                lines.append("```")
                lines.append("")
            cc = (r.get("check_content") or "").strip()
            if cc:
                lines.append("**Check**:")
                lines.append("")
                lines.append("```")
                lines.append(truncate(cc, 1500))
                lines.append("```")
                lines.append("")
            ft = (r.get("fix_text") or "").strip()
            if ft:
                lines.append("**Fix**:")
                lines.append("")
                lines.append("```")
                lines.append(truncate(ft, 1500))
                lines.append("```")
                lines.append("")
            com = (r.get("comments") or "").strip()
            if com:
                lines.append(f"**Comments**: {esc(truncate(com, 500))}")
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
    if not file_path.lower().endswith(".cklb"):
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
                    f"CKLB auto-converted to Markdown (cached, {md_size:,} bytes). "
                    f"Read this file instead: {md_path}"
                )
        else:
            warn(
                f"Existing .md file found at {md_path} (not auto-generated). "
                "Skipping CKLB conversion to avoid overwriting. "
                "Delete or rename the .md file to enable auto-conversion."
            )

    try:
        src_size = os.path.getsize(file_path)
        src_kb = src_size / 1024

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
                f"CKLB auto-converted to Markdown ({md_size:,} bytes from {src_kb:.0f}KB .cklb). "
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
                f"CKLB-to-Markdown conversion failed: {err_msg}. "
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
            f"CKLB conversion timed out (>295s, {src_kb:.0f}KB). "
            "Falling back to native Read."
        )
    except (FileNotFoundError, OSError) as e:
        warn(f"CKLB conversion error: {e}. Falling back to native Read.")

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
