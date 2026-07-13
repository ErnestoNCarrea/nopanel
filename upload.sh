#!/bin/bash
# Upload and install noPanel RPM package to remote hosts
# Usage: ./upload.sh [hostname]
#   hostname (optional) - specific host to upload to, or all hosts if not specified

# Parse command line arguments
SPECIFIC_HOST="$1"

# Show help if requested
if [ "$SPECIFIC_HOST" = "-h" ] || [ "$SPECIFIC_HOST" = "--help" ]; then
    echo "Usage: $0 [hostname]"
    echo ""
    echo "Upload and install noPanel RPM package to remote hosts"
    echo ""
    echo "Arguments:"
    echo "  hostname    (optional) Specific host to deploy to"
    echo "              If not specified, deploys to all hosts"
    echo ""
    echo "Available hosts: fidel enio ares medusa apolo"
    echo ""
    echo "Examples:"
    echo "  $0              # Deploy to all hosts"
    echo "  $0 fidel        # Deploy to fidel only"
    echo "  $0 ares         # Deploy to ares only"
    exit 0
fi

# Define all available hosts
ALL_HOSTS="fidel enio ares medusa apolo"

# Determine which hosts to deploy to
if [ -n "$SPECIFIC_HOST" ]; then
    # Check if the specified host is in the list
    if echo "$ALL_HOSTS" | grep -qw "$SPECIFIC_HOST"; then
        DEPLOY_HOSTS="$SPECIFIC_HOST"
        echo "Deploying to specific host: $SPECIFIC_HOST"
    else
        echo "Error: Unknown host '$SPECIFIC_HOST'"
        echo "Available hosts: $ALL_HOSTS"
        exit 1
    fi
else
    DEPLOY_HOSTS="$ALL_HOSTS"
    echo "Deploying to all hosts: $ALL_HOSTS"
fi

for HOST in $DEPLOY_HOSTS; do
    echo "Deploying to $HOST..."
    ssh root@$HOST 'rm -f /root/nopanel-*.rpm'
    rsync -a ~/rpmbuild/RPMS/noarch/nopanel-*.rpm root@$HOST:/root/
    ssh root@$HOST 'LANG=C dnf -y -q install /root/nopanel-*.rpm'
    ssh root@$HOST 'LANG=C dnf -y -q reinstall /root/nopanel-*.rpm'
    echo "✓ $HOST deployment complete"
done

echo ""
echo "Deployment completed successfully!"
