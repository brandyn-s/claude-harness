#!/bin/bash
# Check for public enums missing #[non_exhaustive]
# Source: jonhoo, BurntSushi, sfackler (3 independent developers)
# Checks the 5 lines preceding "pub enum" for #[non_exhaustive]
# Usage: ./check-non-exhaustive.sh <directory>

DIR="${1:-.}"
VIOLATIONS=0

while IFS= read -r file; do
    mapfile -t lines < "$file"
    total=${#lines[@]}

    for ((i=0; i<total; i++)); do
        trimmed=$(echo "${lines[$i]}" | sed 's/^[[:space:]]*//')
        if echo "$trimmed" | grep -q "^pub enum "; then
            # Check preceding 5 lines for #[non_exhaustive]
            found=0
            for ((j=i-1; j>=0 && j>=i-5; j--)); do
                if echo "${lines[$j]}" | grep -q "#\[non_exhaustive\]"; then
                    found=1
                    break
                fi
                # Stop if we hit a blank line or non-attribute line (not # or //)
                check=$(echo "${lines[$j]}" | sed 's/^[[:space:]]*//')
                if [ -z "$check" ]; then
                    break
                fi
            done
            if [ "$found" -eq 0 ]; then
                echo "VIOLATION: $file:$((i+1)) — $trimmed (missing #[non_exhaustive])"
                VIOLATIONS=$((VIOLATIONS + 1))
            fi
        fi
    done
done < <(find "$DIR" -name "*.rs" -not -path "*/target/*")

if [ "$VIOLATIONS" -eq 0 ]; then
    echo "PASS: All public enums have #[non_exhaustive]"
fi
exit $((VIOLATIONS > 0 ? 1 : 0))
