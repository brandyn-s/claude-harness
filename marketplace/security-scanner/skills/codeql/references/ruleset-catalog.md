# Ruleset Catalog

## Official CodeQL Suites

| Suite | False Positives | Use Case |
|-------|-----------------|----------|
| `security-extended` | Low | **Default** - Security audits |
| `security-and-quality` | Medium | Comprehensive review |
| `security-experimental` | Higher | Research, vulnerability hunting |

**Usage:** `codeql/<lang>-queries:codeql-suites/<lang>-security-extended.qls`

**Languages:** `cpp`, `csharp`, `go`, `java`, `javascript`, `python`, `ruby`, `rust`, `swift`, `actions`

---

## GitHub Actions Suite

The `actions` language has its own pack and suite that catches CI-specific findings (`unpinned-tag`, `missing-workflow-permissions`, `untrusted-checkout`) which source-language suites do not find.

**Usage:** `codeql/actions-queries:codeql-suites/actions-security-and-quality.qls`

**When to run:** Always, if `.github/workflows/` exists. See SKILL.md Principle 2 and the build-database / run-analysis workflows for how the actions database is built and analyzed alongside the primary language database.

---

## Trail of Bits Packs

| Pack | Language | Focus |
|------|----------|-------|
| `trailofbits/cpp-queries` | C/C++ | Memory safety, integer overflows |
| `trailofbits/go-queries` | Go | Concurrency, error handling |
| `trailofbits/java-queries` | Java | Security, code quality |

**Install:**
```bash
codeql pack download trailofbits/cpp-queries
codeql pack download trailofbits/go-queries
codeql pack download trailofbits/java-queries
```

---

## CodeQL Community Packs

| Pack | Language |
|------|----------|
| `githubsecuritylab/codeql-javascript-queries` | JavaScript/TypeScript |
| `githubsecuritylab/codeql-python-queries` | Python |
| `githubsecuritylab/codeql-go-queries` | Go |
| `githubsecuritylab/codeql-java-queries` | Java |
| `githubsecuritylab/codeql-cpp-queries` | C/C++ |
| `githubsecuritylab/codeql-csharp-queries` | C# |
| `githubsecuritylab/codeql-ruby-queries` | Ruby |

**Install:**
```bash
codeql pack download githubsecuritylab/codeql-<lang>-queries
```

**Source:** [github.com/GitHubSecurityLab/CodeQL-Community-Packs](https://github.com/GitHubSecurityLab/CodeQL-Community-Packs)

---

## Verify Installation

```bash
# List all installed packs
codeql resolve qlpacks

# Check specific packs
codeql resolve qlpacks | grep -E "(trailofbits|GitHubSecurityLab)"
```
