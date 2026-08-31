# CKLB Evidence Verification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a three-layer evidence verification system to the STIG assessment pipeline that catches fabricated file paths, recycled evidence, and cross-finding duplication before CKLBs are published.

**Architecture:** One new Python script (`verify_evidence_paths.py`) in the assessment scripts directory, one new reference file in the stig-assess skill, and updates to the existing `validate-artifacts.md` checklist and stig-assess SKILL.md to wire verification into the pipeline.

**Tech Stack:** Python (json, pathlib, re), existing CKLB/script infrastructure in `example-assessment-repo/stig-assessment/`

**Repo:** `$HOME/Documents/GHES/example-assessment-repo/`

**Key context:**
- CKLBs live at `stig-assessment/checklists/*.cklb` (18 files)
- Enriched CKLBs at `stig-assessment/checklists-enriched/*.cklb`
- Existing scripts at `stig-assessment/scripts/`
- PSM source code at `$HOME/Documents/GHES/example-monorepo/`
- CKLBs are single-line JSON. Structure: `data['stigs'][0]['rules']` -> array with `status`, `finding_details`, `comments`, `rule_title`, `group_id`, `rule_version`
- `verify_cklb_content.py` already checks content quality (topic relevance, boilerplate, copy-paste) but NOT file path existence
- `enrich_cklbs_with_code_evidence.py` appends `[Code Evidence]` citations but does NOT verify cited paths exist

---

### Task 1: Build the file inventory generator

**Files:**
- Create: `stig-assessment/scripts/verify_evidence_paths.py`

**Step 1: Write the failing test**

Create a minimal test that imports the module and calls the inventory builder against the PSM repo:

```python
# stig-assessment/scripts/test_verify_evidence.py
import json
import tempfile
from pathlib import Path
from verify_evidence_paths import build_file_inventory, extract_file_paths

def test_build_inventory():
    """Inventory should contain known PSM files."""
    repo = Path("$HOME/Documents/GHES/example-monorepo")
    if not repo.exists():
        return  # skip if repo not available
    inventory = build_file_inventory(repo)
    # Known files that must be in the inventory
    assert "nix/modules/stig.nix" in inventory
    assert "nix/modules/baf.nix" in inventory
    # Files that should NOT be there
    assert "nonexistent/fake.rs" not in inventory

def test_extract_file_paths():
    """Should extract .nix, .rs, .toml, .json paths from text."""
    text = (
        "The firewall is configured in nix/modules/stig.nix (line 42). "
        "See also apid/src/auth.rs for authentication. "
        "No file reference here."
    )
    paths = extract_file_paths(text)
    assert "nix/modules/stig.nix" in paths
    assert "apid/src/auth.rs" in paths
    assert len(paths) == 2

if __name__ == "__main__":
    test_build_inventory()
    print("PASS: test_build_inventory")
    test_extract_file_paths()
    print("PASS: test_extract_file_paths")
```

**Step 2: Run test to verify it fails**

Run: `python stig-assessment/scripts/test_verify_evidence.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'verify_evidence_paths'`

**Step 3: Write the inventory builder and path extractor**

