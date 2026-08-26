import pytest
from pydantic import ValidationError

from mcp_hwc.schemas.operations import EcsCreateSchema


def test_ecs_create_schema_valid():
    data = {
        "region": "cn-north-4",
        "name": "test-vm",
        "public_access": True,
        "root_volume_size_gb": 40,
    }
    schema = EcsCreateSchema(**data)
    assert schema.region == "cn-north-4"
    assert schema.name == "test-vm"


def test_ecs_create_schema_missing_region():
    with pytest.raises(ValidationError):
        EcsCreateSchema(name="test-vm")
