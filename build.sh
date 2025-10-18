#!/bin/bash
# noPanel Build Script
# Usage: ./build.sh [-i] [-b]
#   -i  Increment release number
#   -b  Build RPM package

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
SPEC_FILE="$PROJECT_ROOT/pkg/nopanel-cli.spec"
VERSION_FILE="$PROJECT_ROOT/src/bin/nopanel"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse command line arguments
INCREMENT=false
BUILD_RPM=false

while getopts "ib" opt; do
    case $opt in
        i)
            INCREMENT=true
            ;;
        b)
            BUILD_RPM=true
            ;;
        \?)
            echo "Invalid option: -$OPTARG" >&2
            echo "Usage: $0 [-i] [-b]"
            echo "  -i  Increment release number"
            echo "  -b  Build RPM package"
            exit 1
            ;;
    esac
done

# Get current version and release
get_current_version() {
    grep "^NOPANEL_VERSION=" "$VERSION_FILE" | cut -d'=' -f2 | tr -d ' '
}

get_current_release() {
    grep "^Release:" "$SPEC_FILE" | awk '{print $2}' | tr -d ' '
}

get_spec_version() {
    grep "^Version:" "$SPEC_FILE" | awk '{print $2}' | tr -d ' '
}

# Increment release number
increment_release() {
    local current_release=$(get_current_release)
    local new_release=$((current_release + 1))
    local current_version=$(get_spec_version)
    
    echo -e "${BLUE}Current version: ${current_version}.${current_release}${NC}"
    echo -e "${YELLOW}Incrementing release: ${current_release} -> ${new_release}${NC}"
    
    # Update spec file
    sed -i "s/^Release:.*$/Release:        ${new_release}/" "$SPEC_FILE"
    
    # Update version in nopanel script
    sed -i "s/^NOPANEL_VERSION=.*$/NOPANEL_VERSION=${current_version}.${new_release}/" "$VERSION_FILE"
    
    echo -e "${GREEN}✓ Release incremented to ${new_release}${NC}"
    echo -e "${GREEN}✓ Version updated to ${current_version}.${new_release}${NC}"
}

# Build RPM package
build_rpm() {
    local version=$(get_spec_version)
    local release=$(get_current_release)
    
    echo -e "${BLUE}Building RPM for version ${version}.${release}${NC}"
    
    # Check if rpmbuild is available
    if ! command -v rpmbuild &> /dev/null; then
        echo -e "${RED}✗ rpmbuild not found. Please install rpm-build package.${NC}"
        exit 1
    fi
    
    # Setup RPM build tree
    echo -e "${YELLOW}Setting up RPM build tree...${NC}"
    rpmdev-setuptree 2>/dev/null || mkdir -p ~/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
    
    # Build the RPM
    echo -e "${YELLOW}Building RPM package...${NC}"
    cd "$PROJECT_ROOT/pkg"
    
    if rpmbuild -ba nopanel-cli.spec --define "_sourcedir $PROJECT_ROOT/src"; then
        echo -e "${GREEN}✓ RPM build successful${NC}"
        echo -e "${GREEN}  Location: ~/rpmbuild/RPMS/noarch/nopanel-cli-${version}-${release}.noarch.rpm${NC}"
        echo -e "${GREEN}  SRPM: ~/rpmbuild/SRPMS/nopanel-cli-${version}-${release}.src.rpm${NC}"
        
        # Show RPM info
        if [ -f ~/rpmbuild/RPMS/noarch/nopanel-cli-${version}-${release}.noarch.rpm ]; then
            echo ""
            echo -e "${BLUE}Package information:${NC}"
            rpm -qip ~/rpmbuild/RPMS/noarch/nopanel-cli-${version}-${release}.noarch.rpm | grep -E "^(Name|Version|Release|Size|Summary)"
        fi
    else
        echo -e "${RED}✗ RPM build failed${NC}"
        exit 1
    fi
}

# Main execution
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  noPanel Build Script${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    # Show current version
    local current_version=$(get_spec_version)
    local current_release=$(get_current_release)
    echo -e "${BLUE}Current version: ${current_version}.${current_release}${NC}"
    echo ""
    
    # Execute requested actions
    if [ "$INCREMENT" = false ] && [ "$BUILD_RPM" = false ]; then
        echo -e "${YELLOW}No action specified. Use -i to increment or -b to build.${NC}"
        echo ""
        echo "Usage: $0 [-i] [-b]"
        echo "  -i  Increment release number"
        echo "  -b  Build RPM package"
        echo ""
        echo "Examples:"
        echo "  $0 -i           # Increment release number"
        echo "  $0 -b           # Build RPM"
        echo "  $0 -i -b        # Increment and build"
        exit 0
    fi
    
    if [ "$INCREMENT" = true ]; then
        increment_release
        echo ""
    fi
    
    if [ "$BUILD_RPM" = true ]; then
        build_rpm
        echo ""
    fi
    
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Build completed successfully!${NC}"
    echo -e "${GREEN}========================================${NC}"
}

main
