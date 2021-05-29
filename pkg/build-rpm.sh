#!/bin/bash
#RPMBUILD=~/rpmbuild/
#RPMBUILD_SRC=$RPMBUILD/SOURCES/nopanel-cli-1.0
#OUTPUT_DIR="$(dirname "$BUILD_DIR")"/rpm/
#mkdir -p $RPMBUILD_SRC $OUTPUT_DIR $OUTPUT_DIR/rpmbuild

#rpmbuild -bb --define "sourcedir $RPMBUILD_SRC" nopanel-cli.spec > ${OUTPUT_DIR}.rpm.log --buildroot=$RPMBUILD

BUILD_DIR=$(pwd)
SOURCE_DIR="$(dirname "$BUILD_DIR")"/src/

rpmdev-setuptree
rpmbuild -ba nopanel-cli.spec --define "_sourcedir $SOURCE_DIR"