```python
#!/usr/bin/env python3
"""Verify that file paths cited as evidence in CKLB findings actually exist.

Three verification layers:
  1. File existence - does the cited path exist in the source repo?
  2. Content verification - does the file contain the cited function/config?
  3. Cross-finding dedup - is the same evidence recycled across many findings?

Usage:
    python verify_evidence_paths.py [--repo PATH] [--cklb-dir PATH] [--fix]

With --fix: removes invalid evidence citations from finding_details/comments.
Without --fix: report-only mode (default).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Paths
DEFAULT_REPO = Path(
    "$HOME/Documents/GHES/example-monorepo"
)
DEFAULT_CKLB_DIR = Path(
    "$HOME/Documents/GHES/example-assessment-repo"
    "/stig-assessment/checklists"
)
DEFAULT_ENRICHED_DIR = Path(
    "$HOME/Documents/GHES/example-assessment-repo"
    "/stig-assessment/checklists-enriched"
)

# File extensions that indicate source code paths
CODE_EXTENSIONS = {
    ".nix", ".rs", ".toml", ".json", ".cfg", ".py", ".go",
    ".ts", ".tsx", ".tf", ".sh", ".yml", ".yaml", ".html",
}

# Regex to extract file-path-like references from text
# Matches: word/word/file.ext or word/file.ext (with optional :linenum)
FILE_PATH_RE = re.compile(
    r'(?<!\w)'                          # not preceded by word char
    r'((?:[\w.-]+/)+[\w.-]+\.(?:'       # dir/dir/file.ext
    + '|'.join(ext.lstrip('.') for ext in CODE_EXTENSIONS)
    + r'))(?::(\d+))?'                  # optional :linenum
    r'(?!\w)',                           # not followed by word char
)

def build_file_inventory(repo_path):
    """Build a set of all tracked files in the repo using git ls-files."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return set(
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
            )
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Fallback: walk the filesystem (slower, includes untracked)
    inventory = set()
    for root, _dirs, files in os.walk(repo_path):
        # Skip .git and build dirs
        rel_root = Path(root).relative_to(repo_path)
        if any(
            part.startswith(".")
            or part in ("target", "node_modules", "result", "__pycache__")
            for part in rel_root.parts
        ):
            continue
        for fname in files:
            rel = str((rel_root / fname).as_posix())
            inventory.add(rel)
    return inventory

def extract_file_paths(text):
    """Extract file-path references from finding_details or comments text."""
    paths = set()
    for match in FILE_PATH_RE.finditer(text):
        path = match.group(1)
        # Normalize: strip leading ./ or /
        path = path.lstrip("./")
        paths.add(path)
    return paths

def verify_cklb(cklb_path, inventory, repo_path):
    """Verify all evidence paths in a single CKLB file.

    Returns a list of findings with verification results.
    """
    with open(cklb_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = []
    rules = data["stigs"][0]["rules"]

    for rule in rules:
        status = rule.get("status", "")
        if status in ("not_applicable",):
            continue  # N/A rules rarely have evidence to check

        finding_details = rule.get("finding_details", "") or ""
        comments = rule.get("comments", "") or ""
        combined_text = finding_details + "\n" + comments

        cited_paths = extract_file_paths(combined_text)
        if not cited_paths:
            continue

        for path in cited_paths:
            exists = path in inventory
            # Try common prefix variations
            if not exists:
                for prefix in ("", "nix/", "src/"):
                    if (prefix + path) in inventory:
                        exists = True
                        path = prefix + path
                        break

            entry = {
                "group_id": rule.get("group_id", ""),
                "rule_title": rule.get("rule_title", "")[:80],
                "status": status,
                "cited_path": path,
                "exists": exists,
            }

            # Content verification for existing files
            if exists and ":" in combined_text:
                # Check if any quoted content from the file is real
                # (future enhancement - line-level verification)
                entry["content_verified"] = None  # not yet implemented

            results.append(entry)

    return results

def check_cross_finding_reuse(all_results):
    """Identify evidence paths reused across many findings."""
    path_to_findings = defaultdict(list)
    for r in all_results:
        if r["exists"]:
            path_to_findings[r["cited_path"]].append(r["group_id"])

    reuse_report = {}
    for path, findings in path_to_findings.items():
        if len(findings) > 5:
            reuse_report[path] = {
                "count": len(findings),
                "sample_findings": findings[:10],
            }
    return reuse_report

def fix_cklb(cklb_path, invalid_paths):
    """Remove invalid evidence citations from a CKLB file.

    Only removes lines/sentences containing paths confirmed as non-existent.
    """
    if not invalid_paths:
        return False

    with open(cklb_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    modified = False
    rules = data["stigs"][0]["rules"]

    for rule in rules:
        for field in ("finding_details", "comments"):
            text = rule.get(field, "") or ""
            if not text:
                continue
            original = text
            for path in invalid_paths:
                # Remove lines containing the invalid path
                lines = text.split("\n")
                lines = [
                    line for line in lines
                    if path not in line
                ]
                text = "\n".join(lines).strip()
            if text != original:
                rule[field] = text
                modified = True

    if modified:
        with open(cklb_path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
    return modified

def main():
    parser = argparse.ArgumentParser(
        description="Verify evidence file paths in CKLB findings."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_REPO,
        help="Path to PSM source repo",
    )
    parser.add_argument(
        "--cklb-dir",
        type=Path,
        default=DEFAULT_CKLB_DIR,
        help="Path to CKLB checklists directory",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Remove invalid evidence citations (default: report only)",
    )
    args = parser.parse_args()

    # Layer 1: Build file inventory
    print(f"Building file inventory from {args.repo}...")
    inventory = build_file_inventory(args.repo)
    print(f"  {len(inventory)} files indexed")

    # Layer 2: Verify each CKLB
    all_results = []
    invalid_by_cklb = defaultdict(set)
    cklb_files = sorted(args.cklb_dir.glob("*.cklb"))
    print(f"\nVerifying {len(cklb_files)} CKLB files...")

    for cklb_path in cklb_files:
        results = verify_cklb(cklb_path, inventory, args.repo)
        all_results.extend(results)

        invalid = [r for r in results if not r["exists"]]
        if invalid:
            print(f"\n  {cklb_path.name}:")
            for r in invalid:
                print(
                    f"    INVALID: {r['cited_path']} "
                    f"(in {r['group_id']}: {r['rule_title']})"
                )
                invalid_by_cklb[cklb_path].add(r["cited_path"])

    # Layer 3: Cross-finding reuse
    reuse = check_cross_finding_reuse(all_results)

    # Summary
    total_citations = len(all_results)
    invalid_count = sum(1 for r in all_results if not r["exists"])
    valid_count = total_citations - invalid_count

    print(f"\n{'='*60}")
    print(f"Evidence Path Verification Summary")
    print(f"{'='*60}")
    print(f"Total citations:  {total_citations}")
    print(f"Valid paths:      {valid_count}")
    print(f"Invalid paths:    {invalid_count}")
    if total_citations:
        print(
            f"Accuracy:         "
            f"{valid_count/total_citations*100:.1f}%"
        )

    if reuse:
        print(f"\nHigh-reuse evidence (cited in >5 findings):")
        for path, info in sorted(
            reuse.items(), key=lambda x: x[1]["count"], reverse=True
        ):
            print(f"  {path}: {info['count']} findings")

    # Fix mode
    if args.fix and invalid_by_cklb:
        print(f"\nFixing {len(invalid_by_cklb)} CKLB files...")
        for cklb_path, paths in invalid_by_cklb.items():
            if fix_cklb(cklb_path, paths):
                print(f"  Fixed: {cklb_path.name}")
    elif invalid_count > 0:
        print(f"\nRun with --fix to remove invalid citations.")

    sys.exit(1 if invalid_count > 0 else 0)

if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `cd $HOME/Documents/GHES/example-assessment-repo/stig-assessment/scripts && python test_verify_evidence.py`
Expected: Both tests PASS

**Step 5: Run the verifier against real CKLBs (report-only)**

Run: `python verify_evidence_paths.py`
Expected: Report showing total citations, valid/invalid counts, any high-reuse paths. Exit code 1 if invalid paths found, 0 if clean.

**Step 6: Run against enriched CKLBs too**

Run: `python verify_evidence_paths.py --cklb-dir ../checklists-enriched`
Expected: Same report format. Enriched CKLBs may have more citations from the enrichment script.

**Step 7: Commit**

```bash
git add scripts/verify_evidence_paths.py scripts/test_verify_evidence.py
git commit -m "feat: add evidence path verification for CKLB findings"
```

---

### Task 2: Add file inventory to stig-assess skill pre-assessment phase

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export)
- Create: `~/.claude/a separate skill (not included in this export)

