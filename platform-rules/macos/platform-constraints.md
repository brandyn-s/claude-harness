# platform-constraints — macos (injected at session start by session_start_modules/platform_rules.py)
# Extracted from rules/platform-constraints.md (2026-06-13). Cross-platform invariants/guards stay in the parent rule; this file holds the macos-only DOMAIN sections and loads ONLY on macos.

# ─── DOMAIN: Claude Code Bash sandbox (macOS) ───

ON sandbox_breaks_a_child_process_that_execs_another_binary:
  # The sandbox does not only block NETWORK and WRITES — it breaks command
  # RESOLUTION for external binaries invoked from a subshell or from a
  # subprocess of the tool you called. The failure surfaces as a message
  # about the INNER binary's subject matter, never as "sandbox denied", so it
  # is routinely misdiagnosed as a defect in the thing under test.
  # THREE instances, one session (2026-07-27):
  #   1. `git` inside a piped `while read` loop -> `command not found: git`,
  #      rc=127. With `2>/dev/null` attached this became a silent WRONG
  #      ANSWER for all 15 repos (every one reported "not ignored").
  #   2. code-graph's `index_repository` -> its child `git rev-parse` blocked
  #      -> identity capture failed reporting "not a Git repository: <path>"
  #      for 19 valid checkouts (see code-graph-dev.md).
  #   3. /pr-fix's documented `wc`/`tr`-after-`git fetch` loop failure — the
  #      same mechanism, already in that skill's Phase 1.
  REQUIRED: for any loop or tool whose child execs a binary, either run
    unsandboxed (`dangerouslyDisableSandbox`) or call the binary by ABSOLUTE
    path (`/usr/bin/git`).
  FORBIDDEN: `2>/dev/null` on a probe whose ABSENCE of output you will
    interpret — it converts rc=127 into a confident false negative.

ON brew_install_or_toolchain_install:
  # The Bash sandbox breaks Homebrew's platform/bottle resolution. Sandboxed
  # `brew install <pkg>` fails with "This is a Tier 3 configuration" +
  # "Error: <pkg>: no bottle available!" even on a fully supported host
  # (macOS 26 arm64, bottle exists). The Tier-3 message is a sandbox
  # artifact, NOT a real platform problem — do not build from source and
  # do not report upstream.
  REQUIRED: run `brew install` with dangerouslyDisableSandbox: true.
  # INCIDENT 2026-06-11 code-graph setup: sandboxed `brew install go`
  # failed twice with Tier-3/no-bottle; unsandboxed retry poured
  # go 1.26.4 arm64_tahoe cleanly on the first attempt.

ON go_build_or_module_download:
  # Sandboxed Go builds fail on TWO independent walls: (1) network —
  # proxy.golang.org is not in the sandbox host allowlist, so module
  # downloads die; (2) filesystem — GOPATH (~/go) and GOCACHE
  # (~/Library/Caches/go-build) are outside the sandbox write allowlist.
  REQUIRED: run `go build` / `go test` / `make build` unsandboxed, OR
            set GOPATH/GOMODCACHE/GOCACHE to sandbox-writable paths
            ($TMPDIR or the repo dir) for sandbox-compatible builds.
  # PREEMPTED 2026-06-11: identified before failure during the code-graph
  # build; the unsandboxed `make release` completed clean (CGO +
  # tree-sitter grammars, exit 0).

ON git_branch_or_config_write_under_sandbox:
  # `git checkout -b` / `git fetch` inside an allowed repo dir can still
  # emit `error: could not write config file .git/config: Operation not
  # permitted` under the sandbox. The branch/ref operations SUCCEED;
  # only the config write (e.g. branch tracking setup) is lost. Symptom
  # downstream: `git config --get branch.<name>.remote` returns nothing.
  # Root cause unverified (suspected sandbox deny-pattern matching .git
  # config paths) — the behavior is reproducible, the matching rule is not
  # confirmed. [WORKAROUND - root cause unfixed]: push with `git push -u
  # origin <branch>` — the pr-guard hook REQUIRES an upstream tracking ref
  # before `gh pr create`, so a bare explicit-refspec push (this note's
  # former advice) trips it (2026-06-12 aws-commercial-security-infra
  # PR #54: bare-refspec push → pr-guard block; `git push -u` fixed it
  # instantly, tracking write succeeded). If the sandbox blocks the
  # tracking-config write (the 2026-06-11 mode below), run `git push -u`
  # unsandboxed before creating the PR.
  # INCIDENT 2026-06-11 code-graph fix/portable-mcp-json: branch created
  # despite two config-write errors; push + PR worked with explicit refspec
  # (the pr-guard tracking block was first observed 2026-06-12).

