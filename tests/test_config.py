from pathlib import Path

import pytest

from mcp_hwc.config import CloudApiConfig, ConfigError, ObsConfig
from mcp_hwc.obs_endpoints import OBS_GLOBAL_SERVER, build_obs_server


@pytest.fixture(autouse=True)
def isolate_config_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MCP_HWC_ENV_FILE", str(tmp_path / ".missing.env"))
    for name in [
        "HWC_AK",
        "HWC_SK",
        "HWC_REGION",
        "HWC_PROJECT_ID",
        "HWC_OBS_REGION",
        "HWC_OBS_SERVER",
        "HWC_OBS_ACCESS_KEY_ID",
        "HWC_OBS_SECRET_ACCESS_KEY",
        "HWC_OBS_SECURITY_TOKEN",
        "HWC_ECS_REGION",
        "HWC_ECS_PROJECT_ID",
        "HWC_ECS_ENDPOINT",
        "HWC_RDS_REGION",
        "HWC_RDS_PROJECT_ID",
        "HWC_RDS_ENDPOINT",
        "HWC_SECURITY_TOKEN",
        "AccessKeyID",
        "SecretAccessKey",
        "SecurityToken",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_from_env_reads_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "HWC_AK=test-ak",
                "HWC_SK=test-sk",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("HWC_AK", raising=False)
    monkeypatch.delenv("HWC_SK", raising=False)

    config = ObsConfig.from_env(env_file=env_file)

    assert config.access_key_id == "test-ak"
    assert config.secret_access_key == "test-sk"
    assert config.discovery_server == OBS_GLOBAL_SERVER


def test_from_env_supports_huawei_sdk_variable_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AccessKeyID", "legacy-ak")
    monkeypatch.setenv("SecretAccessKey", "legacy-sk")

    config = ObsConfig.from_env()

    assert config.access_key_id == "legacy-ak"
    assert config.secret_access_key == "legacy-sk"
    assert config.discovery_server == OBS_GLOBAL_SERVER


def test_from_env_supports_optional_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.setenv("HWC_OBS_REGION", "AP-SOUTHEAST-1")

    config = ObsConfig.from_env()

    assert config.region == "ap-southeast-1"
    assert config.discovery_server == build_obs_server("ap-southeast-1")


def test_from_env_resolves_obs_region_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.setenv("HWC_OBS_REGION", "Santiago")

    config = ObsConfig.from_env()

    assert config.region == "la-south-2"
    assert config.discovery_server == build_obs_server("la-south-2")


def test_from_env_supports_optional_server_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.setenv("HWC_OBS_SERVER", "obs.cn-north-4.myhuaweicloud.com/")

    config = ObsConfig.from_env()

    assert config.server == "https://obs.cn-north-4.myhuaweicloud.com"
    assert config.discovery_server == "https://obs.cn-north-4.myhuaweicloud.com"


def test_from_env_raises_on_missing_required_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HWC_AK", raising=False)
    monkeypatch.delenv("HWC_SK", raising=False)
    monkeypatch.delenv("HWC_OBS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AccessKeyID", raising=False)
    monkeypatch.delenv("HWC_OBS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("SecretAccessKey", raising=False)

    with pytest.raises(ConfigError, match="Missing OBS configuration"):
        ObsConfig.from_env()


def test_cloud_api_config_reads_shared_region_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.setenv("HWC_REGION", "ap-southeast-1")
    monkeypatch.setenv("HWC_PROJECT_ID", "project-123")

    config = CloudApiConfig.from_env("ecs")

    assert config.access_key_id == "test-ak"
    assert config.secret_access_key == "test-sk"
    assert config.region == "ap-southeast-1"
    assert config.project_id == "project-123"
    assert config.endpoint is None


def test_cloud_api_config_allows_missing_region_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.delenv("HWC_REGION", raising=False)
    monkeypatch.delenv("HWC_PROJECT_ID", raising=False)
    monkeypatch.delenv("HWC_ECS_REGION", raising=False)
    monkeypatch.delenv("HWC_ECS_PROJECT_ID", raising=False)

    config = CloudApiConfig.from_env("ecs")

    assert config.region is None
    assert config.project_id is None


def test_cloud_api_config_resolves_region_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")

    config = CloudApiConfig.from_env("ecs", region="Santiago")

    assert config.region == "la-south-2"


def test_cloud_api_config_prefers_service_specific_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.setenv("HWC_REGION", "ap-southeast-1")
    monkeypatch.setenv("HWC_PROJECT_ID", "project-123")
    monkeypatch.setenv("HWC_RDS_REGION", "cn-north-4")
    monkeypatch.setenv("HWC_RDS_PROJECT_ID", "project-rds")
    monkeypatch.setenv("HWC_RDS_ENDPOINT", "rds.cn-north-4.myhuaweicloud.com/")

    config = CloudApiConfig.from_env("rds")

    assert config.region == "cn-north-4"
    assert config.project_id == "project-rds"
    assert config.endpoint == "https://rds.cn-north-4.myhuaweicloud.com"


def test_cloud_api_config_applies_runtime_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HWC_AK", "test-ak")
    monkeypatch.setenv("HWC_SK", "test-sk")
    monkeypatch.setenv("HWC_REGION", "ap-southeast-1")
    monkeypatch.delenv("HWC_PROJECT_ID", raising=False)

    config = CloudApiConfig.from_env(
        "ecs",
        region="cn-north-4",
        project_id="project-override",
        endpoint="ecs.cn-north-4.myhuaweicloud.com/",
    )

    assert config.region == "cn-north-4"
    assert config.project_id == "project-override"
    assert config.endpoint == "https://ecs.cn-north-4.myhuaweicloud.com"
