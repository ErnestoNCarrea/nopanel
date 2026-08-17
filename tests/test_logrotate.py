"""Regression tests for the static Apache logrotate configs under share/.

noPanel generates per-domain ``.log``, ``.error.log`` and ``.bytes`` log files
(see share/web/apache/domain.{http,https}.conf and the commit hook that touches
``$DOMAIN_LOGS/$param_domain.bytes``). The logrotate path globs must match
*only* those active log files and never the rotated archives, otherwise -- with
``dateext`` enabled -- logrotate re-rotates the archives every cycle and
produces unbounded ``-YYYYMMDD.gz`` chains (this happened on fidel: 8000+ files
accumulated in /var/log/httpd/domains/).

These tests guard the two static config files that the shell installers copy
into /etc/logrotate.d (src/lib/cli/module/apache/install):
  * share/rhel/logrotate/httpd
  * share/debian/logrotate/apache2
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_LOGROTATE_FILES = {
    "rhel": _REPO_ROOT / "share" / "rhel" / "logrotate" / "httpd",
    "debian": _REPO_ROOT / "share" / "debian" / "logrotate" / "apache2",
}


@pytest.fixture(params=sorted(_LOGROTATE_FILES))
def logrotate_conf(request):
    path = _LOGROTATE_FILES[request.param]
    if not path.is_file():
        pytest.skip(f"{path} not present")
    return path.read_text()


def _paths_block(text):
    """Return the first line (the path spec) of a logrotate stanza."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "{" in stripped:
            return stripped
    raise AssertionError("no logrotate stanza header found")


def test_glob_does_not_match_rotated_archives(logrotate_conf):
    """No path glob may end with a bare ``domains/*`` -- that matches the
    rotated archives (``foo.log-20260224.gz``) and triggers re-rotation."""
    header = _paths_block(logrotate_conf)
    for token in header.split():
        if token.endswith("{"):
            continue
        assert not token.endswith("domains/*"), (
            f"bare 'domains/*' glob re-rotates archives: {token!r} in {header!r}"
        )


def test_glob_covers_bytes_logs(logrotate_conf):
    """noPanel writes a ``.bytes`` CustomLog for every domain, so the glob set
    must include a ``*.bytes`` entry or those logs never rotate."""
    header = _paths_block(logrotate_conf)
    assert "*.bytes" in header, (
        f".bytes logs not covered by glob: {header!r}"
    )


def test_glob_covers_error_logs(logrotate_conf):
    """``.error.log`` must be rotated. ``*.log`` matches it; the legacy Debian
    ``*log`` also matched it. Either is acceptable, but it must be covered."""
    header = _paths_block(logrotate_conf)
    assert "*.log" in header or "*log" in header, (
        f".log/.error.log not covered by glob: {header!r}"
    )
