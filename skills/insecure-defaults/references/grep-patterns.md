# Grep Patterns Library

Pre-written grep patterns per insecure-default category. Use these as
starting points; tailor based on the target codebase's idioms (Phase 1
framework-first discovery).

> **Heuristic:** language-specific declaration idioms (`os.getenv`,
> `mkOption`, `defvar!`, `env::var`) catch more instances than value
> patterns alone. Always run framework-first discovery before the value
> greps below.

## 1. Fallback Secrets / Default Credentials

Code path: `getenv()` returns None, falls back to a hardcoded value.

```bash
# Python
grep -rn "os\.getenv\(['\"][^'\"]*['\"], *['\"][^'\"]\{6,\}" --include="*.py"
grep -rn "os\.environ\.get\(['\"][^'\"]*['\"], *['\"][^'\"]\{6,\}" --include="*.py"
grep -rn "ENV\.fetch\(.*default:" --include="*.rb"

# Node / TypeScript
grep -rn "process\.env\.[A-Z_]\+ *|| *['\"][^'\"]\{6,\}" --include="*.ts" --include="*.js"
grep -rn "process\.env\[['\"][A-Z_]\+['\"]\] *\?\? *['\"]" --include="*.ts" --include="*.js"

# Rust
grep -rn "env::var(.*)\.unwrap_or(['\"][^'\"]\{6,\}" --include="*.rs"
grep -rn "env::var(.*)\.unwrap_or_else.*['\"][^'\"]\{6,\}" --include="*.rs"

# Go
grep -rn "os\.Getenv(['\"][A-Z_]\+['\"])" --include="*.go" -A1 | grep -B1 "if.*== \"\""

# Generic value patterns (all languages)
grep -rEn "(password|passwd|pwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*['\"][^'\"]{8,}" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.java" --include="*.kt"
```

## 2. Hardcoded Credentials in Config Files

```bash
# YAML / JSON / TOML
grep -rEn "(password|secret|api[_-]?key|token|client[_-]?secret)[[:space:]]*[:=].*['\"][A-Za-z0-9+/=_-]{16,}['\"]" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.toml" --include="*.ini" --include="*.env"

# Embedded PEM keys (private)
grep -rn "BEGIN .* PRIVATE KEY" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.toml" --include="*.sh" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go"

# Base64 tokens (heuristic — high false-positive rate)
grep -rEn "['\"][A-Za-z0-9+/]{40,}={0,2}['\"]" --include="*.yaml" --include="*.yml" --include="*.json" | grep -iE "(token|secret|key|password)"

# .env files committed
find . -name ".env" -not -path "*/node_modules/*" -not -path "*/.git/*"
find . -name ".env.production" -not -path "*/node_modules/*"
```

## 3. Fail-Open Security Flags

Auth-disable defaults, debug-mode-on-by-default.

```bash
# Boolean fail-open env defaults
grep -rEn "(AUTH|AUTHZ|AUTHN|VERIFY|TLS|SSL|REQUIRE_AUTH)[A-Z_]*[[:space:]]*[:=][[:space:]]*(false|0|['\"]false['\"]|['\"]0['\"]|['\"]disabled['\"])" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.yaml" --include="*.yml" --include="*.env"

# Debug / verbose enabled by default
grep -rEn "(DEBUG|VERBOSE|DEV[_-]?MODE|TRACE)[[:space:]]*[:=][[:space:]]*(true|1|['\"]true['\"])" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.yaml" --include="*.yml" --include="*.env"

# Default-true on permission flags
grep -rEn "(allow_all|skip_auth|disable_(auth|tls|verify)|insecure_skip_verify)[[:space:]]*[:=][[:space:]]*true" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.yaml" --include="*.yml"

# Python framework specifics
grep -rn "DEBUG = True" --include="*.py"           # Django
grep -rn "app\.debug *= *True" --include="*.py"    # Flask
grep -rn "ALLOWED_HOSTS = \[\]" --include="*.py"   # Django: empty list = no validation in DEBUG
```

## 4. Weak Cryptography

