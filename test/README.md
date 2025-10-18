# NoPanel Test Scripts

This folder contains test scripts for validating noPanel commands.

## Available Tests

### test_export_import.sh
Tests the export and import command structure and functionality.

**Run:**
```bash
./test/test_export_import.sh
```

**What it tests:**
- Export/import command files exist and are executable
- Function naming conventions
- Help functionality
- Sub-functions (users, domains, databases)
- Selective export/import options
- Dry-run functionality
- Skip-existing functionality
- JSON validation
- Password security (removal from exports)
- Documentation exists

### test_validation.sh
Tests input validation for usernames, domains, databases, emails, and passwords.

**Run:**
```bash
./test/test_validation.sh
```

**What it tests:**
- Username validation (format, length, reserved names)
- Domain name validation (RFC compliance, TLD requirements)
- Database name validation (MySQL/MariaDB rules)
- Database user validation (format and reserved names)
- Email address validation (RFC 5322 format)
- Password validation (length and complexity)
- Domain aliases validation (comma-separated domains)

**Coverage:**
- 74 test cases across all validation functions
- Valid and invalid input scenarios
- Edge cases and boundary conditions
- Reserved name detection

### test_migrate.sh
Tests the user migrate command structure (legacy/deprecated).

**Run:**
```bash
./test/test_migrate.sh
```

## Running All Tests

```bash
# From project root
for test in test/test_*.sh; do
    echo "Running $test..."
    $test || exit 1
done
```

Or run individually:

```bash
cd /home/ecarrea/git/nopanel
./test/test_export_import.sh
./test/test_validation.sh
```

## Test Requirements

These tests are **structural tests** that validate:
- File existence and permissions
- Function naming conventions
- Required features are present
- Documentation is available

They do **not** require:
- A running noPanel installation
- Root privileges
- Test data

## Adding New Tests

When creating new test scripts:

1. Make them executable: `chmod +x test/your_test.sh`
2. Start with shebang: `#!/bin/bash`
3. Change to project root: `cd "$(dirname "$0")/.." || exit 1`
4. Use relative paths from project root
5. Exit with code 1 on failure, 0 on success
6. Provide clear output with ✓ and ✗ markers

Example:
```bash
#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

if [[ -f "src/lib/cli/mycommand" ]]; then
    echo "✓ Command exists"
else
    echo "✗ Command missing"
    exit 1
fi
```

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run structural tests
  run: |
    for test in test/*.sh; do
      $test || exit 1
    done
```