ON gh_repo_clone_or_git_clone_https_under_sandbox:
  # Sandboxed `gh repo clone` fails with `Post "https://api.github.com/graphql":
  # tls: failed to verify certificate: x509: OSStatus -26276` — the sandbox
  # network proxy's TLS interception is rejected by gh's clone-path TLS stack.
  # Read-side `gh` calls (repo list, api GET) can succeed sandboxed in the
  # SAME session, so a working list call is NOT evidence clones will work.
  # The OSStatus error is a sandbox artifact, not a real cert/network problem.
  # SCOPE (extended 2026-06-11): the same OSStatus -26276 hits ANY gh call
  # that POSTs over Go's TLS stack — `gh api graphql`, `gh pr create`,
  # `gh issue create` — not just clones. REST GETs (`gh api repos/...`,
  # `gh issue list`) work sandboxed in the same session. Upstream class:
  # anthropics/claude-code #23416 / #29533 / #26466 (macOS sandbox breaks
  # Security.framework TLS verification for Go binaries — gh, terraform);
  # enhancement #62582 proposes auto-managed allowMachLookup.
  # NUANCE: settings.json sandbox.excludedCommands includes "gh *", so a
  # DIRECT `gh ...` invocation is auto-unsandboxed and works. The failure
  # only bites when gh is NESTED — `bash script.sh` that calls gh, loops,
  # compound commands — where the outer command doesn't match the exclusion.
  REQUIRED: for nested/scripted gh POST calls, either run the Bash call
            with dangerouslyDisableSandbox: true, or restructure so the
            top-level command starts with `gh ` (matches excludedCommands).
  # INCIDENT 2026-06-11 example-labs-org clone batch: `gh repo list` succeeded
  # sandboxed; all 11 sandboxed `gh repo clone` calls failed with
  # OSStatus -26276; unsandboxed retry cloned all 11 cleanly.
  # INCIDENT 2026-06-11 gather-claude Watching sweep: sandboxed
  # `gh api graphql` batch failed 3/3 with OSStatus -26276; the REST
  # `gh api repos/.../contents/CHANGELOG.md` GET succeeded sandboxed
  # moments earlier. Unsandboxed retry returned all 120 issue states.

ON git_checkout_merge_rebase_in_claude_config:
  # Sandboxed git in ~/.claude cannot REPLACE working-tree files under the
  # sandbox write deny-list (~/.claude/skills, ~/.claude/hooks,
  # settings.json): checkout/merge/rebase that rewrite those paths fail
  # with `error: unable to unlink old '<path>': Operation not permitted`.
  # WORSE THAN AN ABORT — the failure is PARTIAL and DESTRUCTIVE:
  #   (1) `git checkout <branch>` moves HEAD but leaves deny-listed files
  #       at old content (status shows phantom M entries);
  #   (2) a subsequent `git merge`'s read-tree RESETS files on WRITABLE
  #       paths (rules/, agent-memory/) to HEAD **before** aborting on the
  #       deny-listed paths — silently DESTROYING any uncommitted changes
  #       in those writable files, including changes made by concurrent
  #       sessions.
  #   (3) `git diff HEAD` afterward shows clean — which is NOT evidence of
  #       no loss; clobbered uncommitted work is exactly what diff-vs-HEAD
  #       cannot see.
  REQUIRED: before ANY branch-switch/merge/rebase in ~/.claude, snapshot
            dirty files first (`git stash push -u -- <dirty paths>` or
            copy them out), and run the git command itself with
            dangerouslyDisableSandbox: true. Verify afterward against the
            PRE-operation snapshot, never against HEAD.
  PREFER: committing on the current branch over branch-switch flows in
          ~/.claude — direct commits and staging are unaffected
          (object-db writes only). The Edit tool is also unaffected (not
          Bash-sandboxed), which is how file edits can succeed while a
          merge of those same files fails.
  # INCIDENT 2026-06-11 claude-config model-default bump: commit on
  # feature branch succeeded; sandboxed `git checkout mac-port && git
  # merge` failed unlink on 10 skills/ files + settings.json AND the
  # aborted merge reset uncommitted edits in rules/platform-constraints.md
  # (this file — macOS sandbox + Keychain domains, restored from the
  # session-start snapshot) and agent-memory/topics/code-graph-accuracy.md
  # (content lost — not in any snapshot). A "no data loss" verification
  # via diff-vs-HEAD was falsely reassuring.

# ─── DOMAIN: macOS Keychain via `security` CLI ───

