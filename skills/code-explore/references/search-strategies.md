# Multi-Phrasing Search Strategies

> Empirical results from dual-embedding and HyDE testing (2026-04-11).
> 16 query pairs across Nix, Rust, TypeScript on the a large Rust/Nix monorepo.

## Critical Gotchas

- NEVER use HyDE for generic language constructs (`Result<T, Error>`, `async fn`, `impl Trait`). These match thousands of functions and produce noise. HyDE works when the hypothetical code is *specific to the security-relevant pattern*.
- NEVER run multi-phrasing on targeted queries ("where is function X", "what calls Y"). It's wasted effort — the natural language query already works. Multi-phrasing is for **broad/audit** queries only.
- The Nix idiom strategy scored **0.07** (2.3x baseline) — highest of any strategy. Always include it for Nix-heavy repos.
- Dual-model overlap was **22%** across 8 query pairs. Running one model misses ~40% of what the other finds. But Jina (MRR 0.638 on Nix) adds noise, not signal — use `voyage` + `voyage-context` (both >0.79 MRR), not Voyage + Jina.

## When to Apply

| Query type | Multi-phrasing? | Why |
|---|---|---|
| "Find all X" / "audit Y" / "inventory Z" | **Yes** | Recall matters more than precision |
| Security audit (credentials, firewall, unsafe) | **Yes** | False negatives are expensive |
| "Where is function X?" | No | Single query is sufficient |
| "What calls Y?" | No | Structural query — use graph |
| "How does X work?" | No | Conceptual — single search + chain |

## Phrasing Strategies by Language

### Nix

| Strategy | Template | Best for | Example |
|---|---|---|---|
| **Idiom** (strongest) | `mkOption { type = types.str; default = ...; }` | Config options, secrets, feature flags | `mkOption type str default secret token oidc_client_secret` |
| **Attribute path** | `networking.firewall.allowedTCPPorts = []; openFirewall = true` | Firewall, network, services | `networking.firewall.allowedTCPPorts networking.firewall.allowedUDPPorts openFirewall = true` |
| **Sops pattern** | `sops.secrets.X = { sopsFile = ./secrets.yaml; }` | Secret management | `sops.secrets.X = { sopsFile = ./secrets.yaml; }; environment.SECRET_VAR = config.sops.secrets.X.path;` |
| **Service pattern** | `systemd.services.NAME = { serviceConfig = { User = ...; }; }` | Service permissions, hardening | `systemd.services.NAME serviceConfig User Group DynamicUser` |

### Rust

| Strategy | Template | Best for | Example |
|---|---|---|---|
| **Function signature** (strongest) | `fn name(params: Types) -> Result<T>` | Device I/O, network, protocol | `fn read_can_frame(socket: &CanSocket) -> Result<CanFrame>` |
| **Unsafe pattern** | `unsafe { libc::ioctl ptr::read_unaligned transmute }` | Security audit for unsafe blocks | `unsafe { std::slice::from_raw_parts ptr::read_unaligned libc::ioctl transmute mem::zeroed }` |
| **Error type** | `#[derive(thiserror::Error)] enum AppError` | Error handling audit | Too generic alone — combine with domain term |
| **Struct + impl** | `pub struct Config { field: Type }` | Configuration, state | `pub struct Credentials { api_key: String, secret: String }` |

### TypeScript

| Strategy | Template | Best for | Example |
|---|---|---|---|
| **Interface/type** | `interface Name { field: Type }` | API contracts, props | `interface AuthConfig { token: string; refreshUrl: string }` |
| **React pattern** | `const Component: React.FC<Props> = ({ ... }) =>` | UI components | Specific to component name + props |

### Cross-Language (credentials/secrets)

| Strategy | Template | When |
|---|---|---|
| **Hypothetical code** | `password = "admin123"; apiKey = "sk-secret-key-hardcoded"; environment.AWS_SECRET_ACCESS_KEY = "AKIA"` | Hardcoded credential sweep |
| **Declaration pattern** | `defvar! mkOption type str default secret token oidc_client_secret environment AWS_SECRET_ACCESS_KEY` | Cross-language config audit |

## Confidence Tiers (for presenting results)

After running multiple phrasings, annotate results by how many passes found them:

| Appeared in | Confidence | Action |
|---|---|---|
| 3+ of 4 phrasings | **High** | Report as finding |
| 2/4 phrasings | **Medium** | Report, note which phrasings agreed |
| 1/4 phrasings (idiom, signature, or self-seed) | **Medium-Low** | Report, flag for manual verification |
| 1/4 phrasings (natural language only) | **Low** | Include but note single-source |

Self-seeded results (phrasing D only) are Medium-Low — they're deeper in the semantic
neighborhood but unconfirmed by independent phrasings.

When dual-model consensus is also active (2 models x 4 phrasings = 8 passes), files
appearing in 5+ passes are high confidence. Files in only 1 pass across both models
warrant investigation — they may be noise or they may be the most valuable find.

## Quantitative Evidence

### Dual-Embedding (voyage-4-large vs voyage-context-3, Nix sub-project)

