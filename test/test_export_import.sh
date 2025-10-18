#!/bin/bash
# Test script for noPanel export/import commands

# Change to project root directory
cd "$(dirname "$0")/.." || exit 1

echo "Testing noPanel export/import command structure..."
echo ""

# Test if the export command file exists and is executable
EXPORT_FILE="src/lib/cli/export"
if [[ -f "$EXPORT_FILE" && -x "$EXPORT_FILE" ]]; then
    echo "✓ Export command file exists and is executable"
else
    echo "✗ Export command file is missing or not executable"
    exit 1
fi

# Test if the import command file exists and is executable
IMPORT_FILE="src/lib/cli/import"
if [[ -f "$IMPORT_FILE" && -x "$IMPORT_FILE" ]]; then
    echo "✓ Import command file exists and is executable"
else
    echo "✗ Import command file is missing or not executable"
    exit 1
fi

# Test function name conventions
if grep -q "nopanel_export()" "$EXPORT_FILE"; then
    echo "✓ Export function follows naming convention"
else
    echo "✗ Export function name does not follow convention"
    exit 1
fi

if grep -q "nopanel_import()" "$IMPORT_FILE"; then
    echo "✓ Import function follows naming convention"
else
    echo "✗ Import function name does not follow convention"
    exit 1
fi

# Test help functionality
if grep -q "param_help" "$EXPORT_FILE"; then
    echo "✓ Export has help functionality"
else
    echo "✗ Export help is missing"
    exit 1
fi

if grep -q "param_help" "$IMPORT_FILE"; then
    echo "✓ Import has help functionality"
else
    echo "✗ Import help is missing"
    exit 1
fi

# Test export functions exist
if grep -q "nopanel_export_users()" "$EXPORT_FILE" && \
grep -q "nopanel_export_domains()" "$EXPORT_FILE" && \
grep -q "nopanel_export_databases()" "$EXPORT_FILE"; then
    echo "✓ Export sub-functions are implemented (users, domains, databases)"
else
    echo "✗ Export sub-functions are missing"
    exit 1
fi

# Test import functions exist
if grep -q "nopanel_import_users()" "$IMPORT_FILE" && \
grep -q "nopanel_import_domains()" "$IMPORT_FILE" && \
grep -q "nopanel_import_databases()" "$IMPORT_FILE"; then
    echo "✓ Import sub-functions are implemented (users, domains, databases)"
else
    echo "✗ Import sub-functions are missing"
    exit 1
fi

# Test selective export/import options
if grep -q "param_users\|param_domains\|param_databases" "$EXPORT_FILE"; then
    echo "✓ Export has selective export options"
else
    echo "✗ Export selective options are missing"
    exit 1
fi

if grep -q "param_users\|param_domains\|param_databases" "$IMPORT_FILE"; then
    echo "✓ Import has selective import options"
else
    echo "✗ Import selective options are missing"
    exit 1
fi

# Test dry-run functionality in import
if grep -q "param_dry_run" "$IMPORT_FILE"; then
    echo "✓ Import has dry-run functionality"
else
    echo "✗ Import dry-run functionality is missing"
    exit 1
fi

# Test skip-existing functionality in import
if grep -q "param_skip_existing" "$IMPORT_FILE"; then
    echo "✓ Import has skip-existing functionality"
else
    echo "✗ Import skip-existing functionality is missing"
    exit 1
fi

# Test JSON validation in import
if grep -q "jq empty" "$IMPORT_FILE"; then
    echo "✓ Import has JSON validation"
else
    echo "✗ Import JSON validation is missing"
    exit 1
fi

# Test password removal in export (security)
if grep -q "del(.password)" "$EXPORT_FILE"; then
    echo "✓ Export removes passwords for security"
else
    echo "✗ Export does not remove passwords (security issue)"
    exit 1
fi

# Test documentation exists
if [[ -f "docs/export-import.md" ]]; then
    echo "✓ Documentation file exists (docs/export-import.md)"
else
    echo "✗ Documentation file is missing"
    exit 1
fi

echo ""
echo "All structural tests passed!"
echo ""
echo "Export/Import commands are properly integrated."
echo ""
echo "To test actual functionality, you would need:"
echo "1. A fully configured noPanel installation"
echo "2. Test users, domains, and databases"
echo "3. Run: nopanel export --output=test.json"
echo "4. Verify JSON structure: jq . test.json"
echo "5. Test import: nopanel import --file=test.json --dry-run"
