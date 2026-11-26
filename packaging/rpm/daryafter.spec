Name:           daryafter
Version:        0.1.1
Release:        1
Summary:        Free, open-source multi-connection download manager
License:        MIT
URL:            https://github.com/RezaMarozi/daryafter
BuildArch:      x86_64
Requires:       glibc
Requires:       zlib

# Everything else the app links to is bundled under /opt/daryafter
# (PyInstaller) and found via the bootloader's LD_LIBRARY_PATH (verified
# with LD_DEBUG: even libstdc++.so.6 resolves to the bundled copy).
# Without this rpm auto-detects ~763 soname Requires from the bundled Qt
# libraries (libQt6*, libFLAC, ...) that merely shadow obsolete/unused
# packages on target distributions.
%global __requires_exclude ^((lib|ld-linux).*|/usr/bin/env)(\\(.*\\))?$

%description
Free, open-source multi-connection download manager.

%install
mkdir -p %{buildroot}/opt/daryafter
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/usr/share/applications
mkdir -p %{buildroot}/usr/share/icons/hicolor/scalable/apps

cp -a %{appdir}/. %{buildroot}/opt/daryafter/
printf '%s\n' '#!/bin/sh' 'exec /opt/daryafter/Daryafter "$@"' > %{buildroot}/usr/bin/daryafter
chmod 755 %{buildroot}/usr/bin/daryafter
cp %{desktop} %{buildroot}/usr/share/applications/daryafter.desktop
cp %{icon} %{buildroot}/usr/share/icons/hicolor/scalable/apps/daryafter.svg

%files
/opt/daryafter
/usr/bin/daryafter
/usr/share/applications/daryafter.desktop
/usr/share/icons/hicolor/scalable/apps/daryafter.svg