**Step 1: Create the evidence verification reference**

```markdown
# Evidence Verification Protocol

Run after EVERY assessment update, BEFORE publishing CKLBs or generating XLSX/gap reports.

## Why This Exists

AI assessment agents fabricate file paths that follow the codebase's naming conventions.
`apid/auth.rs`, `hitlman-apid.nix`, `micronav/configuration.nix` sound real but may not exist.
Agents also recycle one real file as evidence across many unrelated findings.

## Verification Steps

### Step 1: Run the evidence path verifier

```
cd $HOME/Documents/GHES/example-assessment-repo/stig-assessment/scripts
python verify_evidence_paths.py
```

If invalid paths are found, run with `--fix` to remove them:

```
python verify_evidence_paths.py --fix
```

### Step 2: Review high-reuse evidence

The verifier flags any file path cited in more than 5 findings. For each:
- Is this a genuinely cross-cutting file (e.g., `nix/modules/stig.nix` for all NixOS STIG findings)? -> OK
- Is this a narrow file being recycled as generic evidence? -> Fix by replacing with finding-specific evidence

### Step 3: Spot-check content accuracy

For the top 5 most-cited files, verify one finding manually:
1. Read the cited file
2. Read the finding_details that cites it
3. Confirm the file actually contains the claimed content

This catches the case where a file exists but doesn't prove what the finding claims.

## When to Run

- After any assessment agent pass (initial, reassessment, V&V, enrichment)
- After `enrich_cklbs_with_code_evidence.py`
- Before `generate_xlsx.py` and `compile_gap_report.py`
- Before any CKLB is shared with assessors or uploaded to eMASS
```

