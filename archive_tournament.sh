#!/bin/bash
# archive_tournament.sh - Mirror TNNT website for archiving
# Usage: ./archive_tournament.sh [year]

set -e

YEAR="${1:-$(date +%Y)}"
SITE_URL="https://tnnt.org"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/tnnt/static/archives/${YEAR}"
TEMP_DIR="${SCRIPT_DIR}/archive_temp_${YEAR}"

echo "=== TNNT Archive Script ==="
echo "Year: ${YEAR}"
echo "Source: ${SITE_URL}"
echo "Output: ${OUTPUT_DIR}"
echo ""

# Check if output directory already exists
if [ -d "${OUTPUT_DIR}" ]; then
    echo "WARNING: Output directory already exists: ${OUTPUT_DIR}"
    read -p "Overwrite? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 1
    fi
    rm -rf "${OUTPUT_DIR}"
fi

# Create temp directory for wget output
mkdir -p "${TEMP_DIR}"
cd "${TEMP_DIR}"

echo "Starting wget mirror..."
echo ""

# Mirror the site with wget
# --mirror: recursive, timestamping, infinite depth, keep FTP listings
# --convert-links: convert links to relative
# --adjust-extension: add .html extension to text/html files
# --page-requisites: get CSS, JS, images
# --no-parent: don't ascend to parent directory
# --reject-regex: exclude patterns
wget \
    --mirror \
    --convert-links \
    --adjust-extension \
    --page-requisites \
    --no-parent \
    --reject-regex="(admin-panel|api/|logins-disabled|/archives/)" \
    --execute robots=off \
    --wait=0.5 \
    --random-wait \
    --user-agent="TNNT-Archiver/1.0" \
    "${SITE_URL}/"

echo ""
echo "Mirror complete. Moving files to output directory..."

# Move the mirrored files to output directory
# wget creates a directory structure like temp_dir/tnnt.org/...
if [ -d "${TEMP_DIR}/tnnt.org" ]; then
    mkdir -p "${OUTPUT_DIR}"
    mv "${TEMP_DIR}/tnnt.org"/* "${OUTPUT_DIR}/"
else
    echo "ERROR: Expected directory ${TEMP_DIR}/tnnt.org not found"
    exit 1
fi

# Cleanup temp directory
cd "${SCRIPT_DIR}"
rm -rf "${TEMP_DIR}"

echo ""
echo "=== Archive Complete ==="
echo "Files saved to: ${OUTPUT_DIR}"
echo ""
echo "Next step: Run cleanup script"
echo "  python cleanup_archive.py ${YEAR}"
