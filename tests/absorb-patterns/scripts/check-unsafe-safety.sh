#!/bin/bash
# Check for unsafe blocks without // SAFETY: comment in preceding 3 lines
# Source: alex, cyphar (security-first Rust developers)
# Usage: ./check-unsafe-safety.sh <directory>

DIR="${1:-.}"
VIOLATIONS=0

while IFS= read -r file; do
    # Read file into array
    mapfile -t lines < "$file"
    total=${#lines[@]}

    for ((i=0; i<total; i++)); do
        trimmed=$(echo "${lines[$i]}" | sed 's/^[[:space:]]*//')
        if echo "$trimmed" | grep -q "^unsafe {"; then
            # Check preceding 3 lines for SAFETY:
            found=0
            for ((j=i-1; j>=0 && j>=i-3; j--)); do
                if echo "${lines[$j]}" | grep -qi "SAFETY:"; then
                    found=1
                    break
                fi
            done
            if [ "$found" -eq 0 ]; then
                echo "VIOLATION: $file:$((i+1)) — unsafe block without // SAFETY: comment"
                VIOLATIONS=$((VIOLATIONS + 1))
            fi
        fi
    done
done < <(find "$DIR" -name "*.rs" -not -path "*/target/*")

if [ "$VIOLATIONS" -eq 0 ]; then
    echo "PASS: All unsafe blocks have // SAFETY: comments"
fi
exit $((VIOLATIONS > 0 ? 1 : 0))
