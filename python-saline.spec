# spec file for package python-saline

%define plainpython python

%define salt_formulas_dir %{_datadir}/salt-formulas

Name:           python-saline
Version:        0
Release:        0
Summary:        The salt events collector and manager python module
License:        Apache-2.0
Group:          Development/Languages/Python
URL:            https://github.com/vzhestkov/saline
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
Requires:       %plainpython(abi) = %{python_version}
Requires:       python-CherryPy
Requires:       python-python-dateutil
Requires:       python-salt
Requires:       config(saline) = %{version}-%{release}
Requires(post): update-alternatives
Requires(postun):update-alternatives
Provides:       saline(module-python) = %{version}-%{release}
BuildRoot:      %{_tmppath}/saline-%{version}
%python_subpackages

%description
Saline python library.

Saline is an extension for Salt providing an extra control of state apply process.
Saline also exposes the metrics from salt events to provide more visible salt monitoring.

%package -n saline
Summary:        The salt events collector and manager
Group:          System/Management
Requires(pre):  salt
Requires:       logrotate
Requires:       salt-master
Requires:       systemd
Requires:       saline(module-python) = %{version}-%{release}

%description -n saline
Saline is an extension for Salt providing an extra control of state apply process.
Saline also exposes the metrics from salt events to provide more visible salt monitoring.

%package -n saline-formula
Summary:        Saline salt formula for Uyuni/SUSE Manager
Group:          System/Management
Requires:       grafana-formula
Requires:       prometheus-exporters-formula

%description -n saline-formula
Saline salt formula for Uyuni/SUSE Manager with exporters configuration and dashboards.

%prep
%autosetup -n saline-%{version}

%build
#%%python_build
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

%pre -n saline
%service_add_pre salined.service

%preun -n saline
%service_del_preun salined.service

%post
%python_install_alternative salined

%post -n saline
%service_add_post salined.service

%postun
%python_uninstall_alternative salined

%postun -n saline
%service_del_postun_with_restart salined.service

%files %python_files
%license LICENSE
%defattr(-,root,root,-)
%python_alternative %{_bindir}/salined
%{python_sitelib}/saline*

%files -n saline
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

%files -n saline-formula
%dir %{salt_formulas_dir}
%dir %{salt_formulas_dir}/metadata
%dir %{salt_formulas_dir}/states
%{salt_formulas_dir}/metadata/saline-*
%{salt_formulas_dir}/states/saline-*

%changelog
