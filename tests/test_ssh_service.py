from pathlib import Path
from types import SimpleNamespace

import paramiko
import pytest

from mcp_hwc.cloud_services.ssh_service import (
    SshService,
    SshServiceError,
    _prepare_known_hosts_file,
)


@pytest.fixture(autouse=True)
def _isolated_known_hosts(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_HWC_KNOWN_HOSTS", str(tmp_path / "auto_known_hosts"))


class FakeChannel:
    def __init__(self, exit_status: int):
        self._exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self._exit_status


class FakeStream:
    def __init__(self, payload: bytes, exit_status: int = 0):
        self._payload = payload
        self.channel = FakeChannel(exit_status)

    def read(self) -> bytes:
        return self._payload


class FakeSftpClient:
    def __init__(self):
        self.created_dirs: list[str] = []
        self.remote_files: dict[str, bytes] = {}

    def put(self, localpath: str, remotepath: str) -> None:
        self.remote_files[remotepath] = Path(localpath).read_bytes()

    def get(self, remotepath: str, localpath: str) -> None:
        Path(localpath).write_bytes(self.remote_files[remotepath])

    def stat(self, path: str):
        if path in self.remote_files:
            return SimpleNamespace(st_size=len(self.remote_files[path]))
        if path in self.created_dirs or path == "/":
            return SimpleNamespace(st_size=0)
        raise OSError(path)

    def mkdir(self, path: str) -> None:
        self.created_dirs.append(path)

    def close(self) -> None:
        return None


class FakeSshClient:
    def __init__(self, sftp_client: FakeSftpClient):
        self.connected_with: dict[str, object] | None = None
        self.sftp_client = sftp_client
        self.closed = False
        self.loaded_system_host_keys = False
        self.loaded_host_keys: str | None = None

    def load_system_host_keys(self) -> None:
        self.loaded_system_host_keys = True
        return None

    def load_host_keys(self, filename: str) -> None:
        self.loaded_host_keys = filename

    def set_missing_host_key_policy(self, policy) -> None:
        self.policy = policy

    def connect(self, *args, **kwargs) -> None:
        self.connected_with = kwargs

    def exec_command(self, *args, **kwargs):
        return (
            None,
            FakeStream(b"nginx installed\n", exit_status=0),
            FakeStream(b"", exit_status=0),
        )

    def open_sftp(self) -> FakeSftpClient:
        return self.sftp_client

    def close(self) -> None:
        self.closed = True


def test_execute_returns_stdout_and_exit_status() -> None:
    fake_sftp = FakeSftpClient()
    fake_client = FakeSshClient(fake_sftp)
    service = SshService(client_factory=lambda: fake_client)

    result = service.execute(
        host="10.0.0.10",
        username="root",
        command="apt-get install -y nginx",
    )

    assert result["exit_status"] == 0
    assert result["stdout"] == "nginx installed\n"
    assert result["stderr"] == ""
    assert fake_client.connected_with["hostname"] == "10.0.0.10"
    assert fake_client.loaded_system_host_keys is True


def test_upload_file_creates_remote_parent_directories(tmp_path: Path) -> None:
    source = tmp_path / "payload.txt"
    source.write_text("demo", encoding="utf-8")
    fake_sftp = FakeSftpClient()
    fake_client = FakeSshClient(fake_sftp)
    service = SshService(client_factory=lambda: fake_client)

    result = service.upload_file(
        host="10.0.0.10",
        username="root",
        local_path=str(source),
        remote_path="/etc/nginx/conf.d/payload.txt",
    )

    assert "/etc" in fake_sftp.created_dirs
    assert "/etc/nginx" in fake_sftp.created_dirs
    assert fake_sftp.remote_files["/etc/nginx/conf.d/payload.txt"] == b"demo"
    assert result["uploaded"] is True
    assert result["size_bytes"] == 4


def test_download_file_writes_local_output(tmp_path: Path) -> None:
    fake_sftp = FakeSftpClient()
    fake_sftp.remote_files["/var/log/nginx/access.log"] = b"logs"
    fake_client = FakeSshClient(fake_sftp)
    service = SshService(client_factory=lambda: fake_client)
    target = tmp_path / "downloads" / "access.log"

    result = service.download_file(
        host="10.0.0.10",
        username="root",
        remote_path="/var/log/nginx/access.log",
        local_path=str(target),
    )

    assert target.read_bytes() == b"logs"
    assert result["downloaded"] is True
    assert result["size_bytes"] == 4


def test_execute_loads_known_hosts_when_unknown_hosts_disallowed() -> None:
    fake_sftp = FakeSftpClient()
    fake_client = FakeSshClient(fake_sftp)
    service = SshService(client_factory=lambda: fake_client)

    service.execute(
        host="10.0.0.10",
        username="root",
        command="whoami",
        allow_unknown_host=False,
    )

    assert fake_client.loaded_system_host_keys is True


def _service_with_fake(monkeypatch, tmp_path):
    known_hosts = tmp_path / "state" / "known_hosts"
    monkeypatch.setenv("MCP_HWC_KNOWN_HOSTS", str(known_hosts))
    client = FakeSshClient(FakeSftpClient())
    return SshService(client_factory=lambda: client), client, known_hosts


def test_connect_loads_and_creates_private_known_hosts_file(monkeypatch, tmp_path) -> None:
    service, client, known_hosts = _service_with_fake(monkeypatch, tmp_path)

    for allow in (True, False):
        service._connect(
            host="203.0.113.10",
            username="root",
            port=22,
            password="pw",
            private_key_path=None,
            allow_unknown_host=allow,
            connect_timeout=5,
        )
        assert client.loaded_host_keys == str(known_hosts)
        assert client.loaded_system_host_keys is True

    assert known_hosts.exists()
    assert oct(known_hosts.stat().st_mode & 0o777) == "0o600"
    assert oct(known_hosts.parent.stat().st_mode & 0o777) == "0o700"


def test_autoadd_policy_persists_key_so_later_strict_connects_trust_it(tmp_path) -> None:
    path = tmp_path / "known_hosts"
    path.touch()
    key = paramiko.ECDSAKey.generate()

    first = paramiko.SSHClient()
    first.load_host_keys(str(path))
    first._transport = SimpleNamespace(_log=lambda *args: None)  # missing_host_key logs via it
    paramiko.AutoAddPolicy().missing_host_key(first, "203.0.113.10", key)

    stored = paramiko.HostKeys(str(path))
    assert stored.check("203.0.113.10", key)

    other_key = paramiko.ECDSAKey.generate()
    assert not stored.check("203.0.113.10", other_key)


@pytest.mark.parametrize("allow", [True, False])
def test_connect_rejects_changed_host_key_and_closes_client(monkeypatch, tmp_path, allow) -> None:
    service, client, _ = _service_with_fake(monkeypatch, tmp_path)

    def raise_bad_key(*args, **kwargs) -> None:
        raise paramiko.BadHostKeyException(
            "203.0.113.10", paramiko.ECDSAKey.generate(), paramiko.ECDSAKey.generate()
        )

    client.connect = raise_bad_key

    with pytest.raises(SshServiceError):
        service._connect(
            host="203.0.113.10",
            username="root",
            port=22,
            password="pw",
            private_key_path=None,
            allow_unknown_host=allow,
            connect_timeout=5,
        )
    assert client.closed is True


def test_prepare_known_hosts_override_tightens_file_but_not_parent(monkeypatch, tmp_path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    known_hosts = shared / "known_hosts"
    known_hosts.touch()
    known_hosts.chmod(0o644)
    monkeypatch.setenv("MCP_HWC_KNOWN_HOSTS", str(known_hosts))

    _prepare_known_hosts_file()

    assert oct(known_hosts.stat().st_mode & 0o777) == "0o600"
    assert oct(shared.stat().st_mode & 0o777) == "0o755"


def test_prepare_known_hosts_default_location_tightens_dir_and_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MCP_HWC_KNOWN_HOSTS", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    state = tmp_path / ".mcp-hwc"
    state.mkdir()
    state.chmod(0o755)
    known_hosts = state / "known_hosts"
    known_hosts.touch()
    known_hosts.chmod(0o644)

    assert _prepare_known_hosts_file() == str(known_hosts)

    assert oct(state.stat().st_mode & 0o777) == "0o700"
    assert oct(known_hosts.stat().st_mode & 0o777) == "0o600"
