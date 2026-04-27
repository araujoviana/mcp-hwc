from types import SimpleNamespace

import pytest

from mcp_hwc.cli_service import CliService, CliServiceError, ContainerMount


def test_resolve_backend_prefers_local_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mcp_hwc.cli_service.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "kubectl" else None,
    )

    backend = CliService().resolve_backend("kubectl", backend="auto", container_image="demo")

    assert backend == "local"


def test_resolve_backend_falls_back_to_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mcp_hwc.cli_service.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )

    backend = CliService().resolve_backend("kubectl", backend="auto", container_image="demo")

    assert backend == "container"


def test_execute_container_builds_mount_command(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_file = tmp_path / "input.txt"
    source_file.write_text("demo", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "mcp_hwc.cli_service.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr("mcp_hwc.cli_service.subprocess.run", fake_run)

    result = CliService().execute_container(
        image="bitnami/kubectl:1.31.0",
        entrypoint="kubectl",
        args=["version"],
        mounts=[ContainerMount(source_file, "/tmp/input.txt", read_only=True)],
    )

    assert result["backend"] == "container"
    assert captured["command"][0] == "/usr/bin/docker"
    assert "-v" in captured["command"]
    assert any(item.endswith(":/tmp/input.txt:ro") for item in captured["command"])


def test_execute_local_raises_on_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcp_hwc.cli_service.shutil.which", lambda name: None)

    with pytest.raises(CliServiceError, match="Local CLI not found"):
        CliService().execute_local("helm", ["version"])
