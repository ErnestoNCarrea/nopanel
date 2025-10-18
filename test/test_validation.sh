#!/bin/bash
# Test validation functions

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source required files
source "$PROJECT_ROOT/src/lib/main.inc"
source "$PROJECT_ROOT/src/lib/validation.inc"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Test function
test_validation() {
    local test_name="$1"
    local validation_func="$2"
    local test_value="$3"
    local expected_result="$4"  # 0 for success, 1 for failure
    
    ((TOTAL_TESTS++))
    
    # Suppress output from validation functions
    if $validation_func "$test_value" >/dev/null 2>&1; then
        actual_result=0
    else
        actual_result=1
    fi
    
    if [[ $actual_result -eq $expected_result ]]; then
        echo -e "${GREEN}✓${NC} $test_name: '$test_value'"
        ((PASSED_TESTS++))
    else
        echo -e "${RED}✗${NC} $test_name: '$test_value' (expected $expected_result, got $actual_result)"
        ((FAILED_TESTS++))
    fi
}

echo "========================================"
echo "Testing Username Validation"
echo "========================================"

# Valid usernames
test_validation "Valid username (simple)" "nplib_validate_username" "john" 0
test_validation "Valid username (with digits)" "nplib_validate_username" "user123" 0
test_validation "Valid username (with underscore)" "nplib_validate_username" "john_doe" 0
test_validation "Valid username (with dash)" "nplib_validate_username" "john-doe" 0
test_validation "Valid username (2 chars)" "nplib_validate_username" "ab" 0

# Invalid usernames
test_validation "Invalid username (too short)" "nplib_validate_username" "a" 1
test_validation "Invalid username (starts with digit)" "nplib_validate_username" "1john" 1
test_validation "Invalid username (starts with uppercase)" "nplib_validate_username" "John" 1
test_validation "Invalid username (has uppercase)" "nplib_validate_username" "johnDoe" 1
test_validation "Invalid username (ends with dash)" "nplib_validate_username" "john-" 1
test_validation "Invalid username (special char)" "nplib_validate_username" "john@doe" 1
test_validation "Invalid username (space)" "nplib_validate_username" "john doe" 1
test_validation "Invalid username (reserved)" "nplib_validate_username" "root" 1
test_validation "Invalid username (reserved)" "nplib_validate_username" "apache" 1
test_validation "Invalid username (empty)" "nplib_validate_username" "" 1

echo ""
echo "========================================"
echo "Testing Domain Validation"
echo "========================================"

# Valid domains
test_validation "Valid domain (simple)" "nplib_validate_domain" "example.com" 0
test_validation "Valid domain (subdomain)" "nplib_validate_domain" "www.example.com" 0
test_validation "Valid domain (deep subdomain)" "nplib_validate_domain" "api.dev.example.com" 0
test_validation "Valid domain (with dash)" "nplib_validate_domain" "my-site.example.com" 0
test_validation "Valid domain (long TLD)" "nplib_validate_domain" "example.technology" 0

# Invalid domains
test_validation "Invalid domain (no TLD)" "nplib_validate_domain" "example" 1
test_validation "Invalid domain (starts with dot)" "nplib_validate_domain" ".example.com" 1
test_validation "Invalid domain (ends with dot)" "nplib_validate_domain" "example.com." 1
test_validation "Invalid domain (starts with dash)" "nplib_validate_domain" "-example.com" 1
test_validation "Invalid domain (ends with dash)" "nplib_validate_domain" "example-.com" 1
test_validation "Invalid domain (double dot)" "nplib_validate_domain" "example..com" 1
test_validation "Invalid domain (localhost)" "nplib_validate_domain" "localhost" 1
test_validation "Invalid domain (.local)" "nplib_validate_domain" "server.local" 1
test_validation "Invalid domain (too short)" "nplib_validate_domain" "a.b" 1
test_validation "Invalid domain (empty)" "nplib_validate_domain" "" 1

echo ""
echo "========================================"
echo "Testing Database Name Validation"
echo "========================================"

# Valid database names
test_validation "Valid database (simple)" "nplib_validate_database" "mydb" 0
test_validation "Valid database (with digits)" "nplib_validate_database" "db123" 0
test_validation "Valid database (with underscore)" "nplib_validate_database" "my_database" 0
test_validation "Valid database (starts with underscore)" "nplib_validate_database" "_private" 0
test_validation "Valid database (mixed case)" "nplib_validate_database" "MyDatabase" 0

