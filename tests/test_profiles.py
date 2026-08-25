from pathlib import Path

import pytest

from mcp_hwc.core import profiles


@pytest.fixture()
def profile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import os

    (tmp_path / ".env").write_text("HWC_AK=AKDEFAULT123\nHWC_SK=skdefault\n")
    (tmp_path / ".env.work").write_text("HWC_AK=AKWORK456\nHWC_SK=skwork\nHWC_REGION=sa-brazil-1\n")
    (tmp_path / ".env.example").write_text("HWC_AK=\nHWC_SK=\n")
    (tmp_path / ".env.bak").write_text("HWC_AK=old\n")
    monkeypatch.setenv("MCP_HWC_ENV_FILE", str(tmp_path / ".env"))
    saved = {k: v for k, v in os.environ.items() if k.startswith("HWC_")}
    for key in saved:
        monkeypatch.delenv(key, raising=False)

    yield tmp_path

    # switch_profile mutates os.environ directly; restore the pre-test state
    # so fake credentials never leak into other tests.
    for key in [k for k in os.environ if k.startswith("HWC_")]:
        del os.environ[key]
    os.environ.update(saved)


def test_list_profiles_discovers_default_and_named(profile_dir: Path) -> None:
    result = profiles.list_profiles()

    names = {p["name"] for p in result["profiles"]}
    assert names == {"default", "work"}
    assert result["active"] == "default"
    active_flags = {p["name"]: p["active"] for p in result["profiles"]}
    assert active_flags["default"] is True
    assert active_flags["work"] is False


def test_switch_profile_applies_env_and_masks_secret(
    profile_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    result = profiles.switch_profile("work")

    assert result["profile"] == "work"
    assert os.environ["HWC_AK"] == "AKWORK456"
    assert os.environ["MCP_HWC_ENV_FILE"] == str(profile_dir / ".env.work")
    assert result["access_key"].startswith("AKWO")
    assert "skwork" not in str(result)
    assert result["region"] == "sa-brazil-1"


def test_switch_profile_clears_stale_hwc_env_keys(
    profile_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv("HWC_PROJECT_ID", "stale-project-from-old-account")

    profiles.switch_profile("work")

    assert "HWC_PROJECT_ID" not in os.environ


def test_switch_profile_makes_config_use_new_account(profile_dir: Path) -> None:
    from mcp_hwc.core.config import CloudApiConfig

    profiles.switch_profile("work")
    config = CloudApiConfig.from_env("ECS")

    assert config.access_key_id == "AKWORK456"
    assert config.secret_access_key == "skwork"

    profiles.switch_profile("default")
    config = CloudApiConfig.from_env("ECS")

    assert config.access_key_id == "AKDEFAULT123"


def test_switch_profile_unknown_lists_available(profile_dir: Path) -> None:
    with pytest.raises(ValueError, match="work"):
        profiles.switch_profile("nope")


def test_switch_profile_rejects_file_without_credentials(
    profile_dir: Path,
) -> None:
    (profile_dir / ".env.broken").write_text("HWC_REGION=sa-brazil-1\n")

    with pytest.raises(ValueError, match="HWC_AK"):
        profiles.switch_profile("broken")


def test_profile_tools_registered_in_mcp() -> None:
    from mcp_hwc.server import mcp

    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {"hwc_list_profiles", "hwc_switch_profile"}
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
