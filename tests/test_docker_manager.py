"""Tests for nopanel.docker_manager — Docker compose operations with mock runner."""

import json
from pathlib import Path

import pytest

from nopanel.docker_manager import CommandResult, DockerManager


class MockRunner:
    """Mock command runner for testing."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.calls: list[list[str]] = []

    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult:
        self.calls.append(args)
        return CommandResult(returncode=self._returncode, stdout=self._stdout, stderr=self._stderr)


@pytest.fixture
def docker_manager(tmp_path: Path) -> DockerManager:
    compose_file = tmp_path / "docker-compose.yml"
    return DockerManager(compose_file=compose_file, runner=MockRunner())


class TestDockerManager:
    def test_compose_up(self, docker_manager: DockerManager):
        docker_manager.compose_up(["apache"])
        runner = docker_manager.runner
        assert isinstance(runner, MockRunner)
        assert runner.calls[0][0] == "docker"
        assert runner.calls[0][1] == "compose"
        assert "up" in runner.calls[0]
        assert "-d" in runner.calls[0]
        assert "apache" in runner.calls[0]

    def test_compose_up_all(self, docker_manager: DockerManager):
        docker_manager.compose_up()
        runner = docker_manager.runner
        assert "apache" not in runner.calls[0]  # no service specified

    def test_compose_down(self, docker_manager: DockerManager):
        docker_manager.compose_down()
        runner = docker_manager.runner
        assert "down" in runner.calls[0]

    def test_compose_stop(self, docker_manager: DockerManager):
        docker_manager.compose_stop(["mariadb"])
        runner = docker_manager.runner
        assert "stop" in runner.calls[0]
        assert "mariadb" in runner.calls[0]

    def test_compose_restart(self, docker_manager: DockerManager):
        docker_manager.compose_restart(["apache"])
        runner = docker_manager.runner
        assert "restart" in runner.calls[0]
        assert "apache" in runner.calls[0]

    def test_compose_pull(self, docker_manager: DockerManager):
        docker_manager.compose_pull()
        runner = docker_manager.runner
        assert "pull" in runner.calls[0]

    def test_build_image(self, tmp_path: Path):
        runner = MockRunner()
        dm = DockerManager(compose_file=tmp_path / "compose.yml", runner=runner)
        dockerfile_dir = tmp_path / "php-8.2"
        dockerfile_dir.mkdir()
        dm.build_image(dockerfile_dir, "nopanel/php-8.2:latest")
        assert "build" in runner.calls[0]
        assert "nopanel/php-8.2:latest" in runner.calls[0]

    def test_get_container_status_running(self):
        runner = MockRunner(stdout=json.dumps([{"Service": "apache", "State": "running"}]))
        dm = DockerManager(runner=runner)
        status = dm.get_container_status("apache")
        assert status is not None
        assert status["State"] == "running"

    def test_get_container_status_not_found(self):
        runner = MockRunner(stdout=json.dumps([]))
        dm = DockerManager(runner=runner)
        status = dm.get_container_status("apache")
        assert status is None

    def test_is_service_running(self):
        runner = MockRunner(stdout=json.dumps([{"Service": "apache", "State": "running"}]))
        dm = DockerManager(runner=runner)
        assert dm.is_service_running("apache") is True
        assert dm.is_service_running("mariadb") is False

    def test_list_running_services(self):
        runner = MockRunner(
            stdout=json.dumps(
                [
                    {"Service": "apache", "State": "running"},
                    {"Service": "mariadb", "State": "running"},
                    {"Service": "valkey", "State": "exited"},
                ]
            )
        )
        dm = DockerManager(runner=runner)
        running = dm.list_running_services()
        assert "apache" in running
        assert "mariadb" in running
        assert "valkey" not in running

    def test_command_result_success(self):
        result = CommandResult(returncode=0, stdout="ok", stderr="")
        assert result.success

    def test_command_result_failure(self):
        result = CommandResult(returncode=1, stdout="", stderr="error")
        assert not result.success