ON keychain_read_for_secret (security find-generic-password -s NAME -w):
  # Two failure shapes, both transient-looking:
  # (1) WRONG SERVICE NAME — the user may have saved the item under a
  #     different service string than you suggested (e.g. ANTHROPIC_API_KEY
  #     not anthropic-api-key). Diagnose with a METADATA-ONLY dump:
  #       security dump-keychain ~/Library/Keychains/login.keychain-db \
  #         | grep -iE '"svce"|"acct"' | grep -iE '<likely-terms>'
  #     NEVER pass -d to dump-keychain (decrypts and prints secret data).
  # (2) ACCESS PROMPT RACE — each `security` read of an item without an
  #     "Always Allow" ACL pops a GUI prompt. The non-interactive Bash
  #     tool can't answer it; the read returns EMPTY (looks like
  #     NOT FOUND / not readable) until the user clicks through. Reads
  #     succeed on retry after the user clicks Allow / Always Allow.
  REQUIRED: on empty read of an item known to exist, tell the user to
            watch for the Keychain dialog and click "Always Allow",
            then retry — do NOT conclude the item is missing.
  REQUIRED: when telling a user to store a secret, give them
            `security add-generic-password -a "$USER" -s NAME -w` with
            NO value after -w (interactive hidden prompt, keeps the
            secret out of shell history and session transcripts), run
            in their own Terminal, not via the Bash tool.
  # Verification reads: report length only ([ -n "$v" ] && echo "len ${#v}"),
  # never the value — same transcript-leak discipline as the env-var
  # FORBIDDEN blocks above.
  # PATTERN (2026-06-11): MCP launchers (~/.local/bin/codebase-memory-mcp-launch)
  # read Keychain at spawn and exec — keys never land in ~/.claude.json/env.
  # Recurring prompts on "Claude Code-credentials" = upstream #67315 (partition
  # reset on token refresh) — NOT our launchers. Incidents + #67315 mechanism:
  # Full: #keychain-read-prompts

# ─── DOMAIN: macOS ───

