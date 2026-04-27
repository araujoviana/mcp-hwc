from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Mapping, Sequence


class CliServiceError(RuntimeError):
    """Raised when a local or containerized CLI command cannot be executed."""


ExecutionBackend = str

DEFAULT_TOOL_IMAGES = {
    "kubectl": "bitnami/kubectl:1.31.0",
    "helm": "alpine/helm:3.16.4",
}


@dataclass(frozen=True)
class ContainerMount:
    source: str | Path
    target: str
    read_only: bool = True


class CliService:
    def resolve_backend(
        self,
        tool_name: str,
        *,
        backend: ExecutionBackend = "auto",
        container_image: str | None = None,
    ) -> ExecutionBackend:
        if backend not in {"auto", "local", "container"}:
            raise ValueError(
                "backend must be one of: auto, local, container"
            )

        if backend == "local":
            self.resolve_local_binary(tool_name)
            return "local"
        if backend == "container":
            if not container_image:
                raise ValueError("container_image is required when backend is container")
            self.resolve_container_runtime()
            return "container"

        if self._local_binary_exists(tool_name):
            return "local"
        if container_image and self._container_runtime_exists():
            return "container"

        raise CliServiceError(
            f"Could not run '{tool_name}'. Install it locally or provide a working container runtime for image '{container_image or DEFAULT_TOOL_IMAGES.get(tool_name, '<none>')}'."
        )

    def resolve_local_binary(self, tool_name: str) -> str:
        binary = shutil.which(tool_name)
        if binary:
            return binary
        raise CliServiceError(f"Local CLI not found: {tool_name}")

    def resolve_container_runtime(self) -> str:
        for runtime in ("docker", "podman", "nerdctl"):
            binary = shutil.which(runtime)
            if binary:
                return binary
        raise CliServiceError(
            "No container runtime found. Install docker, podman, or nerdctl."
        )

    def execute_local(
        self,
        tool_name: str,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        working_directory: str | Path | None = None,
    ) -> dict[str, object]:
        binary = self.resolve_local_binary(tool_name)
        command = [binary, *args]
        return self._run_subprocess(
            command,
            backend="local",
            env=env,
            input_text=input_text,
            working_directory=working_directory,
        )

    def execute_container(
        self,
        *,
        image: str,
        entrypoint: str,
        args: Sequence[str],
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        working_directory: str | Path | None = None,
        mounts: Sequence[ContainerMount] | None = None,
        network: str | None = None,
    ) -> dict[str, object]:
        runtime = self.resolve_container_runtime()
        command = [runtime, "run", "--rm", "-i", "--entrypoint", entrypoint]

        if network:
            command.extend(["--network", network])

        for key, value in (env or {}).items():
            command.extend(["-e", f"{key}={value}"])

        for mount in mounts or ():
            source = Path(mount.source).expanduser().resolve()
            if not source.exists():
                raise ValueError(f"Mount source does not exist: {source}")
            mode = "ro" if mount.read_only else "rw"
            command.extend(["-v", f"{source}:{mount.target}:{mode}"])

        if working_directory is not None:
            command.extend(["-w", str(working_directory)])

        command.append(image)
        command.extend(args)
        return self._run_subprocess(
            command,
            backend="container",
            env=None,
            input_text=input_text,
            working_directory=None,
        )

    def _run_subprocess(
        self,
        command: Sequence[str],
        *,
        backend: ExecutionBackend,
        env: Mapping[str, str] | None,
        input_text: str | None,
        working_directory: str | Path | None,
    ) -> dict[str, object]:
        cwd = None
        if working_directory is not None:
            cwd = str(Path(working_directory).expanduser().resolve())

        try:
            result = subprocess.run(
                list(command),
                input=input_text,
                text=True,
                capture_output=True,
                check=False,
                cwd=cwd,
                env=dict(env) if env else None,
            )
        except OSError as exc:
            joined_command = " ".join(command)
            raise CliServiceError(
                f"Failed to execute {backend} command '{joined_command}': {exc}"
            ) from exc

        if result.returncode != 0:
            joined_command = " ".join(command)
            stderr = result.stderr.strip() or result.stdout.strip()
            raise CliServiceError(
                f"{backend.capitalize()} command failed ({joined_command}): {stderr}"
            )

        return {
            "backend": backend,
            "command": list(command),
            "exit_status": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _local_binary_exists(self, tool_name: str) -> bool:
        return shutil.which(tool_name) is not None

    def _container_runtime_exists(self) -> bool:
        return any(shutil.which(runtime) for runtime in ("docker", "podman", "nerdctl"))
