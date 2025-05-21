#
# spec file for package saline
#
# Copyright (c) 2024-2025 SUSE LLC
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License). An "Open Source License" is a
# license that conforms to the Open Source Definition (Version 1.9)
# published by the Open Source Initiative.

# Please submit bugfixes or comments via https://bugs.opensuse.org/
#


%{?sle15allpythons}
%define skip_python2 1

%if 0%{?suse_version} > 1500
%bcond_without libalternatives
%else
%bcond_with libalternatives
%endif

%define plainpython python

%define salt_formulas_dir %{_datadir}/salt-formulas

Name:           saline
Version:        0
Release:        0
Summary:        The salt events collector and manager
License:        Apache-2.0
Group:          Development/Languages/Python
URL:            https://github.com/openSUSE/saline
Source0:        saline-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  fdupes
BuildRequires:  python-rpm-macros
BuildRequires:  systemd-rpm-macros
BuildRequires:  %{python_module base >= 3.6}
BuildRequires:  %{python_module setuptools}
BuildRequires:  %{python_module packaging}
BuildRequires:  %{python_module pip}
BuildRequires:  %{python_module wheel}
Requires(pre):  salt
Requires:       salined = %{version}-%{release}
Requires:       logrotate
Requires:       salt-master
Requires:       systemd
%define python_subpackage_only 1
%python_subpackages

%description
Saline is an extension for Salt providing an extra control of state apply process.
Saline also exposes the metrics from salt events to provide more visible salt monitoring.

%package -n python-saline
Summary:        The salt events collector and manager python module
Group:          System/Management
Requires:       %plainpython(abi) = %{python_version}
Requires:       python-tornado
Requires:       python-python-dateutil
Requires:       python-salt
Requires:       config(%{name}) = %{version}-%{release}
%if %{with libalternatives}
Requires:       alts
BuildRequires:  alts
%else
Requires(post): update-alternatives
Requires(postun):update-alternatives
%endif
Provides:       salined = %{version}-%{release}
BuildRoot:      %{_tmppath}/%{name}-%{version}

%description -n python-saline
Saline python library.

Saline is an extension for Salt providing an extra control of state apply process.
Saline also exposes the metrics from salt events to provide more visible salt monitoring.

%package formula
Summary:        Saline salt formula%{?productprettyname: for %productprettyname}
Group:          System/Management
Requires:       grafana-formula
Requires:       prometheus-exporters-formula

%description formula
Saline salt formula%{?productprettyname: for %productprettyname}.
Provides formulas for Prometheus exporters and Grafana dashboards configuration.

%prep
%autosetup -n %{name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%python_clone -a %{buildroot}%{_bindir}/salined
%python_expand %fdupes %{buildroot}%{$python_sitelib}

install -Dpm 0644 salined.service %{buildroot}%{_unitdir}/salined.service

install -Ddm 0755 %{buildroot}%{_sbindir}
ln -sv %{_sbindir}/service %{buildroot}%{_sbindir}/rcsalined

install -Dpm 0755 scripts/saline-setup %{buildroot}%{_sbindir}/

install -Dpm 0644 conf/logrotate.d/saline %{buildroot}%{_sysconfdir}/logrotate.d/saline

install -Ddm 0755 %{buildroot}%{_sysconfdir}/salt/saline.d

install -Dpm 0644 conf/salt/saline %{buildroot}%{_sysconfdir}/salt/saline
install -Dpm 0644 conf/salt/saline.d/*.conf %{buildroot}%{_sysconfdir}/salt/saline.d/

install -Ddm 0755 %{buildroot}%{_sysconfdir}/salt/pki/saline

install -Ddm 0755 %{buildroot}%{_sysconfdir}/alternatives

install -Ddm 0755 %{buildroot}%{salt_formulas_dir}/metadata
install -Ddm 0755 %{buildroot}%{salt_formulas_dir}/states
cp -a formulas/metadata/* %{buildroot}%{salt_formulas_dir}/metadata/
cp -a formulas/states/* %{buildroot}%{salt_formulas_dir}/states/

%pre
%service_add_pre salined.service

%preun
%service_del_preun salined.service

%post
%service_add_post salined.service

%postun
%service_del_postun_with_restart salined.service

%pre -n python-saline
# If libalternatives is used: Removing old update-alternatives entries.
%python_libalternatives_reset_alternative salined

%post -n python-saline
%python_install_alternative salined

%postun -n python-saline
%python_uninstall_alternative salined

%files
%defattr(-,root,root,-)
%config(noreplace) %{_sysconfdir}/logrotate.d/saline
%dir %attr(0750,salt,salt) %{_sysconfdir}/salt/saline.d
%config %attr(0640,salt,salt) %{_sysconfdir}/salt/saline
%config %attr(0640,salt,salt) %{_sysconfdir}/salt/saline.d/*.conf
%dir %attr(0750,salt,salt) %{_sysconfdir}/salt/pki/saline
%ghost %config %attr(0600,salt,salt) %{_sysconfdir}/salt/pki/saline/uyuni.crt
%ghost %config %attr(0600,salt,salt) %{_sysconfdir}/salt/pki/saline/uyuni.key
%{_sbindir}/saline-setup
%{_sbindir}/rcsalined
%{_unitdir}/salined.service
%ghost %dir %attr(0750,salt,salt) /var/log/salt
%ghost %attr(0640,salt,salt) /var/log/salt/saline
%ghost %attr(0640,salt,salt) /var/log/salt/saline-api-access.log
%ghost %attr(0640,salt,salt) /var/log/salt/saline-api-error.log

%files formula
%dir %{salt_formulas_dir}
%dir %{salt_formulas_dir}/metadata
%dir %{salt_formulas_dir}/states
%{salt_formulas_dir}/metadata/saline-*
%{salt_formulas_dir}/states/saline-*

%files %{python_files saline}
%license LICENSE
%defattr(-,root,root,-)
%python_alternative %{_bindir}/salined
%{python_sitelib}/saline*

%changelog
