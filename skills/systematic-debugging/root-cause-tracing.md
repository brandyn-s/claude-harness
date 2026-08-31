# Root Cause Tracing

Trace bugs backward through the call chain to find the original trigger.

## Core Principle

Bugs manifest deep in the call stack (wrong directory, wrong path, wrong config value).
Your instinct is to fix where the error appears. That's treating a symptom.

**Trace backward through the call chain until you find the original trigger, then fix at the source.**

## When to Use

- Error happens deep in execution (not at entry point)
- Stack trace shows long call chain
- Unclear where invalid data originated
- Need to find which test/code triggers the problem

## The Tracing Process

### 1. Observe the Symptom

```
Error: connection failed on 127.0.0.1:6379 with ssl=False
```

### 2. Find Immediate Cause

**What code directly causes this?**

```python
redis.Redis(host=host, port=port, ssl=ssl_enabled)
```

### 3. Ask: What Called This?

```python
create_redis_client(config)
  → called by MCPServer.setup()
  → called by main()
  → called with config from environment
```

### 4. Keep Tracing Up

**What value was passed?**

- `ssl_enabled = False` (should be True for ElastiCache!)
- Environment variable `REDIS_SSL` was never set
- Config defaults to `False` when missing

### 5. Find Original Trigger

**Where did the wrong value originate?**

```python
ssl_enabled = os.getenv("REDIS_SSL", "false").lower() == "true"
# Env var not in .env.example or ECS task definition
```

**Root cause:** Missing environment variable, not a connection bug.

## Adding Instrumentation

When you can't trace manually, add diagnostic logging:

```python
# Before the problematic operation
import sys, traceback
print(f"DEBUG redis connect: host={host}, port={port}, ssl={ssl_enabled}", 
      file=sys.stderr)
print(f"DEBUG call stack:\n{''.join(traceback.format_stack())}", 
      file=sys.stderr)
```

**Critical:**
- Use `stderr` in tests/scripts (stdout may be captured or suppressed)
- Log BEFORE the dangerous operation, not after it fails
- Include: the value, the source of the value, environment context, call stack
- `traceback.format_stack()` (Python) or `new Error().stack` (JS) shows the complete call chain

## Test Pollution Bisection

If something appears during tests but you don't know which test:

```bash
#!/usr/bin/env bash
# find-polluter.sh — bisect which test creates side effects
# Usage: ./find-polluter.sh <artifact-to-detect> <test-pattern>
# Example: ./find-polluter.sh '.git' 'tests/test_*.py'

if [ $# -lt 2 ]; then
  echo "error: missing arguments" >&2
  echo "Usage: ./find-polluter.sh <artifact-to-detect> <test-pattern>" >&2
  exit 2
fi

artifact="$1"
pattern="$2"

tested=0
for test_file in $pattern; do
  # Unmatched glob passes through as a literal string — skip it
  [ -e "$test_file" ] || continue
  tested=$((tested + 1))

  # Clean before each
  rm -rf "$artifact" 2>/dev/null
  
  # Run single test
  pytest "$test_file" -x -q 2>/dev/null
  
  # Check for pollution
  if [ -e "$artifact" ]; then
    echo "POLLUTER FOUND: $test_file"
    exit 0
  fi
done

if [ "$tested" -eq 0 ]; then
  echo "error: no test files matched pattern: $pattern" >&2
  echo "hint: quote the glob and check the path (e.g. 'tests/test_*.py')" >&2
  exit 2
fi

echo "No single-test polluter found (may require test interaction)"
```

## Multi-Layer Defense

After finding the root cause, add validation at multiple layers — not just one:

| Layer | Purpose | Example |
|-------|---------|---------|
| **Input validation** | Reject bad values early | `if not directory: raise ValueError("directory required")` |
| **Boundary check** | Validate at component boundaries | `assert ssl_enabled is True, "ElastiCache requires TLS"` |
| **Environment guard** | Prevent dangerous operations in wrong context | `if env != "test": refuse_destructive_operation()` |
| **Instrumentation** | Log before dangerous operations for future debugging | `logger.debug(f"connecting to {host}:{port} ssl={ssl}")` |

One validation layer is a fix. Multiple layers are defense in depth.

## Key Principle

```
Found immediate cause
  → Can trace one level up? → Trace backwards
    → Is this the source? → No → Keep tracing
    → Is this the source? → Yes → Fix at source
  → Can't trace? → Add instrumentation, re-run
```

**NEVER fix just where the error appears.** Trace back to find the original trigger.

## Tips

- **Before operation:** Log before the dangerous operation, not after it fails
- **Include context:** Directory, CWD, environment variables, config source
- **For infrastructure bugs:** Write a boto3/CLI diagnostic script (10s to run) instead of hypothesizing
- **For test pollution:** Bisect to the polluting test before investigating the mechanism

(Pattern source: microsoft/fluidframework `root-cause-tracing` — Context7 registry 2026-04-16)