ON macos_shell_execution:
  the Bash tool shell is zsh: unquoted vars do NOT word-split — use
    `${=var}`, arrays (`"${arr[@]}"`), or list args explicitly. (Bit a
    `git add $list` batch on 2026-06-11: git received ONE bogus pathspec.)
    RECURRENCE 2026-07-27, NEW SHAPE — `set -- $spec` inside a for-loop:
    iterating `for spec in "repo 27" "repo 99"` then `set -- $spec` to split
    into `$1`/`$2` assigns the WHOLE string to `$1` and leaves `$2` empty, so
    `gh pr view $2 --repo $1` failed `argument required when using the --repo
    flag` for every item. The `ORGS=(--owner a --owner b)` array form two
    sections up in /pr-fix exists for exactly this reason; the positional-
    param split is the same trap wearing a different hat. USE a `while IFS='|'
    read -r a b` loop over a heredoc (splits on the delimiter in BOTH shells),
    or an associative array — never `set --` on an unquoted var.
    They also do NOT glob-expand: `ls $pat` passes the literal `*` — use
    `${~pat}` or write the glob inline. (2026-06-12: a disk-count check
    read 0 for every population because `$p` never expanded.) RELATED zsh
    NOMATCH: an UNQUOTED literal `?`/`[`/`*` in any arg is a filename glob,
    and on no match zsh ERRORS `no matches found: <arg>` and runs NOTHING
    (bash passes the literal through). Bites URL/query args worst —
    `gh api repos/o/r/contents/f.md?ref=main` and `curl host/p?a=1` both
    die on the `?`. FIX: QUOTE any arg carrying a URL query string or
    `[]?*`: `gh api "...?ref=main"`. Generalizes the azure-automation
    `[?...]` JMESPath entry to ALL unquoted special-char args.
    (Recurred several times 2026-06-17 on gh api `?ref=` URLs.)
    AND zsh has READ-ONLY special variables bash treats as plain: `status`
    (aliases `$?`) is the common trap — `status=$(...)` aborts the script
    with "read-only variable: status". Also reserved: `pipestatus`, `ERRNO`.
    Use `st`/`rc` as scratch names in .sh files the zsh Bash tool runs.
    (2026-06-12: a dirty-tree scan script died on `status=` mid-/pr-fix.)
    AND indirect (variable-variable) expansion differs: bash `${!var}` is a
    zsh SYNTAX ERROR — `(eval):N: bad substitution`. zsh uses the `(P)`
    parameter flag: `${(P)var}`. Bites env-presence probe loops that iterate
    a var-NAME list and dereference each (`for v in A B C; do echo ${!v}; done`).
    FIX: `val="${(P)v}"`. (2026-07-15: an env-var presence probe died on
    `${!v}` first try; `${(P)v}` worked.)
    AND `$var:word` applies a zsh HISTORY MODIFIER — it silently EATS the
    first letter of what follows the colon. `git show "$sha:ci.tf"` expands to
    `<sha>i.tf` (`:c` = command-path lookup), so `git show` reports "ambiguous
    argument '<sha>i.tf'" or, worse, the surrounding pipeline just returns 0
    hits and reads as "the content is MISSING". Measured 2026-07-29 — 10 of 12
    letters are modifiers, so this fires on most real filenames:
      :a absolute-path  :c command-path  :e ext-only  :h head  :l lowercase
      :q quote          :r root         :s subst     :t tail  :u uppercase
    Only `:p` and `:x` pass through. So `$sha:main.tf` WORKS while
    `$sha:ci.tf` breaks — the bug is DATA-DEPENDENT on the first letter,
    which is why it survives casual testing.
    FIX: **BRACES, not quotes** — `${sha}:ci.tf`. Quoting alone is NOT
    sufficient: `"$sha":ci.tf` still broke when the command was itself nested
    inside an outer double-quoted layer (the outer layer strips the inner
    quotes before zsh parses the modifier). Bites `git show <ref>:<path>`,
    `git cat-file`, `docker <img>:<tag>` and any `ref:path` argument.
    PREFER doing multi-ref `git show` comparisons in a .py file with
    `subprocess.run(["git","show",f"{ref}:{path}"])` — no shell parses it.
    (2026-07-29: `git show "$sha:ci.tf"` returned 0 for BOTH shas while
    verifying a merged IAM grant, and the false zero nearly became a reported
    "the fix is missing" conclusion; a Python re-check found it present in all
    three trees. Same family as the `!`/`[?...]`/`/`-prefix entries — a shell
    metacharacter turning a probe into a confident wrong answer.)
  stock /bin/bash is 3.2 (2007, GPLv2 freeze): no mapfile, no associative
    arrays, no ${var,,}, no EPOCHREALTIME. Homebrew bash is 5.x. Inline bash
    must stay 3.2-compatible unless Homebrew bash is confirmed first.
  BSD userland, not GNU: sed -i '' (not sed -i), no grep -P (use -E or rg),
    no date -d (use date -j -f), stat -f%z (not stat -c%s). gsed/gawk/gdate
    via brew when GNU semantics are required.
  `timeout`/`gtimeout` are now INSTALLED on this host (brew coreutils 9.11,
    2026-06-14; `timeout` symlinked into /opt/homebrew/bin so it does NOT shadow
    the other BSD coreutils). A FRESH macOS ships neither — `brew install coreutils`
    (unsandboxed) provides `gtimeout`; without it, bound a command with
    `cmd & pid=$!; sleep N; kill $pid 2>/dev/null` (check `kill -0` first to
    distinguish still-running from exited), or `perl -e 'alarm shift; exec @ARGV' N cmd`.
  SEPARATE limit: the Bash TOOL kills foreground commands at its own timeout
    (default 120000ms / 2 min, max 300000); a `sleep 300` to poll a job dies
    with exit 143. Use `run_in_background: true` for long waits, or poll in
    sub-2-min windows — do NOT confuse this harness limit with the `timeout` binary.
  # awk -v multiline divergence already covered: #awk-multiline-on-macos

ON playwright_mcp_first_use (any repo whose .mcp.json registers @playwright/mcp —
    ExampleUI/Labs visual-verification):
  # @playwright/mcp defaults to the chrome CHANNEL (real Google Chrome at
  # /Applications/Google Chrome.app), ABSENT on a fresh macOS host — the first
  # browser_navigate errors "Chromium distribution 'chrome' is not found".
  REQUIRED: `brew install --cask google-chrome` (unsandboxed — sandbox breaks
            cask bottle resolution). The already-running MCP picks it up on the
            next navigate (lazy browser launch — no session restart needed).
  FORBIDDEN: `npx playwright install chrome` — it switches to root for system
             deps and fails ("a terminal is required") with no TTY.
  # 2026-06-14 ExampleUI frontend session (first Playwright MCP use on this host).