# Invalid database names
test_validation "Invalid database (too short)" "nplib_validate_database" "d" 1
test_validation "Invalid database (starts with digit)" "nplib_validate_database" "123db" 1
test_validation "Invalid database (has dash)" "nplib_validate_database" "my-database" 1
test_validation "Invalid database (has space)" "nplib_validate_database" "my database" 1
test_validation "Invalid database (special char)" "nplib_validate_database" "my@database" 1
test_validation "Invalid database (reserved)" "nplib_validate_database" "mysql" 1
test_validation "Invalid database (reserved)" "nplib_validate_database" "information_schema" 1
test_validation "Invalid database (empty)" "nplib_validate_database" "" 1

echo ""
echo "========================================"
echo "Testing Database User Validation"
echo "========================================"

# Valid database usernames
test_validation "Valid dbuser (simple)" "nplib_validate_dbuser" "dbuser" 0
test_validation "Valid dbuser (with digits)" "nplib_validate_dbuser" "user123" 0
test_validation "Valid dbuser (with underscore)" "nplib_validate_dbuser" "db_user" 0
test_validation "Valid dbuser (starts with underscore)" "nplib_validate_dbuser" "_admin" 0

# Invalid database usernames
test_validation "Invalid dbuser (too short)" "nplib_validate_dbuser" "u" 1
test_validation "Invalid dbuser (starts with digit)" "nplib_validate_dbuser" "1user" 1
test_validation "Invalid dbuser (has dash)" "nplib_validate_dbuser" "db-user" 1
test_validation "Invalid dbuser (reserved)" "nplib_validate_dbuser" "root" 1
test_validation "Invalid dbuser (reserved)" "nplib_validate_dbuser" "admin" 1
test_validation "Invalid dbuser (empty)" "nplib_validate_dbuser" "" 1

echo ""
echo "========================================"
echo "Testing Email Validation"
echo "========================================"

# Valid emails
test_validation "Valid email (simple)" "nplib_validate_email" "user@example.com" 0
test_validation "Valid email (subdomain)" "nplib_validate_email" "user@mail.example.com" 0
test_validation "Valid email (plus sign)" "nplib_validate_email" "user+tag@example.com" 0
test_validation "Valid email (dots)" "nplib_validate_email" "first.last@example.com" 0
test_validation "Valid email (empty - optional)" "nplib_validate_email" "" 0

# Invalid emails
test_validation "Invalid email (no @)" "nplib_validate_email" "userexample.com" 1
test_validation "Invalid email (no domain)" "nplib_validate_email" "user@" 1
test_validation "Invalid email (no user)" "nplib_validate_email" "@example.com" 1
test_validation "Invalid email (no TLD)" "nplib_validate_email" "user@example" 1
test_validation "Invalid email (space)" "nplib_validate_email" "user @example.com" 1

echo ""
echo "========================================"
echo "Testing Password Validation"
echo "========================================"

# Valid passwords
test_validation "Valid password (strong)" "nplib_validate_password" "Password123" 0
test_validation "Valid password (long)" "nplib_validate_password" "ThisIsAVeryLongPassword123456" 0
test_validation "Valid password (special chars)" "nplib_validate_password" "P@ssw0rd!" 0
test_validation "Valid password (min length)" "nplib_validate_password" "Pass123!" 0

# Invalid passwords
test_validation "Invalid password (too short)" "nplib_validate_password" "Pass12" 1
test_validation "Invalid password (empty)" "nplib_validate_password" "" 1

echo ""
echo "========================================"
echo "Testing Domain Aliases Validation"
echo "========================================"

# Valid aliases
test_validation "Valid aliases (single)" "nplib_validate_aliases" "www.example.com" 0
test_validation "Valid aliases (multiple)" "nplib_validate_aliases" "www.example.com,blog.example.com" 0
test_validation "Valid aliases (empty)" "nplib_validate_aliases" "" 0

# Invalid aliases
test_validation "Invalid aliases (bad domain)" "nplib_validate_aliases" "www.example.com,invalid" 1
test_validation "Invalid aliases (localhost)" "nplib_validate_aliases" "localhost,example.com" 1

echo ""
echo "========================================"
echo "Test Summary"
echo "========================================"
echo "Total tests: $TOTAL_TESTS"
echo -e "Passed: ${GREEN}$PASSED_TESTS${NC}"
echo -e "Failed: ${RED}$FAILED_TESTS${NC}"
echo ""

if [[ $FAILED_TESTS -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
