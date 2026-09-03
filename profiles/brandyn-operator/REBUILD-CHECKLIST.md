# Rebuild checklist for the owner's macOS workstation

Owner-specific companion to `docs/macos-migration.md`. Every command below is
meant to be run by a person in a terminal, one block at a time, verifying the
stated check before moving on. Nothing here is run by the installer. Replace
`~/code` with your code directory if it differs.

Preconditions on this machine, verified 2026-09-03: Homebrew at
`/opt/homebrew`, Python 3.14 via Homebrew, Claude Code 2.1.259, `gh`
authenticated, `uv`, `rg`, `jq`, `gitleaks`, `semgrep`, `trivy`, `node`.

## 0. Secrets

The operator keychain `backup-cli` holds items whose service name is the bare
variable name (`TAVILY_API_KEY`). The session-start loader accepts that form
since 2026-09-03; `bin/keychain-seed` still writes `claude/<NAME>`, and both
resolve. Two housekeeping steps first:

```bash
# The keychain file is in ~/Downloads, which cleanup tools and sync clients treat as disposable.
mv ~/Downloads/backup-cli.keychain-db ~/Library/Keychains/
security list-keychains -d user -s \
  ~/Library/Keychains/login.keychain-db \
  ~/Library/Keychains/backup-cli.keychain-db
security list-keychains -d user                     # both paths listed

# Metadata only; never print a value into a transcript.
for k in EXA_API_KEY FIRECRAWL_API_KEY TAVILY_API_KEY XAI_API_KEY ANTHROPIC_API_KEY VOYAGE_API_KEY; do
  security find-generic-password -s "$k" >/dev/null 2>&1 && echo "present: $k" || echo "ABSENT:  $k"
done
```

`OPENAI_API_KEY` is absent. Roundtable requires it; gather-vendor and
scout-skills use it for their GPT legs. Add it only if you want those.

## 1. The harness checkout

```bash
mkdir -p ~/code
git clone https://github.com/brandyn-s/claude-harness ~/code/claude-harness
cd ~/code/claude-harness && git log --oneline -3   # expect the 2026-09-03 review-fix commits
```

Never make this checkout your live `~/.claude`.

## 2. Kernel and operator layer

```bash
cd ~/code/claude-harness
bash install.sh
#   Apply the fresh-laptop settings profile?      y
#   Add the Brandyn operator layer?               y
#   Install the recommended fresh-laptop core?    y
#   Wire these hooks into settings.json?          y
#   Continue to pick more components?             n
python3 bin/fresh_laptop_doctor.py                 # every line PASS
```

The profile merge unions with your existing `permissions.allow`, so the
curated read-only allow list survives. Then add the network allowlist the
sandbox needs, or every network command will fall back to a prompt:

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
s = json.loads(p.read_text())
net = s.setdefault("sandbox", {}).setdefault("network", {})
have = set(net.get("allowedDomains", []))
have |= {"github.com", "api.github.com", "*.githubusercontent.com", "ghcr.io", "*.ghcr.io",
         "registry.npmjs.org", "*.npmjs.org", "pypi.org", "files.pythonhosted.org",
         "api.anthropic.com", "*.anthropic.com", "formulae.brew.sh", "*.amazonaws.com",
         "api.tavily.com", "api.exa.ai", "api.firecrawl.dev", "api.x.ai", "api.voyageai.com"}
net["allowedDomains"] = sorted(have)
p.write_text(json.dumps(s, indent=2) + "\n")
print("allowedDomains:", len(net["allowedDomains"]))
PY
```

Prove the guard is live before relying on it:

```bash
printf '{"tool_name":"Bash","tool_input":{"command":"rm -rf *"}}' \
  | ~/.claude/hooks/run-hook bash-security-guard.py; echo "exit=$?"     # expect 2
printf '{"tool_name":"Bash","tool_input":{"command":"git status"}}' \
  | ~/.claude/hooks/run-hook bash-security-guard.py; echo "exit=$?"     # expect 0
```

## 3. Integrations, one at a time

`claude mcp add` cannot run inside a Claude Code session; use a plain terminal.
Verify each server with `claude mcp list` before adding the next. Keys are
pulled from the keychain at registration time and stored by Claude Code in
`~/.claude.json`, so re-run the block if you rotate a key.

```bash
# Tavily (the org gateway variant lives in mcp-servers/managed-mcp.json; this is the local one)
claude mcp add --scope user tavily \
  -e TAVILY_API_KEY="$(security find-generic-password -s TAVILY_API_KEY -w)" \
  -- npx -y tavily-mcp@latest

