from __future__ import annotations

import base64
import shutil
import subprocess
from urllib.parse import urlparse

from .errors import HelperToolError
from .sdk_service import HuaweiCloudSdkError, HuaweiCloudSdkService


def looks_like_existing_resource_error(message: str) -> bool:
    lowered = message.casefold()
    return any(
        token in lowered
        for token in ("already exists", "already exist", "duplicate", "conflict", "exist")
    )


def normalize_registry_host(registry: str) -> str:
    value = registry.strip().rstrip("/")
    if "://" in value:
        parsed = urlparse(value)
        value = parsed.netloc or parsed.path
    return value.rstrip("/")


def decode_swr_auth(auth_token: str) -> tuple[str, str]:
    try:
        decoded = base64.b64decode(auth_token).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise HelperToolError("SWR returned an invalid authorization token") from exc

    username, separator, password = decoded.partition(":")
    if not separator or not username or not password:
        raise HelperToolError("SWR authorization token did not contain username and password")
    return username, password


def resolve_container_cli(preferred_cli: str | None) -> str:
    candidates = [preferred_cli] if preferred_cli else ["docker", "podman", "nerdctl"]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    if preferred_cli:
        raise HelperToolError(f"Container CLI not found: {preferred_cli}")
    raise HelperToolError("No container CLI found. Install docker, podman, or nerdctl.")


def run_local_command(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        joined_command = " ".join(command)
        raise HelperToolError(f"Failed to execute local command '{joined_command}': {exc}") from exc

    if result.returncode != 0:
        joined_command = " ".join(command)
        stderr = result.stderr.strip() or result.stdout.strip()
        raise HelperToolError(f"Local command failed ({joined_command}): {stderr}")
    return result


def ensure_swr_namespace_and_repo(
    service: HuaweiCloudSdkService,
    *,
    namespace: str,
    repository: str,
    create_namespace: bool,
    create_repo: bool,
    repo_is_public: bool,
    repo_category: str,
    repo_description: str | None,
) -> None:
    if create_namespace:
        try:
            service.call_operation(
                "create_namespace",
                {"body": {"namespace": namespace}},
            )
        except HuaweiCloudSdkError as exc:
            if not looks_like_existing_resource_error(str(exc)):
                raise

    if create_repo:
        body: dict[str, object] = {
            "repository": repository,
            "is_public": repo_is_public,
            "category": repo_category,
        }
        if repo_description:
            body["description"] = repo_description
        try:
            service.call_operation(
                "create_repo",
                {
                    "namespace": namespace,
                    "body": body,
                },
            )
        except HuaweiCloudSdkError as exc:
            if not looks_like_existing_resource_error(str(exc)):
                raise


def upload_swr_image(
    service: HuaweiCloudSdkService,
    *,
    source_image: str,
    namespace: str,
    repository: str,
    tag: str = "latest",
    registry: str | None = None,
    container_cli: str | None = None,
    create_namespace: bool = True,
    create_repo: bool = True,
    repo_is_public: bool = False,
    repo_category: str = "other",
    repo_description: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    resolved_cli = resolve_container_cli(container_cli)

    ensure_swr_namespace_and_repo(
        service,
        namespace=namespace,
        repository=repository,
        create_namespace=create_namespace,
        create_repo=create_repo,
        repo_is_public=repo_is_public,
        repo_category=repo_category,
        repo_description=repo_description,
    )

    token_result = service.call_operation("create_authorization_token")
    token_response = token_result["response"]
    auths = token_response.get("auths") or {}
    if not isinstance(auths, dict) or not auths:
        raise HelperToolError("SWR did not return any registry authorization entries")

    requested_registry = registry.strip() if registry else next(iter(auths))
    registry_host = normalize_registry_host(requested_registry)
    auth_entry = None
    for auth_registry, value in auths.items():
        if normalize_registry_host(str(auth_registry)) == registry_host:
            auth_entry = value
            break
    if not isinstance(auth_entry, dict):
        raise HelperToolError(
            f"SWR did not return credentials for registry '{registry_host}'"
        )

    encoded_auth = auth_entry.get("auth")
    if not isinstance(encoded_auth, str) or not encoded_auth:
        raise HelperToolError("SWR authorization entry did not include a usable auth token")
    username, password = decode_swr_auth(encoded_auth)

    target_image = f"{registry_host}/{namespace}/{repository}:{tag}"
    login_result = run_local_command(
        [resolved_cli, "login", "--username", username, "--password-stdin", registry_host],
        input_text=password,
    )
    run_local_command([resolved_cli, "tag", source_image, target_image])
    push_result = run_local_command([resolved_cli, "push", target_image])

    return {
        "service": "swr",
        "operation": "upload_image",
        "region": region,
        "container_cli": resolved_cli,
        "registry": registry_host,
        "namespace": namespace,
        "repository": repository,
        "tag": tag,
        "source_image": source_image,
        "target_image": target_image,
        "authorization_expires_at": token_response.get("x_swr_expireat"),
        "login_stdout": login_result.stdout,
        "push_stdout": push_result.stdout,
        "pushed": True,
    }
