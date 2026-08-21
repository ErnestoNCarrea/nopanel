"""Tests for nopanel.templates — Jinja2 template rendering."""


from nopanel.templates import (
    render_apache_vhost_http,
    render_apache_vhost_https,
    render_compose,
    render_httpd_base,
    render_mod_md_config,
    render_php_dockerfile,
    render_php_fpm_pool,
)


class TestRenderApacheVhostHttp:
    def test_basic_vhost(self):
        result = render_apache_vhost_http(
            domain="example.com",
            user="alice",
            docroot="/home/alice/web/example.com/public_html",
            aliases=["www.example.com"],
            php_socket="/var/run/php-fpm/php82-www.sock",
            log_dir="/var/log/nopanel/apache",
            email="alice@example.com",
        )
        assert "example.com" in result
        assert "www.example.com" in result
        assert "/home/alice/web/example.com/public_html" in result
        assert "alice@example.com" in result
        assert "/var/run/php-fpm/php82-www.sock" in result

    def test_vhost_no_php(self):
        result = render_apache_vhost_http(
            domain="static.com",
            user="alice",
            docroot="/home/alice/web/static.com/public_html",
            aliases=[],
            php_socket=None,
            log_dir="/var/log/nopanel/apache",
        )
        assert "static.com" in result
        assert "SetHandler" not in result

    def test_vhost_no_aliases(self):
        result = render_apache_vhost_http(
            domain="example.com",
            user="alice",
            docroot="/home/alice/web/example.com/public_html",
            aliases=[],
            php_socket=None,
            log_dir="/var/log/nopanel/apache",
        )
        assert "ServerAlias" not in result

    def test_vhost_ssl_auto_redirect(self):
        """HTTP vhost with ssl_mode=auto should include HTTPS redirect."""
        result = render_apache_vhost_http(
            domain="example.com",
            user="alice",
            docroot="/home/alice/web/example.com/public_html",
            aliases=[],
            php_socket=None,
            log_dir="/var/log/nopanel/apache",
            ssl_mode="auto",
        )
        assert "RewriteRule" in result
        assert "https://%{HTTP_HOST}" in result

    def test_vhost_ssl_none_no_redirect(self):
        """HTTP vhost with ssl_mode=none should NOT include HTTPS redirect."""
        result = render_apache_vhost_http(
            domain="example.com",
            user="alice",
            docroot="/home/alice/web/example.com/public_html",
            aliases=[],
            php_socket=None,
            log_dir="/var/log/nopanel/apache",
            ssl_mode="none",
        )
        assert "RewriteRule" not in result


class TestRenderApacheVhostHttps:
    def test_basic_https_vhost(self):
        result = render_apache_vhost_https(
            domain="example.com",
            user="alice",
            docroot="/home/alice/web/example.com/public_html",
            aliases=[],
            php_socket="/var/run/php-fpm/php82-www.sock",
            log_dir="/var/log/nopanel/apache",
            ssl_cert="/etc/ssl/cert.pem",
            ssl_key="/etc/ssl/key.pem",
        )
        assert "SSLEngine on" in result
        assert "/etc/ssl/cert.pem" in result
        assert "/etc/ssl/key.pem" in result


class TestRenderModMd:
    def test_mod_md_config(self):
        result = render_mod_md_config(
            domains=["example.com", "test.com"],
            admin_email="admin@example.com",
        )
        assert "admin@example.com" in result
        assert "MDomain example.com auto" in result
        assert "MDomain test.com auto" in result


class TestRenderPhpFpmPool:
    def test_pool_config(self):
        result = render_php_fpm_pool(
            domain="example.com",
            user="alice",
            socket_path="/var/run/php-fpm/php82-www.sock",
            php_version="8.2",
        )
        assert "[example.com]" in result
        assert "user = alice" in result
        assert "/var/run/php-fpm/php82-www.sock" in result

    def test_pool_config_uses_www_data(self):
        """Pool config should use www-data for listen.owner/group (matching httpd:2.4-alpine)."""
        result = render_php_fpm_pool(
            domain="example.com",
            user="alice",
            socket_path="/var/run/php-fpm/php82-www.sock",
            php_version="8.2",
        )
        assert "listen.owner = www-data" in result
        assert "listen.group = www-data" in result


