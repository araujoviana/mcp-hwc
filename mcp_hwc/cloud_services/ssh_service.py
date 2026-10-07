from __future__ import annotations

import os
import posixpath
import socket
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Protocol

import paramiko


class SshServiceError(RuntimeError):
    """Raised when SSH execution or file transfer fails."""


class _ReadableStream(Protocol):
    channel: Any

    def read(self) -> bytes: ...


class _SftpClient(Protocol):
    def put(self, localpath: str, remotepath: str) -> Any: ...

    def get(self, remotepath: str, localpath: str) -> Any: ...

    def stat(self, path: str) -> Any: ...

    def mkdir(self, path: str) -> Any: ...

    def close(self) -> None: ...


class _SshClient(Protocol):
    def load_system_host_keys(self) -> None: ...

    def load_host_keys(self, filename: str) -> None: ...

    def set_missing_host_key_policy(self, policy: Any) -> None: ...

    def connect(self, *args: Any, **kwargs: Any) -> None: ...

    def exec_command(
        self, *args: Any, **kwargs: Any
    ) -> tuple[Any, _ReadableStream, _ReadableStream]: ...

    def open_sftp(self) -> _SftpClient: ...

    def close(self) -> None: ...


SshClientFactory = Callable[[], _SshClient]


class SshService:
    def __init__(self, client_factory: SshClientFactory = paramiko.SSHClient):
        self._client_factory = client_factory

    def execute(
        self,
        host: str,
        username: str,
        command: str,
        port: int = 22,
        password: str | None = None,
        private_key_path: str | None = None,
        allow_unknown_host: bool = False,
        connect_timeout: int = 20,
        command_timeout: int = 300,
    ) -> dict[str, object]:
        client = self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key_path=private_key_path,
            allow_unknown_host=allow_unknown_host,
            connect_timeout=connect_timeout,
        )
        try:
            _, stdout, stderr = client.exec_command(command, timeout=command_timeout)
            stdout_text = stdout.read().decode("utf-8", errors="replace")
            stderr_text = stderr.read().decode("utf-8", errors="replace")
            exit_status = stdout.channel.recv_exit_status()
        except (socket.timeout, TimeoutError) as exc:
            raise SshServiceError(
                f"Timed out while executing SSH command on {username}@{host}:{port}"
            ) from exc
        except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
            raise SshServiceError(
                f"Failed to execute SSH command on {username}@{host}:{port}: {exc}"
            ) from exc
        finally:
            _close_quietly(client)

        return {
            "host": host,
            "port": port,
            "username": username,
            "command": command,
            "exit_status": exit_status,
            "stdout": stdout_text,
            "stderr": stderr_text,
        }

    def upload_file(
        self,
        host: str,
        username: str,
        local_path: str,
        remote_path: str,
        port: int = 22,
        password: str | None = None,
        private_key_path: str | None = None,
        allow_unknown_host: bool = False,
        connect_timeout: int = 20,
    ) -> dict[str, object]:
        resolved_local_path = _resolve_existing_local_path(local_path)
        client = self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key_path=private_key_path,
            allow_unknown_host=allow_unknown_host,
            connect_timeout=connect_timeout,
        )
        sftp = None
        try:
            sftp = client.open_sftp()
            self._ensure_remote_parent_directory(sftp, remote_path)
            sftp.put(str(resolved_local_path), remote_path)
            remote_stat = sftp.stat(remote_path)
        except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
            raise SshServiceError(
                f"Failed to upload file to {username}@{host}:{port}:{remote_path}: {exc}"
            ) from exc
        finally:
            _close_quietly(sftp)
            _close_quietly(client)

        return {
            "host": host,
            "port": port,
            "username": username,
            "local_path": str(resolved_local_path),
            "remote_path": remote_path,
            "size_bytes": getattr(remote_stat, "st_size", resolved_local_path.stat().st_size),
            "uploaded": True,
        }

    def download_file(
        self,
        host: str,
        username: str,
        remote_path: str,
        local_path: str,
        port: int = 22,
        password: str | None = None,
        private_key_path: str | None = None,
        allow_unknown_host: bool = False,
        connect_timeout: int = 20,
    ) -> dict[str, object]:
        resolved_local_path = _resolve_local_output_path(local_path)
        resolved_local_path.parent.mkdir(parents=True, exist_ok=True)
        temp_local_path = resolved_local_path.with_name(f"{resolved_local_path.name}.{uuid.uuid4().hex}.tmp")
        client = self._connect(
            host=host,
            username=username,
            port=port,
            password=password,
            private_key_path=private_key_path,
            allow_unknown_host=allow_unknown_host,
            connect_timeout=connect_timeout,
        )
        sftp = None
        try:
            sftp = client.open_sftp()
            sftp.get(remote_path, str(temp_local_path))
            os.replace(str(temp_local_path), str(resolved_local_path))
        except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
            if temp_local_path.exists():
                try:
                    temp_local_path.unlink()
                except OSError:
                    pass
            raise SshServiceError(
                f"Failed to download file from {username}@{host}:{port}:{remote_path}: {exc}"
            ) from exc
        finally:
            _close_quietly(sftp)
            _close_quietly(client)

        return {
            "host": host,
            "port": port,
            "username": username,
            "remote_path": remote_path,
            "local_path": str(resolved_local_path),
            "size_bytes": resolved_local_path.stat().st_size,
            "downloaded": True,
        }

    def _connect(
        self,
        *,
        host: str,
        username: str,
        port: int,
        password: str | None,
        private_key_path: str | None,
        allow_unknown_host: bool,
        connect_timeout: int,
    ) -> _SshClient:
        resolved_host = host.strip()
        resolved_username = username.strip()
        if not resolved_host:
            raise ValueError("host cannot be empty")
        if not resolved_username:
            raise ValueError("username cannot be empty")
        if port <= 0:
            raise ValueError("port must be greater than zero")
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be greater than zero")

        client = self._client_factory()
        try:
            # System keys catch a changed key for hosts the user already trusts.
            # The mcp-hwc file is bound to the client, so AutoAddPolicy persists
            # newly seen keys there (trust on first use); RejectPolicy never adds.
            _load_system_host_keys_safely(client)
            known_hosts_file = _prepare_known_hosts_file()
            try:
                client.load_host_keys(known_hosts_file)
            except paramiko.hostkeys.InvalidHostKey as exc:
                raise SshServiceError(
                    f"The mcp-hwc known_hosts file {known_hosts_file} contains an invalid "
                    f"entry ({exc}). Fix or delete that file and try again."
                ) from exc
            policy = paramiko.AutoAddPolicy() if allow_unknown_host else paramiko.RejectPolicy()
            client.set_missing_host_key_policy(policy)
            client.connect(
                hostname=resolved_host,
                port=port,
                username=resolved_username,
                password=password or None,
                key_filename=_resolve_private_key_path(private_key_path),
                timeout=connect_timeout,
                banner_timeout=connect_timeout,
                auth_timeout=connect_timeout,
                allow_agent=True,
                look_for_keys=True,
            )
        except SshServiceError:
            _close_quietly(client)
            raise
        except paramiko.BadHostKeyException as exc:
            _close_quietly(client)
            mcp_hwc_file = _known_hosts_path()
            raise SshServiceError(
                f"The host key for {resolved_host} does not match the stored key. This may be "
                "a man-in-the-middle attack, or the server was recreated or its IP address "
                "was reused. If you trust the new server, remove the old entry from the file "
                f"that holds it and retry: ssh-keygen -R {resolved_host} -f {mcp_hwc_file} "
                f"(mcp-hwc file) or ssh-keygen -R {resolved_host} -f ~/.ssh/known_hosts "
                f"(system file). Details: {exc}"
            ) from exc
        except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
            _close_quietly(client)
            raise SshServiceError(
                f"Failed to connect to {resolved_username}@{resolved_host}:{port}: {exc}"
            ) from exc

        return client

    def _ensure_remote_parent_directory(
        self,
        sftp: _SftpClient,
        remote_path: str,
    ) -> None:
        parent = str(PurePosixPath(remote_path).parent)
        if parent in {"", "."}:
            return

        current = "/" if parent.startswith("/") else ""
        for part in PurePosixPath(parent).parts:
            if part in {"", "/", "."}:
                continue
            current = posixpath.join(current, part) if current else part
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)


