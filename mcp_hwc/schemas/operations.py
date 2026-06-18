from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Dict, Any, List

class EcsCreateSchema(BaseModel):
    region: str = Field(..., description="The Huawei Cloud region code (e.g., 'cn-north-4').")
    name: Optional[str] = Field(None, description="The name of the ECS instance. Defaults to a timestamped name.")
    public_access: bool = Field(True, description="Whether to assign a public IP and EIP.")
    ssh_cidr: Optional[str] = Field(None, description="The CIDR block allowed for SSH access. Defaults to '0.0.0.0/0' if public_access is True.")
    admin_password: Optional[str] = Field(None, description="The administrator password for the ECS instance. Must meet complexity requirements (uppercase, lowercase, digit, special).")
    return_password: bool = Field(True, description="Whether to return the generated password in the response.")
    vpc_id: Optional[str] = Field(None, description="The ID of the VPC. If not provided, a default VPC will be picked or created automatically.")
    subnet_id: Optional[str] = Field(None, description="The ID of the subnet. If not provided, a default subnet will be picked or created automatically.")
    security_group_id: Optional[str] = Field(None, description="The ID of the security group. If not provided, a new one allowing SSH will be created.")
    image_id: Optional[str] = Field(None, description="The ID of the image to use. Takes precedence over image_hint.")
    image_hint: Optional[str] = Field("Ubuntu", description="A search hint for the image type (e.g., 'Ubuntu', 'CentOS', 'Windows') if image_id is not provided.")
    flavor_id: Optional[str] = Field(None, description="The ID of the ECS flavor (e.g., 's6.large.2'). Takes precedence over flavor_hint.")
    flavor_hint: Optional[str] = Field(None, description="A search hint for the flavor (e.g., '2vCPUs, 4GB').")
    availability_zone: Optional[str] = Field(None, description="The availability zone (e.g., 'cn-north-4a'). If not provided, one will be selected automatically.")
    root_volume_type: str = Field("GPSSD", description="The type of the root volume. Allowed values: 'SAS' (High I/O), 'SSD' (Ultra-high I/O), 'GPSSD' (General Purpose SSD).")
    root_volume_size_gb: int = Field(40, description="The size of the root volume in GB. Minimum 40GB.")
    bandwidth_size_mbit: int = Field(5, description="The bandwidth size in Mbit/s for public access. Only used if public_access is True.")
    wait: bool = Field(False, description="Whether to wait (up to 20 mins) for the ECS instance to be 'ACTIVE' and return IPs.")

class VpcQuerySchema(BaseModel):
    region: str = Field(..., description="The Huawei Cloud region code (e.g., 'cn-north-4').")
    vpc_id: Optional[str] = Field(None, description="Filter by a specific VPC ID.")
    name: Optional[str] = Field(None, description="Filter by VPC name (fuzzy match supported).")
    project_id: Optional[str] = Field(None, description="The project ID for the request.")

class GenericCallSchema(BaseModel):
    service_name: str = Field(..., description="The name of the Huawei Cloud service (e.g., 'ecs', 'vpc', 'evs', 'elb').")
    operation: str = Field(..., description="The name of the SDK operation (e.g., 'list_servers', 'create_volume').")
    parameters: Optional[Dict[str, Any]] = Field(None, description="The structured parameters for the operation as defined by the Huawei Cloud SDK.")
    region: Optional[str] = Field(None, description="The Huawei Cloud region code (e.g., 'ap-southeast-1').")

class ObsBucketSchema(BaseModel):
    bucket_name: str = Field(..., description="The name of the OBS bucket. Must be globally unique.")
    region: Optional[str] = Field(None, description="The Huawei Cloud region code where the bucket should reside.")

class K8sApplySchema(BaseModel):
    kubeconfig_path: str = Field(..., description="Local path to the kubeconfig file used for authentication.")
    manifest: Optional[str] = Field(None, description="Inline Kubernetes YAML manifest content to apply.")
    manifest_path: Optional[str] = Field(None, description="Local path to a Kubernetes manifest file to apply.")
    namespace: Optional[str] = Field(None, description="Kubernetes namespace to apply the manifest to.")
    context: Optional[str] = Field(None, description="Kubeconfig context name to use.")
    validate_manifest: bool = Field(True, description="Whether to validate the manifest before applying.")
    server_side: bool = Field(False, description="Whether to use server-side apply (recommended for large manifests).")
    execution_backend: str = Field("auto", description="Execution backend: 'auto' (preferred), 'local' (requires kubectl installed), or 'container' (requires Docker/Podman).")
    container_image: Optional[str] = Field(None, description="Custom container image for kubectl if using 'container' backend.")

    @model_validator(mode="after")
    def check_manifest_source(self) -> "K8sApplySchema":
        if bool(self.manifest) == bool(self.manifest_path):
            raise ValueError("Provide exactly one of 'manifest' or 'manifest_path'")
        return self

class K8sExecuteSchema(BaseModel):
    kubeconfig_path: str = Field(..., description="Local path to the kubeconfig file used for authentication.")
    command: str = Field(..., description="The arbitrary kubectl command to run (e.g., 'get pods', 'describe node').")
    namespace: Optional[str] = Field(None, description="Kubernetes namespace to run the command in.")
    context: Optional[str] = Field(None, description="Kubeconfig context name to use.")
    execution_backend: str = Field("auto", description="Execution backend: 'auto' (preferred), 'local' (requires kubectl installed), or 'container' (requires Docker/Podman).")
    container_image: Optional[str] = Field(None, description="Custom container image for kubectl if using 'container' backend.")