Hashing functions and ciphers known broken for security contexts.

```bash
# Broken hash functions (in security contexts — manually verify each hit)
grep -rEn "(hashlib\.md5|hashlib\.sha1|MessageDigest\.getInstance\(['\"]MD5['\"]|['\"](MD5|SHA-?1)['\"])" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.java" --include="*.kt"

# Broken ciphers
grep -rEn "(DES|3DES|TripleDES|RC4|Blowfish|ECB)[^a-zA-Z]" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.java" --include="*.kt"

# Insecure random
grep -rEn "Math\.random\(\)" --include="*.js" --include="*.ts"           # never use for security
grep -rEn "random\.random\(\)|random\.randint" --include="*.py"   # never for tokens
grep -rEn "rand\(\)|srand\(" --include="*.c" --include="*.cpp" --include="*.h"

# JWT "alg": "none"
grep -rEn "['\"]alg['\"][[:space:]]*:[[:space:]]*['\"]none['\"]" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.java" --include="*.kt" --include="*.json" --include="*.yaml" --include="*.yml"
```

## 5. Permissive Access Controls

CORS wildcards, world-writable files, overly broad IAM.

```bash
# CORS wildcard
grep -rEn "(Access-Control-Allow-Origin|cors_origins?|allowed_origins?)[[:space:]]*[:=].*['\"]\\*['\"]" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.yaml" --include="*.yml" --include="*.json"
grep -rn "allow_origins=\[['\"]\\*['\"]\]" --include="*.py"  # FastAPI / Starlette

# File / dir permissions
grep -rEn "(chmod|os\.chmod|fs\.chmod|umask)\([^)]*0?7{2,3}[^)]*\)" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.java"
grep -rEn "(0o777|0o666|0777|0666)" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb"

# IAM wildcards (Terraform / CloudFormation)
grep -rEn "['\"]Action['\"][[:space:]]*:[[:space:]]*['\"]\\*['\"]" --include="*.json" --include="*.tf" --include="*.yaml" --include="*.yml"
grep -rEn "['\"]Resource['\"][[:space:]]*:[[:space:]]*['\"]\\*['\"]" --include="*.json" --include="*.tf" --include="*.yaml" --include="*.yml"

# S3 / GCS bucket public
grep -rEn "(public-read|public-read-write|allUsers|allAuthenticatedUsers)" --include="*.tf" --include="*.yaml" --include="*.yml" --include="*.json"
```

## 6. TLS / Certificate Verification Disabled

```bash
# Python requests
grep -rEn "verify *= *False" --include="*.py"
grep -rEn "ssl\._create_unverified_context\(\)" --include="*.py"

# Node
grep -rEn "rejectUnauthorized *: *false" --include="*.js" --include="*.ts"
grep -rEn "NODE_TLS_REJECT_UNAUTHORIZED *= *['\"]?0" --include="*.js" --include="*.ts" --include="*.env" --include="*.sh"

# Go
grep -rEn "InsecureSkipVerify: *true" --include="*.go"

# curl / wget flags
grep -rEn "curl[[:space:]].*(-k|--insecure)" --include="*.sh" --include="*.bash" --include="*.zsh" --include="*.Dockerfile" --include="*.yaml" --include="*.yml"
grep -rEn "wget[[:space:]].*--no-check-certificate" --include="*.sh" --include="*.bash" --include="*.zsh" --include="*.Dockerfile" --include="*.yaml" --include="*.yml"
```

## 7. SQL Injection-prone Patterns

String-concatenation SQL, format-string SQL.

```bash
# Python f-string SQL
grep -rEn "(cursor|conn|db)\.execute\(f['\"]" --include="*.py"
grep -rEn "['\"]SELECT.*%s.*['\"][[:space:]]*%" --include="*.py"  # %-formatting

# Node template-literal SQL
grep -rEn "\.query\(\`.*\\\$\{" --include="*.js" --include="*.ts"

# Go string concat
grep -rEn "(db\.Query|db\.Exec)\(['\"].*['\"][[:space:]]*\+" --include="*.go"

# Generic raw SQL
grep -rEn "(SELECT|INSERT|UPDATE|DELETE).*FROM.*['\"][[:space:]]*\+[[:space:]]*[a-zA-Z_]" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb" --include="*.java" --include="*.kt"
```

