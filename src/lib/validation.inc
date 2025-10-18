#!/bin/bash
# noPanel validation functions
# © Ernesto N. Carrea / https://www.nopanel.cc

# Validate username according to Linux username rules
# nplib_validate_username 'username'
# Returns 0 if valid, 1 if invalid
nplib_validate_username() {
    local username="$1"
    
    # Check if empty
    if [[ -z "$username" ]]; then
        nplib_command_output 'error' "Username cannot be empty"
        return 1
    fi
    
    # Check length (max 32 characters per Linux standards)
    if [[ ${#username} -gt 32 ]]; then
        nplib_command_output 'error' "Username too long (max 32 characters): $username"
        return 1
    fi
    
    # Check minimum length
    if [[ ${#username} -lt 2 ]]; then
        nplib_command_output 'error' "Username too short (min 2 characters): $username"
        return 1
    fi
    
    # Must start with lowercase letter
    if [[ ! "$username" =~ ^[a-z] ]]; then
        nplib_command_output 'error' "Username must start with a lowercase letter: $username"
        return 1
    fi
    
    # Can only contain lowercase letters, digits, dash, and underscore
    # Cannot end with dash
    if [[ ! "$username" =~ ^[a-z][a-z0-9_-]*[a-z0-9]$ ]] && [[ ! "$username" =~ ^[a-z]$ ]]; then
        nplib_command_output 'error' "Username can only contain lowercase letters, digits, dash, and underscore: $username"
        return 1
    fi
    
    # Check for reserved/system usernames
    local reserved_users="root bin daemon adm lp sync shutdown halt mail operator games ftp nobody systemd-network dbus polkitd unbound rpc gluster saslauth postfix chrony sshd apache nginx mysql mariadb postgres redis memcached nopanel"
    if [[ " $reserved_users " =~ " $username " ]]; then
        nplib_command_output 'error' "Username is reserved or conflicts with system user: $username"
        return 1
    fi
    
    return 0
}

# Validate domain name according to RFC standards
# nplib_validate_domain 'domain'
# Returns 0 if valid, 1 if invalid
nplib_validate_domain() {
    local domain="$1"
    
    # Check if empty
    if [[ -z "$domain" ]]; then
        nplib_command_output 'error' "Domain cannot be empty"
        return 1
    fi
    
    # Check length (max 253 characters per RFC 1035)
    if [[ ${#domain} -gt 253 ]]; then
        nplib_command_output 'error' "Domain name too long (max 253 characters): $domain"
        return 1
    fi
    
    # Check minimum length
    if [[ ${#domain} -lt 3 ]]; then
        nplib_command_output 'error' "Domain name too short (min 3 characters): $domain"
        return 1
    fi
    
    # Must not start or end with dot, dash, or hyphen
    if [[ "$domain" =~ ^[.-] ]] || [[ "$domain" =~ [.-]$ ]]; then
        nplib_command_output 'error' "Domain cannot start or end with dot or dash: $domain"
        return 1
    fi
    
    # Check for valid domain format
    # Labels can be 1-63 characters, contain alphanumeric and hyphens
    # Cannot start or end with hyphen
    # Must have at least one dot (TLD required)
    if [[ ! "$domain" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$ ]]; then
        nplib_command_output 'error' "Invalid domain name format: $domain"
        return 1
    fi
    
    # Check each label length (max 63 per RFC 1035)
    IFS='.' read -ra labels <<< "$domain"
    for label in "${labels[@]}"; do
        if [[ ${#label} -gt 63 ]]; then
            nplib_command_output 'error' "Domain label too long (max 63 characters): $label in $domain"
            return 1
        fi
    done
    
    # Check for localhost and other reserved domains
    local reserved_domains="localhost local test invalid example com net org"
    local domain_lower="${domain,,}"
    if [[ "$domain_lower" == "localhost" ]] || [[ "$domain_lower" == *.local ]] || [[ "$domain_lower" == *.localhost ]]; then
        nplib_command_output 'error' "Domain is reserved: $domain"
        return 1
    fi
    
    return 0
}

# Validate database name
# nplib_validate_database 'dbname'
# Returns 0 if valid, 1 if invalid
nplib_validate_database() {
    local dbname="$1"
    
    # Check if empty
    if [[ -z "$dbname" ]]; then
        nplib_command_output 'error' "Database name cannot be empty"
        return 1
    fi
    
    # Check length (MySQL/MariaDB max is 64, but we use prefix, so limit to 48)
    if [[ ${#dbname} -gt 48 ]]; then
        nplib_command_output 'error' "Database name too long (max 48 characters): $dbname"
        return 1
    fi
    
    # Check minimum length
    if [[ ${#dbname} -lt 2 ]]; then
        nplib_command_output 'error' "Database name too short (min 2 characters): $dbname"
        return 1
    fi
    
    # Can only contain alphanumeric characters and underscores
    # Must start with letter or underscore
    if [[ ! "$dbname" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
        nplib_command_output 'error' "Database name can only contain letters, digits, and underscores, and must start with a letter or underscore: $dbname"
        return 1
    fi
    
    # Check for reserved MySQL/MariaDB keywords
    local reserved_names="information_schema mysql performance_schema sys test"
    local dbname_lower="${dbname,,}"
    if [[ " $reserved_names " =~ " $dbname_lower " ]]; then
        nplib_command_output 'error' "Database name is reserved: $dbname"
        return 1
    fi
    
    return 0
}

# Validate database username
# nplib_validate_dbuser 'dbuser'
# Returns 0 if valid, 1 if invalid
nplib_validate_dbuser() {
    local dbuser="$1"
    
    # Check if empty
    if [[ -z "$dbuser" ]]; then
        nplib_command_output 'error' "Database username cannot be empty"
        return 1
    fi
    
    # Check length (MySQL/MariaDB max is 32 for MariaDB 10.4+, 16 for older)
    if [[ ${#dbuser} -gt 32 ]]; then
        nplib_command_output 'error' "Database username too long (max 32 characters): $dbuser"
        return 1
    fi
    
    # Check minimum length
    if [[ ${#dbuser} -lt 2 ]]; then
        nplib_command_output 'error' "Database username too short (min 2 characters): $dbuser"
        return 1
    fi
    
    # Can only contain alphanumeric characters and underscores
    if [[ ! "$dbuser" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
        nplib_command_output 'error' "Database username can only contain letters, digits, and underscores: $dbuser"
        return 1
    fi
    
    # Check for reserved users
    local reserved_users="root mysql mariadb admin administrator sys"
    local dbuser_lower="${dbuser,,}"
    if [[ " $reserved_users " =~ " $dbuser_lower " ]]; then
        nplib_command_output 'error' "Database username is reserved: $dbuser"
        return 1
    fi
    
    return 0
}

# Validate email address (basic RFC 5322 validation)
# nplib_validate_email 'email'
# Returns 0 if valid, 1 if invalid
nplib_validate_email() {
    local email="$1"
    
    # Check if empty (email is optional in many commands, so allow empty)
    if [[ -z "$email" ]]; then
        return 0
    fi
    
    # Check length
    if [[ ${#email} -gt 254 ]]; then
        nplib_command_output 'error' "Email address too long (max 254 characters): $email"
        return 1
    fi
    
    # Basic email validation
    if [[ ! "$email" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        nplib_command_output 'error' "Invalid email address format: $email"
        return 1
    fi
    
    return 0
}

# Validate password strength
# nplib_validate_password 'password'
# Returns 0 if valid, 1 if invalid
nplib_validate_password() {
    local password="$1"
    
    # Check if empty
    if [[ -z "$password" ]]; then
        nplib_command_output 'error' "Password cannot be empty"
        return 1
    fi
    
    # Check minimum length
    if [[ ${#password} -lt 8 ]]; then
        nplib_command_output 'error' "Password too short (min 8 characters)"
        return 1
    fi
    
    # Check maximum length (for practical reasons)
    if [[ ${#password} -gt 128 ]]; then
        nplib_command_output 'error' "Password too long (max 128 characters)"
        return 1
    fi
    
    # Recommend (but don't require) complexity
    # This is just a warning, not an error
    local has_lower=0
    local has_upper=0
    local has_digit=0
    
    [[ "$password" =~ [a-z] ]] && has_lower=1
    [[ "$password" =~ [A-Z] ]] && has_upper=1
    [[ "$password" =~ [0-9] ]] && has_digit=1
    
    if [[ $has_lower -eq 0 ]] || [[ $has_upper -eq 0 ]] || [[ $has_digit -eq 0 ]]; then
        nplib_command_echo "  Warning: Password should contain uppercase, lowercase, and digits for better security" >&2
    fi
    
    return 0
}

# Validate domain aliases (comma-separated list)
# nplib_validate_aliases 'alias1,alias2,alias3'
# Returns 0 if valid, 1 if invalid
nplib_validate_aliases() {
    local aliases="$1"
    
    # Empty is ok
    if [[ -z "$aliases" ]]; then
        return 0
    fi
    
    # Split by comma and validate each
    IFS=',' read -ra alias_array <<< "$aliases"
    for alias in "${alias_array[@]}"; do
        # Trim whitespace
        alias=$(echo "$alias" | xargs)
        
        if [[ -n "$alias" ]]; then
            if ! nplib_validate_domain "$alias"; then
                return 1
            fi
        fi
    done
    
    return 0
}
