#!/bin/bash
# Check for files exceeding 2000 lines (module size constraint)
# Source: dtolnay (one crate, one concept, under 2K lines)
# Usage: ./check-module-size.sh <directory> [threshold]

DIR="${1:-.}"
THRESHOLD="${2:-2000}"
EXIT_CODE=0

while IFS= read -r file; do
    lines=$(wc -l < "$file")
    if [ "$lines" -gt "$THRESHOLD" ]; then
        echo "VIOLATION: $file ($lines lines > $THRESHOLD threshold)"
        EXIT_CODE=1
    fi
done < <(find "$DIR" -type f \( -name "*.rs" -o -name "*.py" -o -name "*.ts" -o -name "*.md" \) \
    -not -path "*/node_modules/*" -not -path "*/target/*" -not -path "*/.git/*")

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "PASS: All files under $THRESHOLD lines"
fi
exit $EXIT_CODE