class TestRenderCompose:
    def test_compose_basic(self):
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "secret", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }

        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "nopanel-apache" in result
        assert "nopanel-php-8.2" in result
        assert "nopanel-mariadb" in result
        assert "nopanel-valkey" in result
        assert "network_mode: host" in result

    def test_compose_no_remi_volume(self):
        """Volumes should not include /var/opt/remi (fix #13 — RHEL-specific, not needed in Alpine containers)."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "secret", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "/var/opt/remi" not in result

    def test_compose_bridge_mode(self):
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {},
        }
        result = render_compose(
            services=services,
            network_mode="bridge",
            php_versions=[],
        )
        assert "network_mode: bridge" in result

    def test_compose_bridge_has_ports(self):
        """Bridge mode should include port mappings (fix #10)."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "secret", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="bridge",
            php_versions=["8.2"],
        )
        assert "ports:" in result
        assert "80:80" in result
        assert "443:443" in result
        assert "3306:3306" in result
        assert "6379:6379" in result

    def test_compose_host_no_ports(self):
        """Host mode should NOT include port mappings (fix #10)."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=[],
        )
        assert "ports:" not in result

    def test_compose_bridge_has_depends_on(self):
        """Bridge mode should include depends_on for service ordering (fix #11)."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="bridge",
            php_versions=["8.2"],
        )
        assert "depends_on:" in result
        # Apache depends on PHP-FPM
        assert "php-8.2" in result
        # PHP depends on MariaDB
        assert "mariadb" in result

    def test_compose_host_no_depends_on(self):
        """Host mode should NOT include depends_on (fix #11)."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "depends_on:" not in result

    def test_compose_php_fpm_mount_alpine(self):
        """PHP-FPM volume mount should use Alpine path /usr/local/etc/php-fpm.d (fix #14)."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "/usr/local/etc/php-fpm.d" in result
        assert ":/etc/php-fpm.d:" not in result

    def test_compose_per_service_volumes(self):
        """Each service should have tailored volume mounts, not all the same."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        # MariaDB should have /var/lib/mysql but not /home
        assert "/var/lib/mysql" in result
        # Valkey should not have /home or /var/lib/mysql
        # Apache should have pki mount
        assert "/etc/nopanel/pki" in result

    def test_compose_php_mounts_passwd_group(self):
        """PHP-FPM containers must mount /etc/passwd and /etc/group read-only
        so they can resolve host usernames to UIDs for pool user/group directives."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "/etc/passwd:/etc/passwd:ro" in result
        assert "/etc/group:/etc/group:ro" in result

    def test_compose_has_health_checks(self):
        """docker-compose should include health checks for all services."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert "healthcheck:" in result
        assert "httpd" in result  # Apache health check
        assert "php-fpm" in result  # PHP health check
        assert "healthcheck.sh" in result  # MariaDB health check
        assert "valkey-cli" in result  # Valkey health check


class TestRenderPhpDockerfile:
    def test_dockerfile(self):
        result = render_php_dockerfile(
            php_version="8.2",
            core_extensions=["mysqli", "pdo", "gd"],
            pecl_extensions=["redis"],
        )
        assert "FROM php:8.2-fpm-alpine" in result
        assert "docker-php-ext-install mysqli pdo gd" in result
        assert "pecl install redis" in result


class TestRenderHttpdBase:
    def test_httpd_config(self):
        result = render_httpd_base(modules=["md", "ssl", "proxy_fcgi"])
        assert "LoadModule md_module" in result
        assert "LoadModule ssl_module" in result
        assert "LoadModule proxy_fcgi_module" in result
        assert "IncludeOptional conf.d/domains/*.conf" in result

    def test_httpd_config_has_complete_directives(self):
        """httpd.conf should include User, Group, ServerAdmin, DirectoryIndex, ErrorLog."""
        result = render_httpd_base()
        assert "User www-data" in result
        assert "Group www-data" in result
        assert "ServerAdmin" in result
        assert "DirectoryIndex" in result
        assert "ErrorLog" in result
        assert "ServerTokens Prod" in result

    def test_httpd_base_uses_custom_modules(self):
        """Fix #7: render_httpd_base should use modules from WebService config."""
        custom = ["md", "proxy_fcgi", "proxy", "rewrite", "ssl", "socache_shmcb", "headers"]
        result = render_httpd_base(modules=custom)
        assert "LoadModule headers_module" in result

    def test_dockerfile_has_system_deps(self):
        """Fix #2: PHP Dockerfiles must install Alpine system deps for extensions."""
        result = render_php_dockerfile("8.2")
        assert "apk add" in result
        assert "libpng-dev" in result
        assert "icu-dev" in result
        assert "libzip-dev" in result
        assert "oniguruma-dev" in result

    def test_compose_apache_healthcheck_not_graceful(self):
        """Fix #15: Apache healthcheck must not send graceful restart signal."""
        services = {
            "web": {"image": "httpd:2.4-alpine"},
            "mariadb": {"image": "mariadb:lts", "root_password": "", "port": 3306, "enabled": True},
            "valkey": {"image": "valkey/valkey:8-alpine", "port": 6379, "enabled": True},
            "php": {"8.2": {"image": "nopanel/php-8.2:latest"}},
        }
        result = render_compose(
            services=services,
            network_mode="host",
            php_versions=["8.2"],
        )
        assert '"httpd", "-t"' in result
        assert "graceful" not in result
