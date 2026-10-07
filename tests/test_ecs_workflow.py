from types import SimpleNamespace

import pytest

from mcp_hwc.workflows import ecs


class FakeEcsService:
    _config = SimpleNamespace(region="la-south-2")

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call_operation(self, operation: str, payload: dict | None = None) -> dict:
        self.calls.append((operation, payload or {}))
        return {"region": "la-south-2", "response": {"job_id": "job-1", "serverIds": ["srv-1"]}}


@pytest.fixture
def patched_ecs(monkeypatch):
    monkeypatch.setattr(ecs, "resolve_vpc_and_subnet", lambda *a, **k: ("vpc-1", "subnet-1", None))
    monkeypatch.setattr(ecs, "create_ecs_security_group", lambda *a, **k: "sg-1")
    monkeypatch.setattr(ecs, "resolve_ecs_image", lambda *a, **k: {"id": "img-1"})
    monkeypatch.setattr(ecs, "resolve_ecs_flavor", lambda *a, **k: ({"id": "flv-1"}, "az-1"))
    monkeypatch.setattr(ecs, "extract_server_ids_from_response", lambda r: ["srv-1"])
    service = FakeEcsService()
    return lambda **kwargs: ecs.create_ecs_vm(
        service_factory=lambda *a, **k: service, region="la-south-2", **kwargs
    )


def _credential_notes(result: dict) -> list[str]:
    return [s for s in result["next_steps"] if "reset_server_password" in s]


def test_discarded_generated_password_adds_recovery_next_step(patched_ecs) -> None:
    result = patched_ecs()

    notes = _credential_notes(result)
    assert len(notes) == 1
    assert "SSH login will not work" in notes[0]
    assert "huaweicloud_call_operation" in notes[0]
    assert "password" not in result["login"]


def test_supplied_password_has_no_recovery_next_step(patched_ecs) -> None:
    assert _credential_notes(patched_ecs(admin_password="Sup3r-Secret!")) == []


def test_returned_password_has_no_recovery_next_step(patched_ecs) -> None:
    result = patched_ecs(return_password=True)

    assert _credential_notes(result) == []
    assert result["login"]["password"]