**Step 2: Update stig-assess SKILL.md**

Add to Step 2 (Full Re-Assessment), between step 5 (aggressive NR reduction) and step 6 (regenerate XLSX):

```
5b. Verify evidence paths: `python stig-assessment/scripts/verify_evidence_paths.py`
    - If invalid paths found, fix with `--fix` flag, then re-run to confirm clean
    - See `references/evidence-verification.md` for the full protocol
```

Add to Step 5 (Generate and Validate Deliverables), between step 3 (update narrative) and step 4 (validate artifact consistency):

```
3b. Verify evidence paths: run `references/evidence-verification.md` protocol
```

**Step 3: Update validate-artifacts.md**

Add a new Step 2b between Step 2 (Cross-Check Against Baseline) and Step 3 (Cross-Check XLSX):

```markdown
## Step 2b: Verify Evidence Paths

Run the evidence path verifier:

```
cd stig-assessment/scripts
python verify_evidence_paths.py
```

Expected: Exit code 0 (no invalid paths). If exit code 1:
- Review the INVALID paths listed in the output
- Run `python verify_evidence_paths.py --fix` to remove fabricated evidence
- Re-run to confirm clean
- Re-assess any findings that lost their evidence (they may need legitimate evidence added)
```

**Step 4: Commit**

```bash
git add ~/.claude/a separate skill (not included in this export)
git add ~/.claude/a separate skill (not included in this export)
git add ~/.claude/a separate skill (not included in this export)
git commit -m "feat: wire evidence verification into stig-assess pipeline"
```

---

### Task 3: Add pre-assessment file inventory to agent prompts

**Files:**
- Modify: `stig-assessment/scripts/enrich_cklbs_with_code_evidence.py` (add inventory pre-check)

**Step 1: Add inventory validation to the enrichment script**

At the top of the `main()` function in `enrich_cklbs_with_code_evidence.py`, add a pre-flight check that builds the file inventory and validates all evidence files exist before appending citations:

```python
# At the start of main(), after loading evidence files:
from verify_evidence_paths import build_file_inventory, extract_file_paths

repo = Path("$HOME/Documents/GHES/example-monorepo")
inventory = build_file_inventory(repo)
print(f"File inventory: {len(inventory)} files")

# When appending a citation, verify the file exists first:
# In the citation loop, add:
cited_paths = extract_file_paths(citation_text)
invalid = [p for p in cited_paths if p not in inventory]
if invalid:
    print(f"  SKIP: {rule['group_id']} - invalid path(s): {invalid}")
    continue
```

This prevents the enrichment script from introducing new fabricated paths.

**Step 2: Run enrichment on a test CKLB to verify**

Run: `python enrich_cklbs_with_code_evidence.py`
Expected: Any citations with invalid paths are skipped with a warning instead of appended.

**Step 3: Commit**

```bash
git add scripts/enrich_cklbs_with_code_evidence.py
git commit -m "feat: pre-validate evidence paths in enrichment script"
```

---

## Verification Checklist

After all tasks:

- [ ] `verify_evidence_paths.py` runs against real CKLBs and produces a report
- [ ] `verify_evidence_paths.py --fix` removes invalid paths without corrupting CKLB JSON
- [ ] `enrich_cklbs_with_code_evidence.py` skips invalid-path citations
- [ ] `stig-assess` SKILL.md references evidence verification in the pipeline
- [ ] `validate-artifacts.md` includes evidence verification step
- [ ] `references/evidence-verification.md` documents the full protocol
- [ ] Running the full pipeline (assess -> verify -> fix -> generate) produces clean CKLBs