# Exa: without --tools only 2 of 4 tools load (exa-labs/exa-mcp-server#77)
claude mcp add --scope user exa \
  -e EXA_API_KEY="$(security find-generic-password -s EXA_API_KEY -w)" \
  -- npx -y exa-mcp-server --tools=web_search_exa,get_code_context_exa,web_fetch_exa,crawling_exa

# Firecrawl
claude mcp add --scope user firecrawl \
  -e FIRECRAWL_API_KEY="$(security find-generic-password -s FIRECRAWL_API_KEY -w)" \
  -- npx -y firecrawl-mcp

claude mcp list                                     # all three Connected
```

Memory search runs from your `mcp-servers` repo and needs the Voyage key:

```bash
git clone https://github.com/brandyn-s/mcp-servers ~/code/mcp-servers
cd ~/code/mcp-servers/memory-search
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.lock
mkdir -p ~/.local/bin
cat > ~/.local/bin/memory-search-mcp-launch <<'SH'
#!/usr/bin/env bash
export VOYAGE_API_KEY="$(security find-generic-password -s VOYAGE_API_KEY -w)"
exec "$HOME/code/mcp-servers/memory-search/.venv/bin/python" \
     "$HOME/code/mcp-servers/memory-search/memory_search_mcp.py" "$@"
SH
chmod +x ~/.local/bin/memory-search-mcp-launch       # a launcher without the exec bit shows "Failed to connect"
claude mcp add --scope user memory-search -- ~/.local/bin/memory-search-mcp-launch
claude mcp list
```

The index lives at `~/.claude/memory-search.db`; the first reindex needs the
knowledge base from step 4 to exist.

Code intelligence, once `code-graph` and `code-search` are published: follow
their READMEs, install the binary, register
`~/.local/bin/codebase-memory-mcp-launch` the same way, then install the
`code-intelligence` plugin bundle in step 5.

## 4. Knowledge base and API docs

```bash
git clone https://github.com/brandyn-s/claude-knowledge-base ~/Documents/knowledge-base
cd ~/Documents/knowledge-base
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.lock
.venv/bin/python tools/kb.py build && .venv/bin/python tools/kb.py check
git clone https://github.com/brandyn-s/api-docs ~/Documents/api-docs
```

macOS TCC gates `~/Documents`; grant the terminal access when prompted, and
keep both clones out of iCloud sync.

## 5. Skills

From inside a Claude Code session:

```
/plugin marketplace add brandyn-s/claude-harness
/plugin install security-scanner@claude-harness        # now
/plugin install knowledge-ops@claude-harness           # after steps 3 and 4
/plugin install code-intelligence@claude-harness       # after code-graph and code-search land
```

Companion skills and the standalone checklists are single directories; copy
the ones you want:

```bash
cd ~/code/claude-harness
for s in interview plateau-diagnose search-axis-rotate \
         debugging-hypotheses legacy-code-tdd design-evidence-first review-depth-by-risk; do
  cp -R "skills/$s" ~/.claude/skills/
done
sed -i '' 's/mcp__memory-search__memory_search/Grep/' ~/.claude/skills/interview/SKILL.md   # only if memory-search is not registered
```

Do not install the planning-toolkit bundle's remaining superpowers-era skills;
the installed superpowers 6.3.0 plugin owns brainstorming, TDD, debugging,
subagent-driven development, and completion verification.

## 6. Rules, one at a time

The kernel installed `outcome-over-verification.md` and `claude-md-quality.md`;
the operator layer added `operator-discipline.md`. Promote further rules only
through the gate in `docs/fresh-laptop-control-audit.md`: a measured failure,
no native control covers it, a direct test exists, and the cost is bounded.

## 7. Organisation content, when that work starts

```bash
git clone https://github.com/brandyn-s/claude-config ~/code/claude-config      # never as ~/.claude
mkdir -p ~/.claude/agent-memory/topics
cp ~/code/claude-config/agent-memory/topics/*.md ~/.claude/agent-memory/topics/
```

Copy individual organisation skills from that checkout as the work demands
them. The worker agent, the topic auto-loader, and 23 skills read
`~/.claude/agent-memory/topics/`, so this step is what makes them useful.

## Completion gate

One green doctor run, `claude mcp list` showing every registered server
Connected, and a normal session in which a sandboxed edit-and-test loop runs
without prompts while `rm -rf *` is refused.