8 security query pairs, k=5 each:
- **Mean overlap: 22%** (range: 0%–33%)
- **Mean union size: 6.9 files** vs 4.2 per model alone (+57%)
- Zero-overlap case: "debug mode bypass" — completely disjoint result sets

### HyDE Effect by Domain

| Domain | NL quality | HyDE improvement | Score delta |
|---|---|---|---|
| Credentials | Moderate | +3-6 unique files | 0.03 → 0.05-0.07 |
| Firewall/ports | Moderate | +3 targeted results | 0.03 → 0.04 |
| Network config | Weak | **Transformative** — all 5 new results relevant | 0.03 → 0.03 (but relevant) |
| Unsafe code | **Failed** (0 relevant) | **Transformative** — found actual unsafe blocks | 0.03 → 0.03 (but relevant) |
| CAN bus/serial | Weak | **Transformative** — found CanSocket, device registries | 0.03 → 0.04 |
| Error handling | **Failed** | Partial — too-generic pattern | 0.03 → 0.02 |

### Key Finding

HyDE helps most when natural language is weakest. For domains where NL already works (credentials), HyDE adds marginal finds. For domains where NL completely fails (unsafe code, CAN bus), HyDE is the difference between zero and five relevant results.

## HyDE Improvement Principles

1. **Specificity over generality.** `mkOption type str default secret token oidc_client_secret` (scored 0.07) vs `Result<T, Error>` (noise). The hypothetical must be specific to the *security-relevant pattern*, not a generic language construct.

2. **Consume Step 0 output.** If Step 0 discovers the codebase uses `defvar!` macros, the HyDE query should contain `defvar!`. Don't generate generic Rust when the codebase has project-specific idioms.

3. **Self-seeding is mandatory (phrasing D).** After phrasings A/B/C return, examine
   their top results' `name`/`snippet` fields. Extract the codebase's vocabulary for the
   domain and generate a 4th phrasing. Tested 2026-04-11 on 4 queries: +9 unique files
   (20-30% recall gain on top of 3-phrasing pipeline). Examples:
   - `credentials = {` → `credentials = { accessKeyId secretAccessKey sessionToken`
     → found `download_from_s3`, `hitlman-apid/main.rs`
   - `create_raw_image_message` → `from_raw_parts as_ptr &[u8] buffer bytes raw frame`
     → found `encode_zstd_frame_raw`, `compute_checksum`
   - `register_compass_device` → `fn register_device serialport::new TTYPort CanSocket`
     → found `send_pgn_request`, `register_device` (2 different crates)

4. **Always run all phrasings.** Do not skip HyDE based on NL scores. Even when NL scores well (0.05+), HyDE phrasings surface unique files that NL misses. The additional API cost is trivial compared to the recall gain.

5. **Generate 2-3 variations, not one.** Different abstraction levels:
   - Specific instance: `oidc_client_secret = mkOption { type = types.str; default = ""; }`
   - Structural pattern: `mkOption type str default secret token environment`
   - Cross-language: `password = "hardcoded"; apiKey = "sk-secret"`

## Single-Provider Repo Guidance

When `list_projects` shows only one `embedding_provider` for the target path:

- **Dual-model is unavailable** — note this in the response
- **Lean harder on HyDE** — multi-phrasing on a single model provides comparable diversity (40-60% result expansion) to dual-model on a single phrasing
- **For security-critical repos** (high-assurance): recommend reindexing with a second provider via `/index-repo` to enable dual-model permanently
- **For other repos** (mcp-servers, knowledge-base): HyDE multi-phrasing is sufficient; dual-indexing cost isn't justified

**Dual-index is the default (split-backend only).** On split-backend hosts (code-search MCP),
`/index-repo` creates both `voyage` and `voyage-context` indexes for every repo. Use `--single`
to skip the secondary index for repos where the extra indexing time isn't worth it (rare —
incremental updates are cheap after first index). On unified-backend hosts (codebase-memory-mcp),
there is no separate code-search index, no provider pairs, and no `--single` flag — see
index-repo SKILL.md for backend detection.

## Dual-Model Weighting

**Current state (2026-04-11): equal weighting is correct.**

Tested 6 golden-set queries against both models. Neither model consistently dominates
any category. Average overlap: 18% (even lower than the security-query 22%). Per-query
winners are unpredictable — `voyage` wins on some, `voyage-context` on others, most tie.

**Learned per-category weighting requires:**
1. 200+ queries accumulated in `query-routing-log.jsonl` with outcome labels
2. Categories classified (networking, hardware, service, library, secrets)
3. Per-category win rate computed for each model
4. Weighting applied accordingly

The `query-routing-log.py` hook is already capturing the data. The analysis script
doesn't exist yet. Until it does, equal weighting (union + dedup) is the right default.

**Research alignment (EMNLP 2025):** The "Mixture of Retrievers" paper confirms that
per-query routing requires enough logged data to identify statistical patterns. With
small sample sizes, equal weighting outperforms learned routing because the learned
weights overfit to noise.
