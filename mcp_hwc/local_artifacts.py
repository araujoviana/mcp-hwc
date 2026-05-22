from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import tempfile
import zipfile

from .cli_service import ContainerMount


def resolve_output_path(
    destination_path: str | None,
    *,
    prefix: str,
    suffix: str,
) -> Path:
    if destination_path is None:
        handle = tempfile.NamedTemporaryFile(delete=False, prefix=prefix, suffix=suffix)
        handle.close()
        return Path(handle.name)

    resolved_path = Path(destination_path).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def serialize_kubeconfig_document(response: dict[str, object]) -> str:
    kubeconfig = {
        "apiVersion": response.get("apiVersion") or response.get("api_version") or "v1",
        "kind": response.get("kind") or "Config",
        "preferences": response.get("preferences") or {},
        "clusters": response.get("clusters") or [],
        "users": response.get("users") or [],
        "contexts": response.get("contexts") or [],
        "current-context": response.get("current-context")
        or response.get("current_context")
        or "",
    }
    return json.dumps(kubeconfig, indent=2, ensure_ascii=True)


def format_cli_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    return str(value)


def prepare_helm_values_file(
    values: str | None,
    values_file: str | None,
) -> tuple[Path | None, bool]:
    if values and values_file:
        raise ValueError("Provide either values or values_file, not both")
    if values_file:
        return resolve_existing_path(values_file), False
    if values is None:
        return None, False

    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        prefix="mcp-hwc-helm-values-",
        suffix=".yaml",
        mode="w",
        encoding="utf-8",
    )
    with temp_file:
        temp_file.write(values)
    return Path(temp_file.name), True


def prepare_kubeconfig_for_backend(
    kubeconfig_path: str,
    *,
    context: str | None,
    backend: str,
) -> tuple[list[str], list[ContainerMount]]:
    resolved_path = resolve_existing_path(kubeconfig_path)
    if backend == "container":
        mounted_path = "/tmp/mcp-hwc-kubeconfig"
        args = ["--kubeconfig", mounted_path]
        mounts = [ContainerMount(resolved_path, mounted_path, read_only=True)]
    else:
        args = ["--kubeconfig", str(resolved_path)]
        mounts = []

    if context:
        args.extend(["--context", context])
    return args, mounts


def parse_json_output(stdout: str) -> object | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_psql_rows(stdout: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in stdout.splitlines():
        stripped = line.rstrip("\n")
        if not stripped:
            continue
        rows.append(stripped.split("\t"))
    return rows


def prepare_chart_reference(
    chart: str,
    *,
    backend: str,
) -> tuple[str, list[ContainerMount]]:
    candidate = Path(chart).expanduser()
    if not candidate.exists():
        return chart, []

    resolved_path = candidate.resolve()
    if backend == "container":
        mounted_path = "/tmp/mcp-hwc-chart"
        return mounted_path, [ContainerMount(resolved_path, mounted_path, read_only=True)]
    return str(resolved_path), []


def resolve_existing_path(path: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise ValueError(f"Path does not exist: {candidate}")
    return candidate


def package_functiongraph_source(source_path: str) -> dict[str, object]:
    resolved_path = resolve_existing_path(source_path)
    suffix = resolved_path.suffix.lower()

    if resolved_path.is_file() and suffix in {".zip", ".jar"}:
        archive_bytes = resolved_path.read_bytes()
        code_type = "jar" if suffix == ".jar" else "zip"
        code_filename = resolved_path.name
    else:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            if resolved_path.is_dir():
                written = False
                for child in sorted(resolved_path.rglob("*")):
                    if child.is_dir():
                        continue
                    archive.write(child, child.relative_to(resolved_path).as_posix())
                    written = True
                if not written:
                    raise ValueError(f"Directory is empty: {resolved_path}")
                code_filename = f"{resolved_path.name or 'function'}.zip"
            else:
                archive.write(resolved_path, resolved_path.name)
                code_filename = f"{resolved_path.stem or resolved_path.name}.zip"
        archive_bytes = archive_buffer.getvalue()
        code_type = "zip"

    return {
        "source_path": str(resolved_path),
        "code_type": code_type,
        "code_filename": code_filename,
        "func_code": {
            "file": base64.b64encode(archive_bytes).decode("ascii"),
        },
        "archive_size_bytes": len(archive_bytes),
    }
