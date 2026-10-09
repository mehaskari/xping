Name:           xping
Version:        1.5.2
Release:        1%{?dist}
Summary:        Network diagnostics for the terminal

License:        MIT
URL:            https://mehaskari.github.io/xping/
Source:         %{pypi_source xping}

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pytest

# used as a fallback when unprivileged ICMP sockets are not allowed
Recommends:     iputils
Recommends:     traceroute
Recommends:     iproute
Suggests:       bind-utils

%description
xping turns ping, traceroute, MTR, DNS, TLS, HTTP, mail server, Wi-Fi
and port checks into live, color-coded terminal output, over IPv4 and
IPv6. Ping and traceroute work without root through unprivileged ICMP
sockets.

"xping doctor" explains in plain words why a connection does not work.
"xping monitor" follows many checks over time as a live dashboard or a
background service, with desktop and webhook alerts, a saved history and
an HTML report.

Every command returns a meaningful exit code, accepts thresholds and
exports JSON, CSV or Markdown, so it fits scripts, cron jobs and
monitoring.


%prep
%autosetup -n xping-%{version}


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files xping

# shell completion, generated from the CLI definition
export PYTHONPATH=%{buildroot}%{python3_sitelib}
install -d %{buildroot}%{bash_completions_dir} %{buildroot}%{zsh_completions_dir} %{buildroot}%{fish_completions_dir}
%{python3} -m xping completion bash > %{buildroot}%{bash_completions_dir}/xping
%{python3} -m xping completion zsh  > %{buildroot}%{zsh_completions_dir}/_xping
%{python3} -m xping completion fish > %{buildroot}%{fish_completions_dir}/xping.fish


%check
# no network in the build: the test suite mocks every network call
export HOME=$(mktemp -d)
%pytest -q -p no:cacheprovider


%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/xping
%{_mandir}/man1/xping.1*
%{bash_completions_dir}/xping
%{zsh_completions_dir}/_xping
%{fish_completions_dir}/xping.fish


%changelog
* Fri Oct 09 2026 Mehdi Askari <iorganamis@gmail.com> - 1.5.2-1
- Initial Fedora package
