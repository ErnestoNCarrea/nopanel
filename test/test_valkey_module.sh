#!/bin/bash
# Quick test for Valkey module structure

cd "$(dirname "$0")" || exit 1

echo "Testing Valkey module structure..."
echo ""

# Test 1: Install script exists
if [[ -f "src/lib/cli/module/valkey/install" ]]; then
    echo "✓ Install script exists"
else
    echo "✗ Install script missing"
    exit 1
fi

# Test 2: Install script is executable
if [[ -x "src/lib/cli/module/valkey/install" ]]; then
    echo "✓ Install script is executable"
else
    echo "✗ Install script is not executable"
    exit 1
fi

# Test 3: Install script has correct function name
if grep -q "nopanel_module_valkey_install()" "src/lib/cli/module/valkey/install"; then
    echo "✓ Install function has correct name"
else
    echo "✗ Install function name incorrect"
    exit 1
fi

# Test 4: OSAL variables defined in RHEL
if grep -q "OSAL_PKG_VALKEY" "src/lib/osal_rhel_based.inc"; then
    echo "✓ OSAL variables defined for RHEL"
else
    echo "✗ OSAL variables missing for RHEL"
    exit 1
fi

# Test 5: OSAL variables defined in Debian
if grep -q "OSAL_PKG_VALKEY" "src/lib/osal_debian_based.inc"; then
    echo "✓ OSAL variables defined for Debian"
else
    echo "✗ OSAL variables missing for Debian"
    exit 1
fi

# Test 6: Module registered in modules.json.dist
if grep -q '"valkey"' "share/etc/nopanel/modules.json.dist"; then
    echo "✓ Module registered in modules.json.dist"
else
    echo "✗ Module not registered in modules.json.dist"
    exit 1
fi

# Test 7: Install script uses nplib_auto_elevate
if grep -q "nplib_auto_elevate" "src/lib/cli/module/valkey/install"; then
    echo "✓ Uses nplib_auto_elevate for privilege escalation"
else
    echo "✗ Missing nplib_auto_elevate"
    exit 1
fi

# Test 8: Install script marks module as installed
if grep -q "nplib_modules_set_installed.*valkey.*true" "src/lib/cli/module/valkey/install"; then
    echo "✓ Marks module as installed"
else
    echo "✗ Doesn't mark module as installed"
    exit 1
fi

echo ""
echo "All tests passed! ✓"
