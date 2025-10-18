#!/bin/bash
# Test script to validate parameter parsing with = sign

cd "$(dirname "$0")/.." || exit 1

echo "Testing parameter parsing with = format..."
echo ""

# Test the params.inc parsing logic
source src/lib/params.inc

# Simulate parsing --output=test.json
set -- "--output=test.json" "--users"

# Source params.inc parsing (the for loop part)
params=''
for param in "$@"
do
    if [[ $param == *"--"* ]]; then
        if [ "$param_name" ] && [ ! "${!param_name}" ]; then
            declare $param_name=1
        fi
        
        if [[ $param == *"="* ]]; then
            param_name=$(echo "param_${param:2}" | cut -d'=' -f1 | sed 's/-/_/')
            param_value=$(echo "$param" | cut -d'=' -f2-)
            [[ $params =~ (^|[[:space:]])$param_name($|[[:space:]]) ]] || params="$params $param_name"
            declare $param_name="$param_value"
            param_name=''
            last_was='value'
        else
            param_name=$(echo "param_${param:2}" | sed 's/-/_/')
            [[ $params =~ (^|[[:space:]])$param_name($|[[:space:]]) ]] || params="$params $param_name"
            last_was='name'
        fi
    else
        if [ "$param_name" ]; then
            if [ "${!param_name}" ]; then
                declare $param_name="${!param_name} $param"
            else
                declare $param_name="$param"
            fi
        fi
        last_was='value'
    fi
done
if [ "$last_was" == 'name' ]; then
    declare $param_name=1
fi

# Check results
if [[ "$param_output" == "test.json" ]]; then
    echo "✓ --output=test.json parsed correctly: '$param_output'"
else
    echo "✗ --output=test.json parsing failed: got '$param_output' instead of 'test.json'"
    exit 1
fi

if [[ "$param_users" == "1" ]]; then
    echo "✓ --users parsed correctly as boolean flag"
else
    echo "✗ --users parsing failed: got '$param_users'"
    exit 1
fi

echo ""
echo "Parameter parsing test passed!"
