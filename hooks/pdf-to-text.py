"""PreToolUse hook for Read: Auto-convert PDF files to Markdown.

Intercepts Read tool calls on .pdf files, converts them to .md using
pymupdf4llm (preserves tables, headers, structure), caches the result
in a central directory, and blocks the Read with a redirect to the .md file.

Protocol:
  Exit 0 = allow (stderr = advisory warning shown to Claude)
  Exit 2 = block (stderr = reason shown to Claude)

Cache dir: ~/Documents/converted-pdfs/
  Mirrors source path structure to avoid collisions:
    ~/Documents/STIG/readme.pdf -> converted-pdfs/STIG/readme.md

Cache: skips conversion if .md exists, has the sentinel header, and is
newer than the .pdf. Refuses to overwrite .md files not created by this hook.

Security: paths passed via sys.argv to subprocess (no f-string injection).
Timeout: 295s subprocess, 300s hook (settings.json) - handles any PDF size.
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
    (env override → author's local path → sys.executable). PDF
    conversion additionally requires `pymupdf4llm` in the chosen
    interpreter's site-packages; if it's missing, the hook falls back
    gracefully to native Read with a WARN."""
    explicit = os.environ.get("PYTHON_EXE")
    if explicit:
        return explicit
    if sys.platform == "win32":
        local = Path(_HOME, "AppData/Local/Programs/Python/Python312/python.exe")
        if local.exists():
            return str(local)
    return sys.executable


# CUSTOMIZE: Set $PYTHON_EXE to override; default tries the author's
# local install first, then falls back to sys.executable.
PYTHON_312 = _resolve_python_exe()

SENTINEL = "<!-- pdf-to-markdown-hook -->"
CACHE_DIR = str(Path(_HOME, "Documents/converted-pdfs"))
DOCUMENTS_ROOT = str(Path(_HOME, "Documents"))

# Conversion script passed to subprocess - paths come via sys.argv
CONVERT_SCRIPT = r"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
import pymupdf4llm

SENTINEL = "<!-- pdf-to-markdown-hook -->"
pdf_path = sys.argv[1]
md_path = sys.argv[2]

os.makedirs(os.path.dirname(md_path), exist_ok=True)

md_text = pymupdf4llm.to_markdown(pdf_path)
if not md_text or not md_text.strip():
    print("EMPTY")
    sys.exit(1)

with open(md_path, "w", encoding="utf-8") as f:
    f.write(SENTINEL + "\n")
    f.write(f"<!-- source: {pdf_path} -->\n\n")
    f.write(md_text)
print("OK")
"""


def _get_md_path(pdf_path):
    """Derive the cached .md path in the central cache directory.

    Mirrors directory structure relative to Documents root.
    Falls back to flat filename for paths outside Documents.

    Examples:
      .../Documents/STIG/readme.pdf -> converted-pdfs/STIG/readme.md
      .../Documents/ExampleTarget/manual.pdf -> converted-pdfs/ExampleTarget/manual.md
      C:/Other/report.pdf -> converted-pdfs/report.md
    """
    norm_pdf = os.path.normpath(pdf_path).replace("\\", "/")
    norm_root = os.path.normpath(DOCUMENTS_ROOT).replace("\\", "/")

    if norm_pdf.lower().startswith(norm_root.lower() + "/"):
        # Strip Documents root, keep relative structure
        rel = norm_pdf[len(norm_root) + 1:]
    else:
        # Outside Documents - just use the filename
        rel = os.path.basename(norm_pdf)

    # Replace .pdf with .md
    rel_md = os.path.splitext(rel)[0] + ".md"
    return os.path.join(CACHE_DIR, rel_md).replace("\\", "/")


def block(reason):
    """Block the Read tool call. Exit 2 + stderr = Claude sees the reason."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def warn(message):
    """Allow the Read but show advisory. Exit 0 + stderr = Claude sees the warning."""
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
    if not file_path.lower().endswith(".pdf"):
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    md_path = _get_md_path(file_path)

    # Cache check: .md exists, has our sentinel, and is newer than .pdf
    if os.path.isfile(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
        except (OSError, UnicodeDecodeError):
            first_line = ""

        if first_line == SENTINEL:
            # It's ours - check freshness
            pdf_mtime = os.path.getmtime(file_path)
            md_mtime = os.path.getmtime(md_path)
            md_size = os.path.getsize(md_path)
            if md_mtime >= pdf_mtime and md_size > len(SENTINEL) + 10:
                block(
                    f"PDF auto-converted to Markdown (cached, {md_size:,} bytes). "
                    f"Read this file instead: {md_path}"
                )
            # Stale or corrupt cache - reconvert below
        else:
            # .md exists but wasn't created by us - don't overwrite
            warn(
                f"Existing .md file found at {md_path} (not auto-generated). "
                "Skipping PDF conversion to avoid overwriting. "
                "Delete or rename the .md file to enable auto-conversion."
            )

    # Convert PDF to Markdown - paths passed as arguments, not in code string
    try:
        pdf_size = os.path.getsize(file_path)
        pdf_mb = pdf_size / 1024 / 1024

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
                f"PDF auto-converted to Markdown ({md_size:,} bytes from {pdf_mb:.1f}MB PDF). "
                f"Read this file instead: {md_path}"
            )

        # Conversion failed - clean up partial .md if it exists
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
                f"PDF-to-Markdown conversion failed: {err_msg}. "
                "Falling back to native PDF read."
            )

    except subprocess.TimeoutExpired:
        # Clean up partial .md on timeout
        if os.path.isfile(md_path):
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    if f.readline().strip() == SENTINEL:
                        os.remove(md_path)
            except OSError:
                pass
        warn(
            f"PDF conversion timed out (>295s, {pdf_mb:.1f}MB PDF). "
            "Falling back to native PDF read."
        )
    except (FileNotFoundError, OSError) as e:
        warn(f"PDF conversion error: {e}. Falling back to native PDF read.")

    # If we get here, allow the Read
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
