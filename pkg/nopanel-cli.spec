Name:           nopanel-cli
Version:        1.0
Release:        1%{?dist}
Summary:        noPanel CLI
Group:          System Environment/Base
License:        GPLv3
URL:            https://www.nopanel.com
Vendor:         nopanel.com
Requires:       (redhat-release >= 7) OR (fedora-release-common >= 32)
Requires:       bash
Requires:       jq
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

%clean

%pre

%post
%{_bindir}/nopanel init

%preun

%postun

%files
%defattr(-,root,root)
%attr(755,root,root) %{_bindir}/nopanel
%attr(755,root,root) /usr/local/nopanel/
%attr(755,root,root) /etc/nopanel/

%changelog
# nothing