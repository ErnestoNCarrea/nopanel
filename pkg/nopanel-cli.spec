Name:           nopanel-cli
Version:        1.0
Release:        24
Summary:        noPanel CLI
Group:          System Environment/Base
License:        GPLv3
URL:            https://www.nopanel.cc
Vendor:         nopanel.cc
Requires:       (redhat-release >= 7 or fedora-release-common >= 32)
Requires:       bash
Requires:       util-linux
Requires:       sed
Requires:       tar
Requires:       gzip
Requires:       jq
Requires:       libidn
Requires:       curl
Requires:       openssl
Provides:       nopanel-cli = %{version}
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root
BuildArch:      noarch

%description
This package contains the noPanel command line interface.

%prep

%build
# Nothing to build

%install
install -m 0750 -d %{buildroot}/etc/nopanel
install -m 755 -D "%{_sourcedir}/bin"/* -t "%{buildroot}%{_bindir}/"

mkdir -p "%{buildroot}/usr/local/nopanel/"
cp -rfa "%{_sourcedir}/lib"/* "%{buildroot}/usr/local/nopanel/"

mkdir -p "%{buildroot}/usr/share/nopanel/"
cp -rfa "%{_sourcedir}/../share"/* "%{buildroot}/usr/share/nopanel/"

%clean

%pre

%post
if [[ -f /etc/nopanel/nopanel.json ]]; then
    %{_bindir}/nopanel upgrade --interactive no --output silent
fi

%preun

%postun

%files
%defattr(-,root,root)
%attr(755,root,root) %{_bindir}/nopanel
%attr(755,root,root) /usr/local/nopanel/
%attr(755,root,root) /usr/share/nopanel/
%attr(755,root,root) /etc/nopanel/

%changelog
# nothing