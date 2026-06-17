from pathlib import Path
from types import SimpleNamespace

from mcp_hwc.cloud_services.ssh_service import SshService


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

    def load_system_host_keys(self) -> None:
        self.loaded_system_host_keys = True
        return None

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
    assert fake_client.loaded_system_host_keys is False


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