## 8. Command Injection

Shell invocation with unvalidated input.

```bash
# Python shell=True
grep -rEn "subprocess\.(run|call|Popen|check_output)\([^)]*shell *= *True" --include="*.py"
grep -rEn "os\.system\(" --include="*.py"

# Node child_process exec (vs execFile)
grep -rEn "child_process\.exec\(" --include="*.js" --include="*.ts"
grep -rEn "require\(['\"]child_process['\"]\)\.exec\(" --include="*.js" --include="*.ts"

# Go exec.Command with constructed args
grep -rEn "exec\.Command\(['\"]sh['\"], *['\"]-c['\"]" --include="*.go"

# Ruby
grep -rEn "(system|exec|\`).*#\{" --include="*.rb"
```

## 9. Deserialization

Untrusted-input deserialization.

```bash
# Python
grep -rEn "(pickle\.loads?|cPickle\.loads?|marshal\.loads?|yaml\.load[^_])" --include="*.py"
# Java
grep -rEn "(ObjectInputStream|readObject\(\)|XStream)" --include="*.java" --include="*.kt"
# .NET
grep -rEn "(BinaryFormatter|NetDataContractSerializer|XmlSerializer)" --include="*.cs"
# Node
grep -rEn "node-serialize|serialize-javascript" --include="*.js" --include="*.ts" --include="*.json"
```

## 10. Path Traversal

```bash
# Path joins with user input
grep -rEn "(path\.join|os\.path\.join|filepath\.Join)\([^)]*request\." --include="*.py" --include="*.js" --include="*.ts" --include="*.go"
# File reads accepting raw user paths
grep -rEn "open\(.*req(uest)?\.(params|args|body|query)" --include="*.py"
# Static file servers with insecure config
grep -rEn "send_file\([^,)]*\)" --include="*.py"  # Flask: needs basedir lock
```

## 11. Open Redirect

```bash
# Redirect with unvalidated input
grep -rEn "(redirect|res\.redirect|return.*Redirect)\([^)]*req(uest)?\.(params|args|body|query)" --include="*.py" --include="*.js" --include="*.ts" --include="*.go" --include="*.rb"
```

## 12. Secrets in Logs / Errors

```bash
# Print/log statements with secret-named variables
grep -rEn "(print|console\.log|logger?\.(info|debug|warn|error|trace))\([^)]*(password|secret|api[_-]?key|token)" --include="*.py" --include="*.js" --include="*.ts" --include="*.rs" --include="*.go" --include="*.rb"

# Verbose error responses (Flask/Django/Express defaults)
grep -rn "app\.config\['PROPAGATE_EXCEPTIONS'\] = True" --include="*.py"
grep -rn "DEBUG = True" --include="*.py"
grep -rEn "express\(\)\.use\(errorHandler" --include="*.js" --include="*.ts"
```

---

## Heuristics for Cutting False Positives

1. **Strip test fixtures first**: prefix every grep with a `--exclude-dir` for
   `tests/`, `test/`, `__tests__/`, `examples/`, `fixtures/`, `node_modules/`,
   `vendor/`, `.git/`.
2. **Cross-check with `code-explore` semantic search**: a value pattern hit in
   a comment or string-literal-only file is often a false positive. Tracing
   the data-flow path (Phase 2 VERIFY) filters these.
3. **Framework idiom > value pattern**: language declaration idioms (Step 1
   Framework-First Discovery in SKILL.md) catch instances generic patterns
   miss, especially in Rust (`defvar!` macros) and Nix (`mkOption`).
4. **Production-reachable only**: tag every hit with whether it's import-time
   code (production-reachable) or test/CI/example code (not production). The
   default verdict for non-production hits is SKIP unless explicitly cited
   by production code.