def _resolve_existing_local_path(local_path: str) -> Path:
    path = Path(local_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ValueError(f"Local file does not exist: {resolved}")
    return resolved


def _resolve_local_output_path(local_path: str) -> Path:
    path = Path(local_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _known_hosts_override() -> str | None:
    return os.environ.get("MCP_HWC_KNOWN_HOSTS") or None


def _known_hosts_path() -> Path:
    override = _known_hosts_override()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mcp-hwc" / "known_hosts"


def _load_system_host_keys_safely(client: Any, filename: str | None = None) -> None:
    # paramiko raises InvalidHostKey (not an SSHException) for @cert-authority,
    # @revoked and malformed lines in the user's ~/.ssh/known_hosts. Skip the
    # system keys rather than fail every connection; the mcp-hwc file is still
    # loaded afterwards and strict mode still uses RejectPolicy.
    try:
        if filename is None:
            client.load_system_host_keys()
        else:
            client.load_system_host_keys(filename)
    except (paramiko.hostkeys.InvalidHostKey, OSError):
        pass


def _prepare_known_hosts_file() -> str:
    path = _known_hosts_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.touch(mode=0o600, exist_ok=True)
    # Modes passed above only apply on creation; tighten pre-existing paths.
    # Only chmod the directory when it is our own default (~/.mcp-hwc); a
    # user-chosen override may live in a shared directory such as /tmp.
    if _known_hosts_override() is None:
        os.chmod(path.parent, 0o700)
    os.chmod(path, 0o600)
    return str(path)


def _resolve_private_key_path(private_key_path: str | None) -> str | None:
    if private_key_path is None:
        return None
    resolved = Path(private_key_path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ValueError(f"Private key file does not exist: {resolved}")
    return str(resolved)


def _close_quietly(resource: Any) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
