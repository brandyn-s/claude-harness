# platform-constraints — windows (injected at session start by session_start_modules/platform_rules.py)
# Extracted from rules/platform-constraints.md (2026-06-13). Cross-platform invariants/guards stay in the parent rule; this file holds the windows-only DOMAIN sections and loads ONLY on windows.

# ─── DOMAIN: Shell / PowerShell ───  [WINDOWS-ONLY — inactive on macOS]
# On macOS the shell is zsh and there is no PowerShell. Ignore this domain.
# Use ps/pgrep (safe forms in the wide-process-listing FORBIDDEN above).

ON powershell_invocation:  # [WINDOWS-ONLY — inactive on macOS]
  MUST use pwsh (PS7+), never powershell (5.1)
  MUST pwsh -NoProfile -NonInteractive -File script.ps1 (never inline from bash)
  env vars: $env:VAR="value" (never `set VAR=value`)

ON powershell_string_parser_error_with_misleading_line_number:
  # WHY: pwsh lexer treats smart quotes as string delimiters; "missing terminator"
  #      is reported FAR downstream of the real defect.
  FORBIDDEN: assuming the parser-reported line is the defect line.
  REQUIRED: scan for non-ASCII bytes BEFORE the cited line; replace with ASCII.
  # INCIDENT 2026-05-20 profile.ps1. Full: #pwsh-smart-quote-lexer

ON windows_process_query (find PIDs by command line, parent, etc.):
  REQUIRED: pwsh `Get-CimInstance Win32_Process | Where {$_.CommandLine -like '*pattern*'}`
  FORBIDDEN: wmic — deprecated on Win11, SILENT EMPTY output (exit 0).
  # INCIDENT 2026-05-02 (killed wrong PIDs). Full: #wmic-silent-empty-output

ON powershell_acl_detection_or_remediation (Get-Acl loops, Intune detection, STIG checks):
  REQUIRED: validate against a REAL file round-tripped through Set-Acl/Get-Acl — NEVER
            in-memory FileSecurity (empty .Access → false COMPLIANT for every case).
  REQUIRED: assert BOTH a should-PASS and a should-FAIL case before trusting detection.
  FORBIDDEN: write-mask from FullControl/Modify composites (includes read bits).
  REQUIRED: enumerate write bits explicitly — WriteData,AppendData,WriteExtendedAttributes,
            WriteAttributes,Delete,DeleteSubdirectoriesAndFiles,ChangePermissions,TakeOwnership
  # INCIDENT 2026-05-29 REM051. Full: #powershell-acl-write-mask

ON interactive_npm_cli:
  # The UV_HANDLE_CLOSING assertion/hang was WINDOWS-ONLY (a Windows libuv TTY
  #   handle-close bug). macOS quick repro 2026-06-10: Node readline TTY
  #   open→render→close→exit under a real pty exited rc=0 in 0.06s with no
  #   assertion. Does NOT reproduce on macOS libuv.
  # STILL TRUE EVERYWHERE: arrow-key / menu input CANNOT be piped (no stdin
  #   keystrokes), and the Bash tool has no TTY, so interactive prompts still
  #   need a non-interactive path.
  fallbacks: (1) --yes/--non-interactive flags, (2) pipe "y" for Y/n, (3) gh api
             contents/ + manual install. Arrow-key CANNOT be piped.
