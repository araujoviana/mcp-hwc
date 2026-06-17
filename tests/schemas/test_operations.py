import pytest
from pydantic import ValidationError
from mcp_hwc.schemas.operations import EcsCreateSchema, ObsBucketSchema, K8sApplySchema

def test_ecs_create_schema_valid():
    data = {
        "region": "cn-north-4",
        "name": "test-vm",
        "public_access": True,
        "root_volume_size_gb": 40
    }
    schema = EcsCreateSchema(**data)
    assert schema.region == "cn-north-4"
    assert schema.name == "test-vm"

def test_ecs_create_schema_missing_region():
    with pytest.raises(ValidationError):
        EcsCreateSchema(name="test-vm")

def test_obs_bucket_schema_valid():
    data = {"bucket_name": "my-bucket", "region": "ap-southeast-1"}
    schema = ObsBucketSchema(**data)
    assert schema.bucket_name == "my-bucket"

def test_k8s_apply_schema_mutual_exclusion():
    with pytest.raises(ValidationError, match="Provide exactly one of 'manifest' or 'manifest_path'"):
        K8sApplySchema(kubeconfig_path="/path", manifest="kind: Pod", manifest_path="/path/manifest.yaml")

    with pytest.raises(ValidationError, match="Provide exactly one of 'manifest' or 'manifest_path'"):
        K8sApplySchema(kubeconfig_path="/path")

def test_k8s_apply_schema_valid():
    schema1 = K8sApplySchema(kubeconfig_path="/path/to/kube", manifest="kind: Pod")
    assert schema1.kubeconfig_path == "/path/to/kube"
    assert schema1.manifest == "kind: Pod"

    schema2 = K8sApplySchema(kubeconfig_path="/path/to/kube", manifest_path="/path/to/manifest")
    assert schema2.kubeconfig_path == "/path/to/kube"
    assert schema2.manifest_path == "/path/to/manifest"
