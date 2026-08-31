#!/bin/bash
# Check that Rust source files have co-located tests (#[cfg(test)] in same file)
# Source: BurntSushi (every flag in ripgrep has its test immediately below the impl)
# Usage: ./check-colocated-tests.sh <directory>

DIR="${1:-.}"
MISSING=0
CHECKED=0

while IFS= read -r file; do
    # Skip test-only files, build scripts, and main.rs
    basename=$(basename "$file")
    if [[ "$basename" == *"test"* ]] || [[ "$basename" == "build.rs" ]] || [[ "$basename" == "main.rs" ]]; then
        continue
    fi

    CHECKED=$((CHECKED + 1))

    # Check if file contains #[cfg(test)]
    if ! grep -q '#\[cfg(test)\]' "$file"; then
        echo "MISSING: $file has no #[cfg(test)] block"
        MISSING=$((MISSING + 1))
    fi
done < <(find "$DIR" -type f -name "*.rs" -not -path "*/target/*" -not -path "*/.git/*")

echo "Checked $CHECKED files, $MISSING missing co-located tests"
if [ "$MISSING" -gt 0 ]; then
    exit 1
else
    echo "PASS: All source files have co-located tests"
    exit 0
fi