ON macos_file_access_under_Documents_Desktop_Downloads:
  # TCC privacy: terminal apps need a per-app grant for these dirs; denial is
  # a SILENT EACCES inside hooks (no prompt for non-GUI children).
  REQUIRED: grant the terminal Full Disk Access, or keep repos and the
            knowledge-base OUTSIDE TCC-protected dirs (~/dev, ~/work).
  FORBIDDEN: iCloud "Desktop & Documents Folders" sync on working dirs —
             evicts files to dataless stubs and sync-conflicts git repos.
  # MID-SESSION LOSS (2026-06-16): access can work for most of a session then
  # DROP — EPERM "Operation not permitted" on the Read tool AND Bash `ls`
  # (even dangerouslyDisableSandbox), after working fine earlier same session.
  # Suspected (UNVERIFIED): the shell held the dir via an open fd while cwd was
  # inside; a post-merge `cd` away released it and TCC denied re-entry. It
  # RECOVERED later the same session (transient). Do NOT flail on cwd / `git -C`
  # — they all fail once the fd is gone.
  ROUTE-AROUND: clone the repo fresh OUTSIDE ~/Documents (`gh repo clone
            <org/repo> /tmp/<name>`) and do EVERYTHING from there — reads,
            greps, AND the full branch→commit→push→PR flow. Verified 2026-06-16:
            KB marker verification + the marker-flip PR (#861) both ran from a
            /tmp clone while ~/Documents/knowledge-base was EPERM-blocked.

ON macos_downloaded_binary_fails_to_run ("cannot be opened", "killed: 9"):
  CAUSE: com.apple.quarantine xattr (Gatekeeper) on non-brew downloads.
  RECOVERY: install via brew, or xattr -d com.apple.quarantine <file>.

ON macos_binary_aborts_dyld_Library_not_loaded (SIGABRT / exit 134 at spawn):
  CAUSE: Homebrew dependency skew — a partial upgrade batch repoints
    /opt/homebrew/opt/<lib> to a new keg; a NOT-upgraded dependent (still
    referencing the old dylib install name) aborts on every fresh spawn.
  FIX: `brew upgrade <dependent>` — NOT reinstall (re-pours the same
    bottle with the same stale install names).
  CAUTION: already-running processes survive (dyld binds at spawn); do NOT
    restart them or Claude Code before the upgrade — respawns hit the abort.
  # INCIDENT 2026-06-11 node/llhttp blank statusline. Diagnosis recipe +
  # full: incidents#homebrew-partial-upgrade-dyld-skew

ON macos_python_resolution:
  /usr/bin/python3 is the Xcode CLT stub — triggers an install dialog if CLT
    is missing, and version-drifts with Xcode updates.
  REQUIRED: Homebrew python3 for hooks and MCP server configs (the macOS
    analog of the Windows Python314/pythonw.exe pin). Verify which python3
    with `command -v python3` before registering an MCP server.

ON python_script_subprocesses_a_python_tool (pytest, ruff, mypy, a sibling .py):
  # WHY: `bash -lc "python3 -m pytest …"` spawns a LOGIN shell whose `python3`
  #   resolves to a DIFFERENT interpreter than the one running the script — on
  #   this host the login-shell python3 has NO pytest (nor the other pip
  #   packages the Bash-tool python3 carries). The import dies to stderr, the
  #   subprocess emits no test summary, and a naive `(\d+) passed` parse reads
  #   ZERO-collected as a SILENT PASS — the worst failure shape (a measurement
  #   that lies). Verified 2026-06-16: `bash -lc "python3 -c 'import pytest'"`
  #   → ModuleNotFoundError, while the script's own interpreter runs the suite.
  REQUIRED: invoke via the SAME interpreter — subprocess.run([sys.executable,
            "-m", "<tool>", …], cwd=<dir>) — pass cwd= rather than `cd && …`.
  REQUIRED: treat 0-collected / empty output as DID-NOT-RUN, not success —
            guard `if passed == 0 and failed == 0:` as a non-pass branch.
  FORBIDDEN: subprocess.run(["bash", "-lc", "… python3 -m <tool> …"]) for any
             tool that must run in the SCRIPT's own environment.
  # INCIDENT 2026-06-16 healthcheck _check_all.py orchestrator: the Hooks-row
  # pytest ran via `bash -lc` and reported "0 tests passed → PASS"; switching
  # to [sys.executable, "-m", "pytest"], cwd=hooks + the 0/0 guard fixed it
  # (PR #1329). Caught only because "0 tests passed" looked wrong.

ON macos_many_open_files (code-search/code-graph indexing, MCP servers):
  CAUSE: default ulimit -n is 256 on macOS.
  RECOVERY: ulimit -n 4096 in the launching shell; persistent fix via
    launchctl limit maxfiles.

ON macos_wifi_or_ssid_state_check (network connectivity diagnosis):
  # `networksetup -getairportnetwork en0` reports "You are not associated
  # with an AirPort network" EVEN WHEN Wi-Fi is connected and working.
  # Observed 2026-06-15: en0 held inet 10.16.20.169 + status: active and
  # `system_profiler SPAirPortDataType` showed "Status: Connected"
  # (Signal/Noise -55/-95 dBm) while getairportnetwork claimed "not
  # associated." Reading getairportnetwork as "Wi-Fi is down" is a phantom.
  # SUSPECTED cause (mechanism unverified this session): modern macOS
  # (Sonoma+/Tahoe 26) gates SSID/association introspection behind Location
  # Services authorization for the CALLING process; the non-GUI Bash tool
  # lacks the grant, so the SSID query returns empty/"not associated." The
  # legacy `airport -I` CLI is removed on Tahoe — same blind spot.
  REQUIRED: judge Wi-Fi association from `ifconfig en0` (inet present +
            status: active) and `system_profiler SPAirPortDataType`
            ("Status: Connected" + Signal/Noise), NOT from
            `networksetup -getairportnetwork`.
  FORBIDDEN: concluding "Wi-Fi disconnected" from getairportnetwork alone —
             cross-check the interface IP + system_profiler first.

ON macos_long_running_background_job (indexing, corpus clones, gathers, evals):
  # Laptop idle-sleep suspends the job mid-run; the harness still shows the
  # task as running, so the stall is SILENT until the timeout/next check.
  REQUIRED: wrap with `caffeinate -i <cmd>` (holds off idle sleep for the
    command's lifetime only; no system-wide settings change).
  # Scheduled jobs: the launchd templates (templates/launchd/) already wrap.

ON macos_env_vars_for_hooks_and_mcps:
  # ~/.zshrc only affects interactive terminal sessions.
  REQUIRED: exports consumed by Claude Code hooks/MCPs go in ~/.zshenv (or
    env_loader.py), so GUI-launched and non-interactive contexts see them.

ON macos_secret_storage (API keys consumed by hooks/MCPs):
  REQUIRED: macOS Keychain — generic password, service claude/<ENV_VAR>,
    seeded once via bin/keychain-seed; env_loader resolves env-var-first then
    Keychain. CLAUDE_KEYCHAIN_SECRETS=0 disables the Keychain tier.
  # TWO service-name conventions coexist (2026-06-12): claude/<VAR> (above)
  # AND bare <VAR> (MCP-launcher convention; the LIVE ANTHROPIC_API_KEY /
  # VOYAGE_API_KEY / ANTHROPIC_COMPLIANCE_ACCESS_KEY items are BARE).
  # Keychain fallbacks MUST probe both, claude/-prefixed first (mcp-servers
  # #526: probing one convention read live keys as "not seeded").
  FORBIDDEN: plaintext secret exports in ~/.zshenv/.zshrc once a key is
    seeded (dotfile secrets are what the rotated-key incidents trace to).
  # First read per python binary raises a Keychain ACL prompt — "Always
  # Allow" binds to that binary path; a Homebrew python upgrade re-prompts.

ON homebrew_cask_needs_sudo_but_bash_cannot_sudo (a .pkg cask, e.g. session-manager-plugin):
  # `brew install --cask <pkg>` runs the pkg installer under `sudo`; the Bash tool cannot
  # answer the interactive password prompt ("a terminal is required to read the password"),
  # so the install fails. For a cask whose payload is a plain binary, extract WITHOUT sudo:
  REQUIRED:
    brew fetch --cask <pkg>                                  # download the .pkg to the cache
    PKG=$(find ~/Library/Caches/Homebrew -iname '*<pkg>*.pkg' | head -1)
    cd "$(mktemp -d)"; xar -xf "$PKG"                        # expand the pkg
    mkdir ex && cd ex && tar xf ../Payload                   # Payload is plain (odc) cpio -> tar extracts
    cp -R usr/local/<tool>/* ~/.local/<tool>/                # place binary + siblings (user-writable)
    mkdir -p ~/.local/bin; ln -sf ~/.local/<tool>/bin/<bin> ~/.local/bin/<bin>
  # VERIFY `<bin> --version`; ensure ~/.local/bin is on PATH. New inode (not overwriting a
  # running binary) so no code-sign SIGKILL. 2026-07-19: installed session-manager-plugin
  # 1.2.835.0 this way (cask sudo-blocked). The Payload was ASCII cpio — `tar xf Payload`
  # worked where `gunzip | cpio` did not.

ON echo_or_argument_beginning_with_equals_sign_in_zsh:
  # WHY: zsh performs `=word` filename expansion on any UNQUOTED word starting
  #      with `=` (expands to the command's path, like `=ls` → /bin/ls). An
  #      unknown word is a FATAL expansion error — `echo ===SECTION===` dies
  #      with `(eval): ==SECTION== not found` and kills the ENTIRE command
  #      line (everything chained after `;`/`&&` in that compound never runs,
  #      same partial-state hazard as a hook-blocked compound). bash does not
  #      do this, so the habit imports silently from bash. Hit 3× in one
  #      session (2026-07-22) using `echo ===X===` as an output separator.
  REQUIRED: quote any word starting with `=` (`echo "===X==="`), or use a
    separator that doesn't start with `=` (`echo ---X---`).

ON emitting_a_command_block_for_the_USER_to_paste_into_their_own_shell:
  # WHY: interactive zsh does NOT treat `#` as a comment unless
  #      `interactive_comments` is set, and it is off by default. A `#` line
  #      pasted at the prompt runs as a COMMAND — `command not found: #`.
  #      Two distinct costs, and the second is the dangerous one:
  #        (a) noise — the `#` line errors, the user sees a spurious failure;
  #        (b) SILENT PARTIAL EXECUTION — if the `#` line carried an
  #            INSTRUCTION ("drop line 7 from .gitignore, then:"), it is
  #            skipped while every real command around it succeeds, so the
  #            recipe LOOKS complete and a required step never happened.
  #      Hit twice in one session (2026-07-29): a `# then, with that id:` line
  #      errored with `zsh: command not found: #`, and a `# drop
  #      .terraform.lock.hcl from .gitignore` line was skipped — the lock never
  #      became tracked, and only a post-hoc state check caught it. This is NOT
  #      the agent's own Bash tool (that shell honours `#` fine); it fires only
  #      on blocks the USER pastes.
  # VERIFIED / DO NOT MIS-REFUTE: `options[interactivecomments]` is `off` on
  #      this host. But `zsh -i -c '# x'` does NOT reproduce it — `-c` reads a
  #      script string, not a TTY, so the option does not engage and the line is
  #      silently tolerated. A re-test via `-c` will look like the rule is
  #      wrong. The reproducing condition is a REAL prompt paste; the evidence
  #      is the observed `command not found: #` above, not a `-c` probe.
  FORBIDDEN: any `#` line inside a fenced block intended for the user to paste.
  FORBIDDEN: placeholders (`<id>`, `<sha>`) in a paste block — substitute the
    real value first, or the paste fails on the literal.
  REQUIRED: instructions and commentary go in PROSE OUTSIDE the block; the
    block contains only runnable lines. If a step needs explaining, put the
    explanation above the fence.

# ─── zsh ARGUMENT GLOBBING (distinct from word-splitting) ───

FORBIDDEN: passing_an_unquoted_argument_containing_a_glob_char_to_a_command
  # WHY: zsh does NOT word-split unquoted variables (already documented), but it DOES
  #      glob-expand unquoted arguments containing `*` `?` `[`. Worse than bash: when the
  #      pattern matches NOTHING, zsh ABORTS the whole command with
  #      `zsh: no matches found: --include=*.tf` -- the command never runs, and the error
  #      does not look like a quoting problem. bash would have passed the literal through.
  #      Bites hardest on tool flags that legitimately contain `*`:
  #        grep -r --include=*.tf .        <- ABORTS if no *.tf in CWD
  #        find . -name *.py               <- ABORTS or expands to the first match
  #      USE quotes on any argument containing a glob metacharacter:
  #        grep -r --include='*.tf' .   /   find . -name '*.py'
  # INCIDENT 2026-07-27: `grep -rn -l ... --include=*.tf --include=*.py .` returned
  #      `(eval):1: no matches found: --include=*.tf` and produced NO output; read as
  #      "no Terraform files reference this" for a moment before the error text was
  #      actually read. Re-running with quoted patterns found 9 files immediately.
  #      Pairs with the existing "zsh does NOT word-split" note in project CLAUDE.md --
  #      same shell, OPPOSITE direction: it under-splits variables and over-expands globs.

# ─── DOMAIN: interactive tty input has a MAX_CANON byte limit ───
# FORBIDDEN: routing a value longer than ~1024 bytes through an interactive
#      prompt (Python `input()`, `read`, any tty-line read). In canonical mode
#      the terminal line discipline buffers a line until it sees a newline, and
#      that buffer is MAX_CANON bytes -- 1024 on this host (`getconf MAX_CANON /`).
#      Overflow SILENTLY DROPS the excess INCLUDING the trailing newline, so the
#      read blocks forever with no error and no truncation warning: the program
#      just looks frozen.
# INCIDENT 2026-08-04: handed the user a script that read a ~1500-char OAuth
#      redirect URL (a 1430-char JWT auth code) via `input()`. It hung; the user
#      reported "the script appears to be hanging." Not a logic bug -- the tty
#      canonical buffer filled and swallowed the newline. A JWT, a long OAuth
#      authorize/redirect URL, a base64 blob, or any long secret hits this.
# FIX: never route long input through a tty prompt. Read it from the clipboard
#      (`pbpaste`), from a file, or from an env var / Keychain item. If a script
#      must accept a pasted long value, write a two-invocation flow (first run
#      prints + exits; user copies; second run reads the clipboard) rather than
#      one blocking prompt. This also keeps long secrets off the tty entirely.

# ─── DOMAIN: three shell/awk semantics that pass review and fail at runtime ───
# All three cost a fix-and-rerun cycle in ONE session (2026-08-30, claude-gov
# installer + its test harness). Each is invisible on inspection: the code reads
# exactly like the thing it is not doing.

# (1) BSD `wc -l` PADS its output, so a STRING compare against a count fails.
# FORBIDDEN: [[ "$(wc -l <<<"$v")" == "1" ]]
#      BSD wc emits leading spaces ("       1"), so this is false while the value
#      is CORRECT. GNU wc does not pad, so the bug is macOS-only and a CI leg on
#      ubuntu will not reproduce it.
# FIX: count with awk -- `lines="$(awk 'END { print NR }' <<<"$v")"` -- or strip
#      with `| tr -d ' '`. Prefer awk: it needs no cleanup step to forget.
#      Same class as the documented `stat -f%z` / `sed -i ''` BSD divergences
#      above; this one is worse because it yields a WRONG COMPARISON rather than
#      an error.

# (2) `local` expands ALL its arguments BEFORE it creates any of them.
# FORBIDDEN: local home="$1" conf="${home}/.aws/config"
#      Arguments to the `local` builtin are expanded by the shell first, so
#      `${home}` resolves in the OUTER scope -- unset under `set -u`, which
#      aborts the function with "home: unbound variable". It reads like an
#      ordinary sequential assignment and is the single most plausible-looking
#      line in the file.
# FIX: one `local` per derived value:
#      `local home="$1"` / `local conf="${home}/.aws/config"`.
#      The same trap applies to `declare`, `export`, and `readonly`.

# (3) awk's `exit` inside a rule STILL RUNS the END block.
# FORBIDDEN: relying on `exit` to skip END --
#      `/pat/ { print "found"; exit }  END { print "none" }`
#      emits BOTH lines. `exit` jumps TO END; it does not leave the program.
# FIX: set a flag in the rule and gate END on it --
#      `/pat/ { seen=1; print "found"; exit }  END { if (!seen) print "none" }`
# WHY IT MATTERS BEYOND TIDINESS: a two-line value silently becomes a
#      DIFFERENT value downstream. A Jamf extension attribute emitted
#      "canonical\nnone"; Jamf takes the LAST <result> line, so every HEALTHY
#      Mac classified as the failure state. Caught only because the EA's own
#      test asserted the verdict was exactly one line -- assert the LINE COUNT
#      of any awk-produced scalar, not just its content.

# ─── DOMAIN: after the FIRST bash guard block, stop judging each command ───
# The parent rule already says a guard blocking the same SHAPE twice is a signal
# about your default, not the guard. Two macOS-specific sharpenings:
#   (a) the trigger is not SIZE. `inline-python-guard` fires on `python3 -c`
#       bodies over 300 CHARS, and a "quick helper" crosses 300 almost
#       immediately, so the blocked shape is not the one that FEELS big.
#   (b) the class is ANY deterministic bash guard, not one named guard.
# INCIDENT 2026-08-30, FOUR blocks in one session across TWO guards:
#      credential-guard x2 (`grep`/`sed` over a MKTEMP SANDBOX path that merely
#      CONTAINED `.aws/config` -- the guard matches command TEXT, not the real
#      target), inline-python-guard x1 (a ~25-line marker check), then
#      bash-tail-buffering-guard x1 (`python3 script.py | grep -E` used purely
#      to shorten DISPLAY output). The large metrics script in the same session
#      was correctly written to a file; only the "small" ones were inlined, and
#      the 4th block came AFTER this very section was drafted naming only
#      bash-security-guard -- scoping the lesson to one guard is how it recurs.
# FIX: once ANY bash guard has fired once in a session, for the rest of it:
#      write every python body and every multi-step shell body to a file under
#      /tmp/claude/ and execute it, and get LESS OUTPUT from the PRODUCER
#      (`-m`, `-n`, `--limit`, a slice in the script) instead of appending
#      `| grep`/`| head`. Do not re-evaluate per command whether this one is
#      small enough -- that judgment is exactly what the guards keep catching.
