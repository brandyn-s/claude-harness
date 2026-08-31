# macOS provisioning for this Claude Code architecture — run `brew bundle`
# from the repo root after installing Homebrew (https://brew.sh).
# See docs/macos-migration.md for the full migration checklist.

brew "bash"        # stock macOS bash is 3.2; run-hook latency telemetry needs 5.x (EPOCHREALTIME)
brew "git"
brew "gh"          # post-merge-sync hook shells out to `gh pr merge`
brew "node"        # claude-hud statusline + npx-launched MCP servers
brew "python@3.13" # hooks + local MCP servers; pin MCP registrations to this (see rules/platform-constraints.md ON macos_python_resolution)
brew "ripgrep"
brew "jq"
brew "uv"          # uv-managed MCP servers

# Per-need — uncomment what this machine actually uses:
# brew "semgrep"      # /semgrep skill
# brew "awscli"       # prefer boto3 scripts per platform-constraints, but the CLI is handy
# brew "poppler"      # pdftoppm for the pdf-to-text hook's image fallback
# cask "powershell"   # pwsh — only if running Intune/STIG .ps1 work from templates/
# cask "orbstack"     # Docker runtime for local Fargate image work — lighter than Docker
#                     # Desktop; remember --platform linux/amd64 (see platform-constraints
#                     # ON docker_image_build_for_ecs_fargate_from_apple_silicon)
