from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib import import_module
import re
from typing import Any, Callable, Literal

from huaweicloudsdkcore.auth.credentials import BasicCredentials, GlobalCredentials
from huaweicloudsdkcore.exceptions import exceptions as sdk_exceptions
from huaweicloudsdkcore.region.region import Region
from huaweicloudsdkcore.utils.http_utils import sanitize_for_serialization

from mcp_hwc.core.config import CloudApiConfig

_PRIMITIVE_TYPES = {"str", "int", "float", "bool", "object"}
_PASSTHROUGH_TYPES = _PRIMITIVE_TYPES | {"none_type", "NoneType"}
_SERVICE_KEY_PATTERN = re.compile(r"[^a-z0-9]+")

CredentialScope = Literal["basic", "global"]

_OPERATION_CATEGORY_PREFIXES = {
    "create": ("create", "batch_create"),
    "read": ("list", "show", "get", "nova_show", "check"),
    "update": ("update", "batch_update", "modify", "change", "set"),
    "delete": ("delete", "batch_delete", "remove"),
    "attach": ("attach", "detach", "associate", "disassociate", "bind", "unbind"),
    "execute": (
        "run",
        "execute",
        "invoke",
        "import",
        "export",
        "install",
        "upgrade",
        "scale",
        "expand",
        "shrink",
        "start",
        "stop",
        "enable",
        "disable",
        "restart",
        "reboot",
    ),
}
_OPERATION_TOKEN_STOPWORDS = {
    "api",
    "all",
    "async",
    "batch",
    "by",
    "for",
    "from",
    "group",
    "groups",
    "id",
    "ids",
    "info",
    "instance",
    "instances",
    "job",
    "jobs",
    "list",
    "new",
    "of",
    "request",
    "response",
    "server",
    "servers",
    "show",
    "single",
    "to",
    "update",
    "with",
}


class HuaweiCloudSdkError(RuntimeError):
    """Raised when an SDK-backed service operation fails."""


@dataclass(frozen=True)
class ServiceVersionSpec:
    api_version: str
    client_module: str
    client_class_name: str
    region_module: str
    region_class_name: str
    model_package: str

    @property
    def client_class(self) -> type[Any]:
        return _import_attribute(self.client_module, self.client_class_name)

    @property
    def region_class(self) -> type[Any]:
        return _import_attribute(self.region_module, self.region_class_name)

    def endpoint_for_region(self, region: str) -> str:
        region_id = region.strip()
        resolved_region = self._try_region(region_id)
        endpoint = getattr(resolved_region, "endpoint", None)
        if isinstance(endpoint, str) and endpoint:
            return endpoint.rstrip("/")
        return _infer_endpoint_template(
            self.region_module,
            self.region_class_name,
        ).format(region=region_id)

    def region_for(self, region: str) -> Region:
        region_id = region.strip()
        resolved_region = self._try_region(region_id)
        if resolved_region is not None:
            return resolved_region
        return Region(region_id, self.endpoint_for_region(region_id))

    def _try_region(self, region: str) -> Region | None:
        try:
            return self.region_class.value_of(region)
        except KeyError:
            return None


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    display_name: str
    implementation_name: str
    sdk_package_root: str
    env_key: str
    credential_scope: CredentialScope
    default_api_version: str
    versions: dict[str, ServiceVersionSpec]
    aliases: tuple[str, ...] = ()
    provisioning_prerequisites: tuple[str, ...] = ()
    provisioning_notes: str | None = None

    def resolve(self, api_version: str | None = None) -> "ResolvedServiceSpec":
        resolved_api_version = (api_version or self.default_api_version).strip()
        if resolved_api_version not in self.versions:
            supported_versions = ", ".join(self.versions)
            raise ValueError(
                f"Unsupported API version '{resolved_api_version}' for {self.display_name}. "
                f"Supported versions: {supported_versions}"
            )
        return ResolvedServiceSpec(self, self.versions[resolved_api_version])


@dataclass(frozen=True)
class ResolvedServiceSpec:
    service_spec: ServiceSpec
    version_spec: ServiceVersionSpec

    @property
    def name(self) -> str:
        return self.service_spec.name

    @property
    def display_name(self) -> str:
        return self.service_spec.display_name

    @property
    def implementation_name(self) -> str:
        return self.service_spec.implementation_name

    @property
    def sdk_package_root(self) -> str:
        return self.service_spec.sdk_package_root

    @property
    def env_key(self) -> str:
        return self.service_spec.env_key

    @property
    def credential_scope(self) -> CredentialScope:
        return self.service_spec.credential_scope

    @property
    def api_version(self) -> str:
        return self.version_spec.api_version

    @property
    def available_api_versions(self) -> tuple[str, ...]:
        return tuple(self.service_spec.versions)

    @property
    def client_class(self) -> type[Any]:
        return self.version_spec.client_class

    @property
    def model_package(self) -> str:
        return self.version_spec.model_package

    @property
    def provisioning_prerequisites(self) -> tuple[str, ...]:
        return self.service_spec.provisioning_prerequisites

    @property
    def provisioning_notes(self) -> str | None:
        return self.service_spec.provisioning_notes

    def endpoint_for_region(self, region: str) -> str:
        return self.version_spec.endpoint_for_region(region)

    def region_for(self, region: str) -> Region:
        return self.version_spec.region_for(region)


def _service_version(
    sdk_package_root: str,
    api_version: str,
    client_class_name: str,
    region_module_name: str,
    region_class_name: str,
) -> ServiceVersionSpec:
    return ServiceVersionSpec(
        api_version=api_version,
        client_module=f"{sdk_package_root}.{api_version}",
        client_class_name=client_class_name,
        region_module=f"{sdk_package_root}.{api_version}.region.{region_module_name}",
        region_class_name=region_class_name,
        model_package=f"{sdk_package_root}.{api_version}.model",
    )


_ECS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkecs",
        "v2",
        "EcsClient",
        "ecs_region",
        "EcsRegion",
    ),
}
_IMS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkims",
        "v2",
        "ImsClient",
        "ims_region",
        "ImsRegion",
    ),
}
_RDS_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkrds",
        "v3",
        "RdsClient",
        "rds_region",
        "RdsRegion",
    ),
}
_VPC_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkvpc",
        "v2",
        "VpcClient",
        "vpc_region",
        "VpcRegion",
    ),
}
_CCE_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkcce",
        "v3",
        "CceClient",
        "cce_region",
        "CceRegion",
    ),
    "v5": _service_version(
        "huaweicloudsdkcce",
        "v5",
        "CceClient",
        "cce_region",
        "CceRegion",
    ),
}
_MRS_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkmrs",
        "v1",
        "MrsClient",
        "mrs_region",
        "MrsRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkmrs",
        "v2",
        "MrsClient",
        "mrs_region",
        "MrsRegion",
    ),
}
_GAUSSDB_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkgaussdb",
        "v3",
        "GaussDBClient",
        "gaussdb_region",
        "GaussDBRegion",
    ),
}
_GAUSSDB_NOSQL_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkgaussdbfornosql",
        "v3",
        "GaussDBforNoSQLClient",
        "gaussdbfornosql_region",
        "GaussDBforNoSQLRegion",
    ),
}
_GAUSSDB_OPENGAUSS_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkgaussdbforopengauss",
        "v3",
        "GaussDBforopenGaussClient",
        "gaussdbforopengauss_region",
        "GaussDBforopenGaussRegion",
    ),
}
_MASTUDIO_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkmastudio",
        "v1",
        "MaStudioClient",
        "mastudio_region",
        "MaStudioRegion",
    ),
}
_METASTUDIO_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkmetastudio",
        "v1",
        "MetaStudioClient",
        "metastudio_region",
        "MetaStudioRegion",
    ),
}
_KMS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkkms",
        "v2",
        "KmsClient",
        "kms_region",
        "KmsRegion",
    ),
}
_IAM_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkiam",
        "v3",
        "IamClient",
        "iam_region",
        "IamRegion",
    ),
    "v5": _service_version(
        "huaweicloudsdkiam",
        "v5",
        "IamClient",
        "iam_region",
        "IamRegion",
    ),
}
_SECMASTER_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdksecmaster",
        "v1",
        "SecMasterClient",
        "secmaster_region",
        "SecMasterRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdksecmaster",
        "v2",
        "SecMasterClient",
        "secmaster_region",
        "SecMasterRegion",
    ),
}
_EVS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkevs",
        "v2",
        "EvsClient",
        "evs_region",
        "EvsRegion",
    ),
}
_SFSTURBO_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdksfsturbo",
        "v1",
        "SFSTurboClient",
        "sfsturbo_region",
        "SFSTurboRegion",
    ),
}
_ELB_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkelb",
        "v2",
        "ElbClient",
        "elb_region",
        "ElbRegion",
    ),
    "v3": _service_version(
        "huaweicloudsdkelb",
        "v3",
        "ElbClient",
        "elb_region",
        "ElbRegion",
    ),
}
_EIP_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkeip",
        "v2",
        "EipClient",
        "eip_region",
        "EipRegion",
    ),
    "v3": _service_version(
        "huaweicloudsdkeip",
        "v3",
        "EipClient",
        "eip_region",
        "EipRegion",
    ),
}
_AS_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkas",
        "v1",
        "AsClient",
        "as_region",
        "AsRegion",
    ),
}
_CBR_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkcbr",
        "v1",
        "CbrClient",
        "cbr_region",
        "CbrRegion",
    ),
}
_DDS_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkdds",
        "v3",
        "DdsClient",
        "dds_region",
        "DdsRegion",
    ),
}
_DCS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkdcs",
        "v2",
        "DcsClient",
        "dcs_region",
        "DcsRegion",
    ),
}
_DMS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkdms",
        "v2",
        "DmsClient",
        "dms_region",
        "DmsRegion",
    ),
}
_ASM_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkasm",
        "v1",
        "AsmClient",
        "asm_region",
        "AsmRegion",
    ),
}
_NAT_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdknat",
        "v2",
        "NatClient",
        "nat_region",
        "NatRegion",
    ),
}
_DNS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkdns",
        "v2",
        "DnsClient",
        "dns_region",
        "DnsRegion",
    ),
}
_ER_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdker",
        "v3",
        "ErClient",
        "er_region",
        "ErRegion",
    ),
}
_VPN_VERSIONS = {
    "v5": _service_version(
        "huaweicloudsdkvpn",
        "v5",
        "VpnClient",
        "vpn_region",
        "VpnRegion",
    ),
}
_DC_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkdc",
        "v3",
        "DcClient",
        "dc_region",
        "DcRegion",
    ),
}
_GEIP_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkgeip",
        "v3",
        "GeipClient",
        "geip_region",
        "GeipRegion",
    ),
}
_GA_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkga",
        "v1",
        "GaClient",
        "ga_region",
        "GaRegion",
    ),
}
_SWR_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkswr",
        "v2",
        "SwrClient",
        "swr_region",
        "SwrRegion",
    ),
}
_UCS_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkucs",
        "v1",
        "UcsClient",
        "ucs_region",
        "UcsRegion",
    ),
}
_VPCEP_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkvpcep",
        "v1",
        "VpcepClient",
        "vpcep_region",
        "VpcepRegion",
    ),
}
_CC_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkcc",
        "v2",
        "CcClient",
        "cc_region",
        "CcRegion",
    ),
    "v3": _service_version(
        "huaweicloudsdkcc",
        "v3",
        "CcClient",
        "cc_region",
        "CcRegion",
    ),
}
_KAFKA_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkkafka",
        "v2",
        "KafkaClient",
        "kafka_region",
        "KafkaRegion",
    ),
}
_RABBITMQ_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkrabbitmq",
        "v2",
        "RabbitMQClient",
        "rabbitmq_region",
        "RabbitMQRegion",
    ),
}
_ROCKETMQ_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkrocketmq",
        "v2",
        "RocketMQClient",
        "rocketmq_region",
        "RocketMQRegion",
    ),
}
_DWS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkdws",
        "v2",
        "DwsClient",
        "dws_region",
        "DwsRegion",
    ),
}
_CLOUDTABLE_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkcloudtable",
        "v2",
        "CloudTableClient",
        "cloudtable_region",
        "CloudTableRegion",
    ),
}
_APM_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkapm",
        "v1",
        "ApmClient",
        "apm_region",
        "ApmRegion",
    ),
}
_AOM_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkaom",
        "v1",
        "AomClient",
        "aom_region",
        "AomRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkaom",
        "v2",
        "AomClient",
        "aom_region",
        "AomRegion",
    ),
    "v3": _service_version(
        "huaweicloudsdkaom",
        "v3",
        "AomClient",
        "aom_region",
        "AomRegion",
    ),
    "v4": _service_version(
        "huaweicloudsdkaom",
        "v4",
        "AomClient",
        "aom_region",
        "AomRegion",
    ),
}
_WORKSPACE_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkworkspace",
        "v2",
        "WorkspaceClient",
        "workspace_region",
        "WorkspaceRegion",
    ),
}
_WORKSPACEAPP_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkworkspaceapp",
        "v1",
        "WorkspaceAppClient",
        "workspaceapp_region",
        "WorkspaceAppRegion",
    ),
}
_FUNCTIONGRAPH_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkfunctiongraph",
        "v2",
        "FunctionGraphClient",
        "functiongraph_region",
        "FunctionGraphRegion",
    ),
}
_CAE_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkcae",
        "v1",
        "CaeClient",
        "cae_region",
        "CaeRegion",
    ),
}
_CDN_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkcdn",
        "v1",
        "CdnClient",
        "cdn_region",
        "CdnRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkcdn",
        "v2",
        "CdnClient",
        "cdn_region",
        "CdnRegion",
    ),
}
_DAS_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkdas",
        "v3",
        "DasClient",
        "das_region",
        "DasRegion",
    ),
}
_DRS_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkdrs",
        "v3",
        "DrsClient",
        "drs_region",
        "DrsRegion",
    ),
    "v5": _service_version(
        "huaweicloudsdkdrs",
        "v5",
        "DrsClient",
        "drs_region",
        "DrsRegion",
    ),
}
_UGO_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkugo",
        "v1",
        "UgoClient",
        "ugo_region",
        "UgoRegion",
    ),
}
_DDM_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkddm",
        "v1",
        "DdmClient",
        "ddm_region",
        "DdmRegion",
    ),
}
_OCR_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkocr",
        "v1",
        "OcrClient",
        "ocr_region",
        "OcrRegion",
    ),
}
_CSS_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkcss",
        "v1",
        "CssClient",
        "css_region",
        "CssRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkcss",
        "v2",
        "CssClient",
        "css_region",
        "CssRegion",
    ),
}
_LTS_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdklts",
        "v2",
        "LtsClient",
        "lts_region",
        "LtsRegion",
    ),
}
_CES_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkces",
        "v1",
        "CesClient",
        "ces_region",
        "CesRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkces",
        "v2",
        "CesClient",
        "ces_region",
        "CesRegion",
    ),
    "v3": _service_version(
        "huaweicloudsdkces",
        "v3",
        "CesClient",
        "ces_region",
        "CesRegion",
    ),
}
_CTS_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkcts",
        "v3",
        "CtsClient",
        "cts_region",
        "CtsRegion",
    ),
}
_ORGANIZATIONS_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkorganizations",
        "v1",
        "OrganizationsClient",
        "organizations_region",
        "OrganizationsRegion",
    ),
}
_SMN_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdksmn",
        "v2",
        "SmnClient",
        "smn_region",
        "SmnRegion",
    ),
}
_CONFIG_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkconfig",
        "v1",
        "ConfigClient",
        "config_region",
        "ConfigRegion",
    ),
}
_APIG_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkapig",
        "v2",
        "ApigClient",
        "apig_region",
        "ApigRegion",
    ),
}
_ESW_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkesw",
        "v3",
        "EswClient",
        "esw_region",
        "EswRegion",
    ),
}
_CFW_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkcfw",
        "v1",
        "CfwClient",
        "cfw_region",
        "CfwRegion",
    ),
}
_WAF_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkwaf",
        "v1",
        "WafClient",
        "waf_region",
        "WafRegion",
    ),
}
_AAD_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkaad",
        "v1",
        "AadClient",
        "aad_region",
        "AadRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkaad",
        "v2",
        "AadClient",
        "aad_region",
        "AadRegion",
    ),
}
_ANTIDDOS_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkantiddos",
        "v1",
        "AntiDDoSClient",
        "antiddos_region",
        "AntiDDoSRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkantiddos",
        "v2",
        "AntiDDoSClient",
        "antiddos_region",
        "AntiDDoSRegion",
    ),
}
_CGS_VERSIONS = {
    "v5": _service_version(
        "huaweicloudsdkcgs",
        "v5",
        "CgsClient",
        "cgs_region",
        "CgsRegion",
    ),
}
_CBH_VERSIONS = {
    "v1": _service_version(
        "huaweicloudsdkcbh",
        "v1",
        "CbhClient",
        "cbh_region",
        "CbhRegion",
    ),
    "v2": _service_version(
        "huaweicloudsdkcbh",
        "v2",
        "CbhClient",
        "cbh_region",
        "CbhRegion",
    ),
}
_CODEARTS_ARTIFACT_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkcodeartsartifact",
        "v2",
        "CodeArtsArtifactClient",
        "codeartsartifact_region",
        "CodeArtsArtifactRegion",
    ),
}
_CODEARTS_BUILD_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkcodeartsbuild",
        "v3",
        "CodeArtsBuildClient",
        "codeartsbuild_region",
        "CodeArtsBuildRegion",
    ),
}
_CODEARTS_CHECK_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkcodeartscheck",
        "v2",
        "CodeArtsCheckClient",
        "codeartscheck_region",
        "CodeArtsCheckRegion",
    ),
}
_CODEARTS_DEPLOY_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkcodeartsdeploy",
        "v2",
        "CodeArtsDeployClient",
        "codeartsdeploy_region",
        "CodeArtsDeployRegion",
    ),
}
_CODEARTS_PIPELINE_VERSIONS = {
    "v2": _service_version(
        "huaweicloudsdkcodeartspipeline",
        "v2",
        "CodeArtsPipelineClient",
        "codeartspipeline_region",
        "CodeArtsPipelineRegion",
    ),
}
_CODEARTS_REPO_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkcodeartsrepo",
        "v3",
        "CodeArtsRepoClient",
        "codeartsrepo_region",
        "CodeArtsRepoRegion",
    ),
    "v4": _service_version(
        "huaweicloudsdkcodeartsrepo",
        "v4",
        "CodeArtsRepoClient",
        "codeartsrepo_region",
        "CodeArtsRepoRegion",
    ),
}
_CODEHUB_VERSIONS = {
    "v3": _service_version(
        "huaweicloudsdkcodehub",
        "v3",
        "CodeHubClient",
        "codehub_region",
        "CodeHubRegion",
    ),
    "v4": _service_version(
        "huaweicloudsdkcodehub",
        "v4",
        "CodeHubClient",
        "codehub_region",
        "CodeHubRegion",
    ),
}

SERVICE_SPECS = {
    "ecs": ServiceSpec(
        name="ecs",
        display_name="Elastic Cloud Server (ECS)",
        implementation_name="ecs",
        sdk_package_root="huaweicloudsdkecs",
        env_key="ECS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_ECS_VERSIONS,
        aliases=("elastic_cloud_server", "elastic_compute_service"),
        provisioning_prerequisites=("vpc", "ims"),
        provisioning_notes=(
            "Create or reuse VPC, subnet, security group, image, and optional "
            "EIP or EVS volumes automatically."
        ),
    ),
    "rds": ServiceSpec(
        name="rds",
        display_name="Relational Database Service (RDS)",
        implementation_name="rds",
        sdk_package_root="huaweicloudsdkrds",
        env_key="RDS",
        credential_scope="basic",
        default_api_version="v3",
        versions=_RDS_VERSIONS,
        aliases=("relational_database_service",),
        provisioning_prerequisites=("vpc", "kms", "cbr"),
        provisioning_notes=(
            "Create networking, security groups, backups, and optional KMS or "
            "public-access resources without waiting for extra user input."
        ),
    ),
    "vpc": ServiceSpec(
        name="vpc",
        display_name="Virtual Private Cloud (VPC)",
        implementation_name="vpc",
        sdk_package_root="huaweicloudsdkvpc",
        env_key="VPC",
        credential_scope="basic",
        default_api_version="v2",
        versions=_VPC_VERSIONS,
        aliases=("virtual_private_cloud",),
        provisioning_prerequisites=(),
        provisioning_notes="Use this to create or discover VPCs, subnets, routes, and security groups for higher-level services.",
    ),
    "ims": ServiceSpec(
        name="ims",
        display_name="Image Management Service (IMS)",
        implementation_name="ims",
        sdk_package_root="huaweicloudsdkims",
        env_key="IMS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_IMS_VERSIONS,
        aliases=("image_management_service",),
        provisioning_prerequisites=(),
        provisioning_notes="Use this for image discovery, import, export, and image lifecycle management during ECS provisioning.",
    ),
    "cce": ServiceSpec(
        name="cce",
        display_name="Cloud Container Engine (CCE)",
        implementation_name="cce",
        sdk_package_root="huaweicloudsdkcce",
        env_key="CCE",
        credential_scope="basic",
        default_api_version="v3",
        versions=_CCE_VERSIONS,
        aliases=("cloud_container_engine", "cluster", "kubernetes"),
        provisioning_prerequisites=("vpc", "elb", "eip", "evs"),
        provisioning_notes=(
            "Provision clusters, node pools, add-ons, networking, and public "
            "access end-to-end with a minimal question count."
        ),
    ),
    "mrs": ServiceSpec(
        name="mrs",
        display_name="MapReduce Service (MRS)",
        implementation_name="mrs",
        sdk_package_root="huaweicloudsdkmrs",
        env_key="MRS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_MRS_VERSIONS,
        aliases=("mapreduce_service",),
        provisioning_prerequisites=("vpc", "eip", "evs"),
        provisioning_notes=(
            "Provision clusters, node groups, jobs, and supporting networking "
            "with sane defaults unless the user specifies a topology."
        ),
    ),
    "gaussdb": ServiceSpec(
        name="gaussdb",
        display_name="GaussDB",
        implementation_name="gaussdb",
        sdk_package_root="huaweicloudsdkgaussdb",
        env_key="GAUSSDB",
        credential_scope="basic",
        default_api_version="v3",
        versions=_GAUSSDB_VERSIONS,
        aliases=("gauss_db",),
        provisioning_prerequisites=("vpc", "kms", "cbr"),
        provisioning_notes=(
            "Provision instances, networking, backups, access rules, and scaling "
            "resources automatically when the user asks for a database."
        ),
    ),
    "taurusdb": ServiceSpec(
        name="taurusdb",
        display_name="TaurusDB",
        implementation_name="gaussdb",
        sdk_package_root="huaweicloudsdkgaussdb",
        env_key="GAUSSDB",
        credential_scope="basic",
        default_api_version="v3",
        versions=_GAUSSDB_VERSIONS,
        aliases=("taurus", "gaussdb_mysql"),
        provisioning_prerequisites=("vpc", "kms", "cbr"),
        provisioning_notes=(
            "Backed by the GaussDB SDK surface used for TaurusDB-compatible "
            "managed database workflows."
        ),
    ),
    "gaussdb_nosql": ServiceSpec(
        name="gaussdb_nosql",
        display_name="GaussDB(for NoSQL)",
        implementation_name="gaussdbfornosql",
        sdk_package_root="huaweicloudsdkgaussdbfornosql",
        env_key="GAUSSDBFORNOSQL",
        credential_scope="basic",
        default_api_version="v3",
        versions=_GAUSSDB_NOSQL_VERSIONS,
        aliases=("gaussdbfornosql", "nosql", "geminidb"),
        provisioning_prerequisites=("vpc", "kms", "cbr"),
        provisioning_notes=(
            "Extended NoSQL instance lifecycle and management surface beyond the "
            "requested baseline, and the closest published SDK-backed surface when "
            "users ask for GeminiDB-style NoSQL workflows."
        ),
    ),
    "gaussdb_opengauss": ServiceSpec(
        name="gaussdb_opengauss",
        display_name="GaussDB(for openGauss)",
        implementation_name="gaussdbforopengauss",
        sdk_package_root="huaweicloudsdkgaussdbforopengauss",
        env_key="GAUSSDBFOROPENGAUSS",
        credential_scope="basic",
        default_api_version="v3",
        versions=_GAUSSDB_OPENGAUSS_VERSIONS,
        aliases=("gaussdbforopengauss", "opengauss"),
        provisioning_prerequisites=("vpc", "kms", "cbr"),
        provisioning_notes="Extended openGauss management surface beyond the requested baseline.",
    ),
    "modelarts_studio": ServiceSpec(
        name="modelarts_studio",
        display_name="ModelArts Studio",
        implementation_name="mastudio",
        sdk_package_root="huaweicloudsdkmastudio",
        env_key="MASTUDIO",
        credential_scope="basic",
        default_api_version="v1",
        versions=_MASTUDIO_VERSIONS,
        aliases=("modelartsstudio", "ma_studio", "mastudio"),
        provisioning_prerequisites=(),
        provisioning_notes=(
            "Use this surface for chat and text-completion style ModelArts Studio "
            "workflows without requiring extra configuration questions."
        ),
    ),
    "maas": ServiceSpec(
        name="maas",
        display_name="MaaS",
        implementation_name="mastudio",
        sdk_package_root="huaweicloudsdkmastudio",
        env_key="MASTUDIO",
        credential_scope="basic",
        default_api_version="v1",
        versions=_MASTUDIO_VERSIONS,
        aliases=("model_as_a_service",),
        provisioning_prerequisites=(),
        provisioning_notes="Shares the MaStudio SDK surface for managed chat and text completion workflows.",
    ),
    "metastudio": ServiceSpec(
        name="metastudio",
        display_name="MetaStudio",
        implementation_name="metastudio",
        sdk_package_root="huaweicloudsdkmetastudio",
        env_key="METASTUDIO",
        credential_scope="basic",
        default_api_version="v1",
        versions=_METASTUDIO_VERSIONS,
        aliases=("meta_studio",),
        provisioning_prerequisites=(),
        provisioning_notes="Extended digital-human and media-generation management surface beyond the requested baseline.",
    ),
    "kms": ServiceSpec(
        name="kms",
        display_name="DEW Key Management Service (KMS)",
        implementation_name="kms",
        sdk_package_root="huaweicloudsdkkms",
        env_key="KMS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_KMS_VERSIONS,
        aliases=("dew", "dew_kms", "key_management_service"),
        provisioning_prerequisites=(),
        provisioning_notes="Use this for key, alias, and encryption lifecycle management that supports database and storage provisioning.",
    ),
    "iam": ServiceSpec(
        name="iam",
        display_name="Identity and Access Management (IAM)",
        implementation_name="iam",
        sdk_package_root="huaweicloudsdkiam",
        env_key="IAM",
        credential_scope="global",
        default_api_version="v3",
        versions=_IAM_VERSIONS,
        aliases=("identity_and_access_management",),
        provisioning_prerequisites=(),
        provisioning_notes=(
            "Global IAM flows can use `domain_id` when automatic discovery is not "
            "enough, but prefer zero-extra-input region-based resolution first."
        ),
    ),
    "secmaster": ServiceSpec(
        name="secmaster",
        display_name="SecMaster",
        implementation_name="secmaster",
        sdk_package_root="huaweicloudsdksecmaster",
        env_key="SECMASTER",
        credential_scope="basic",
        default_api_version="v1",
        versions=_SECMASTER_VERSIONS,
        aliases=("sec_master",),
        provisioning_prerequisites=(),
        provisioning_notes="Full incident, threat, workspace, and automation management surface through the published SDK.",
    ),
    "evs": ServiceSpec(
        name="evs",
        display_name="Elastic Volume Service (EVS)",
        implementation_name="evs",
        sdk_package_root="huaweicloudsdkevs",
        env_key="EVS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_EVS_VERSIONS,
        aliases=("elastic_volume_service",),
        provisioning_prerequisites=(),
        provisioning_notes="Create and attach disks as part of ECS, CCE, or MRS provisioning without extra user prompting.",
    ),
    "sfs": ServiceSpec(
        name="sfs",
        display_name="Scalable File Service (SFS)",
        implementation_name="sfsturbo",
        sdk_package_root="huaweicloudsdksfsturbo",
        env_key="SFSTURBO",
        credential_scope="basic",
        default_api_version="v1",
        versions=_SFSTURBO_VERSIONS,
        aliases=("sfs_turbo", "sfsturbo"),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Backed by the SFS Turbo SDK surface for share lifecycle, quotas, and access-rule management.",
    ),
    "elb": ServiceSpec(
        name="elb",
        display_name="Elastic Load Balance (ELB)",
        implementation_name="elb",
        sdk_package_root="huaweicloudsdkelb",
        env_key="ELB",
        credential_scope="basic",
        default_api_version="v3",
        versions=_ELB_VERSIONS,
        aliases=("elastic_load_balance",),
        provisioning_prerequisites=("vpc", "eip"),
        provisioning_notes="Provision load balancers, listeners, pools, members, and certificates as part of end-to-end service setup.",
    ),
    "eip": ServiceSpec(
        name="eip",
        display_name="Elastic IP (EIP)",
        implementation_name="eip",
        sdk_package_root="huaweicloudsdkeip",
        env_key="EIP",
        credential_scope="basic",
        default_api_version="v2",
        versions=_EIP_VERSIONS,
        aliases=("elastic_ip",),
        provisioning_prerequisites=(),
        provisioning_notes="Provision, bind, unbind, and manage public IPs and shared bandwidth automatically when public access is needed.",
    ),
    "as": ServiceSpec(
        name="as",
        display_name="Auto Scaling (AS)",
        implementation_name="as",
        sdk_package_root="huaweicloudsdkas",
        env_key="AS",
        credential_scope="basic",
        default_api_version="v1",
        versions=_AS_VERSIONS,
        aliases=("auto_scaling",),
        provisioning_prerequisites=("ecs", "elb", "eip"),
        provisioning_notes="Provision scaling groups, policies, hooks, and lifecycle management tied to compute and load-balancing resources.",
    ),
    "cbr": ServiceSpec(
        name="cbr",
        display_name="Cloud Backup and Recovery (CBR)",
        implementation_name="cbr",
        sdk_package_root="huaweicloudsdkcbr",
        env_key="CBR",
        credential_scope="basic",
        default_api_version="v1",
        versions=_CBR_VERSIONS,
        aliases=("cloud_backup_and_recovery", "vbs", "volume_backup_service"),
        provisioning_prerequisites=(),
        provisioning_notes="Create backup vaults, policies, and protected-resource flows automatically for storage and database services.",
    ),
    "dws": ServiceSpec(
        name="dws",
        display_name="Data Warehouse Service (DWS)",
        implementation_name="dws",
        sdk_package_root="huaweicloudsdkdws",
        env_key="DWS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_DWS_VERSIONS,
        aliases=("data_warehouse_service",),
        provisioning_prerequisites=("vpc", "eip", "evs", "cbr"),
        provisioning_notes=(
            "Provision warehouse clusters, snapshots, scaling, networking, and "
            "backup-related resources for DWS analytics workloads."
        ),
    ),
    "cloudtable": ServiceSpec(
        name="cloudtable",
        display_name="CloudTable",
        implementation_name="cloudtable",
        sdk_package_root="huaweicloudsdkcloudtable",
        env_key="CLOUDTABLE",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CLOUDTABLE_VERSIONS,
        aliases=("cloud_table",),
        provisioning_prerequisites=("vpc", "eip", "evs"),
        provisioning_notes=(
            "Manage CloudTable clusters, component configuration, networking, and "
            "lifecycle operations for HBase-style workloads."
        ),
    ),
    "apm": ServiceSpec(
        name="apm",
        display_name="Application Performance Management (APM)",
        implementation_name="apm",
        sdk_package_root="huaweicloudsdkapm",
        env_key="APM",
        credential_scope="basic",
        default_api_version="v1",
        versions=_APM_VERSIONS,
        aliases=("application_performance_management",),
        provisioning_prerequisites=("aom", "lts"),
        provisioning_notes=(
            "Manage APM discovery, topology, traces, and performance-analysis flows "
            "through the published SDK surface."
        ),
    ),
    "aom": ServiceSpec(
        name="aom",
        display_name="Application Operations Management (AOM)",
        implementation_name="aom",
        sdk_package_root="huaweicloudsdkaom",
        env_key="AOM",
        credential_scope="basic",
        default_api_version="v4",
        versions=_AOM_VERSIONS,
        aliases=("application_operations_management",),
        provisioning_prerequisites=("lts", "ces"),
        provisioning_notes=(
            "Manage dashboards, metrics, events, alarms, and application observability "
            "resources across AOM API versions."
        ),
    ),
    "workspace": ServiceSpec(
        name="workspace",
        display_name="Workspace",
        implementation_name="workspace",
        sdk_package_root="huaweicloudsdkworkspace",
        env_key="WORKSPACE",
        credential_scope="basic",
        default_api_version="v2",
        versions=_WORKSPACE_VERSIONS,
        aliases=("workspace_desktop", "workspace_service"),
        provisioning_prerequisites=("vpc", "evs", "eip", "dns"),
        provisioning_notes=(
            "Manage desktop workspaces, directories, policies, internet access, users, "
            "and desktop lifecycle resources with minimal extra input."
        ),
    ),
    "workspaceapp": ServiceSpec(
        name="workspaceapp",
        display_name="Workspace App",
        implementation_name="workspaceapp",
        sdk_package_root="huaweicloudsdkworkspaceapp",
        env_key="WORKSPACEAPP",
        credential_scope="basic",
        default_api_version="v1",
        versions=_WORKSPACEAPP_VERSIONS,
        aliases=("workspace_app", "workspace_application"),
        provisioning_prerequisites=("vpc", "evs", "eip", "dns"),
        provisioning_notes=(
            "Manage application streaming groups, app servers, assignments, images, "
            "and related workspace-app lifecycle operations."
        ),
    ),
    "functiongraph": ServiceSpec(
        name="functiongraph",
        display_name="FunctionGraph",
        implementation_name="functiongraph",
        sdk_package_root="huaweicloudsdkfunctiongraph",
        env_key="FUNCTIONGRAPH",
        credential_scope="basic",
        default_api_version="v2",
        versions=_FUNCTIONGRAPH_VERSIONS,
        aliases=("function_graph", "fg"),
        provisioning_prerequisites=("obs", "swr", "lts", "vpc", "apig"),
        provisioning_notes=(
            "Manage functions, triggers, workflows, code packages, VPC access, and "
            "logging. Use the direct code-deploy helper when you want local source "
            "zipped and uploaded automatically."
        ),
    ),
    "cae": ServiceSpec(
        name="cae",
        display_name="Cloud Application Engine (CAE)",
        implementation_name="cae",
        sdk_package_root="huaweicloudsdkcae",
        env_key="CAE",
        credential_scope="basic",
        default_api_version="v1",
        versions=_CAE_VERSIONS,
        aliases=("cloud_application_engine",),
        provisioning_prerequisites=("vpc", "elb", "eip", "swr"),
        provisioning_notes=(
            "Manage CAE environments, components, domains, and application lifecycle "
            "resources for containerized app delivery."
        ),
    ),
    "cdn": ServiceSpec(
        name="cdn",
        display_name="Content Delivery Network (CDN)",
        implementation_name="cdn",
        sdk_package_root="huaweicloudsdkcdn",
        env_key="CDN",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CDN_VERSIONS,
        aliases=("content_delivery_network",),
        provisioning_prerequisites=("obs", "elb", "eip"),
        provisioning_notes=(
            "Manage CDN domains, origins, certificates, cache policies, and acceleration "
            "configuration for public delivery workloads."
        ),
    ),
    "das": ServiceSpec(
        name="das",
        display_name="Database Autonomy Service (DAS)",
        implementation_name="das",
        sdk_package_root="huaweicloudsdkdas",
        env_key="DAS",
        credential_scope="basic",
        default_api_version="v3",
        versions=_DAS_VERSIONS,
        aliases=("database_autonomy_service",),
        provisioning_prerequisites=("rds", "gaussdb", "dds", "gaussdb_nosql"),
        provisioning_notes=(
            "Manage SQL insight, diagnostics, tuning, and autonomous database analysis "
            "for supported Huawei database engines."
        ),
    ),
    "drs": ServiceSpec(
        name="drs",
        display_name="Data Replication Service (DRS)",
        implementation_name="drs",
        sdk_package_root="huaweicloudsdkdrs",
        env_key="DRS",
        credential_scope="basic",
        default_api_version="v5",
        versions=_DRS_VERSIONS,
        aliases=("data_replication_service",),
        provisioning_prerequisites=("vpc", "rds", "gaussdb", "dds"),
        provisioning_notes=(
            "Manage migration, synchronization, and disaster-recovery jobs plus their "
            "networking prerequisites and task lifecycle operations."
        ),
    ),
    "ugo": ServiceSpec(
        name="ugo",
        display_name="UGO",
        implementation_name="ugo",
        sdk_package_root="huaweicloudsdkugo",
        env_key="UGO",
        credential_scope="basic",
        default_api_version="v1",
        versions=_UGO_VERSIONS,
        aliases=("ugo_service",),
        provisioning_prerequisites=("rds", "gaussdb", "gaussdb_opengauss"),
        provisioning_notes=(
            "Manage database evaluation, migration-assessment, syntax-conversion, and "
            "verification workflows for modernization projects."
        ),
    ),
    "ddm": ServiceSpec(
        name="ddm",
        display_name="Distributed Database Middleware (DDM)",
        implementation_name="ddm",
        sdk_package_root="huaweicloudsdkddm",
        env_key="DDM",
        credential_scope="basic",
        default_api_version="v1",
        versions=_DDM_VERSIONS,
        aliases=("distributed_database_middleware",),
        provisioning_prerequisites=("vpc", "rds", "taurusdb"),
        provisioning_notes=(
            "Manage DDM instances, schemas, shard rules, and database-access resources "
            "for distributed MySQL-compatible deployments."
        ),
    ),
    "ocr": ServiceSpec(
        name="ocr",
        display_name="Optical Character Recognition (OCR)",
        implementation_name="ocr",
        sdk_package_root="huaweicloudsdkocr",
        env_key="OCR",
        credential_scope="basic",
        default_api_version="v1",
        versions=_OCR_VERSIONS,
        aliases=("optical_character_recognition",),
        provisioning_prerequisites=(),
        provisioning_notes="Access OCR extraction and recognition APIs for image and document understanding workloads.",
    ),
    "css": ServiceSpec(
        name="css",
        display_name="Cloud Search Service (CSS)",
        implementation_name="css",
        sdk_package_root="huaweicloudsdkcss",
        env_key="CSS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CSS_VERSIONS,
        aliases=("cloud_search_service", "elasticsearch"),
        provisioning_prerequisites=("vpc", "eip", "cbr"),
        provisioning_notes=(
            "Manage Elasticsearch or OpenSearch-compatible clusters, snapshots, scaling, "
            "security, and public or private access settings."
        ),
    ),
    "lts": ServiceSpec(
        name="lts",
        display_name="Log Tank Service (LTS)",
        implementation_name="lts",
        sdk_package_root="huaweicloudsdklts",
        env_key="LTS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_LTS_VERSIONS,
        aliases=("log_tank_service", "cloud_log"),
        provisioning_prerequisites=("obs", "smn"),
        provisioning_notes=(
            "Manage log groups, streams, indexes, transfers, dashboards, and queries. "
            "Use the direct log-query helper when you want log filtering by name, ID, "
            "keywords, SQL, or local regex matching."
        ),
    ),
    "ces": ServiceSpec(
        name="ces",
        display_name="Cloud Eye (CES)",
        implementation_name="ces",
        sdk_package_root="huaweicloudsdkces",
        env_key="CES",
        credential_scope="basic",
        default_api_version="v3",
        versions=_CES_VERSIONS,
        aliases=("cloud_eye", "cloudeye"),
        provisioning_prerequisites=("smn",),
        provisioning_notes="Manage metrics, alarms, dimensions, and monitoring data across Huawei Cloud resources.",
    ),
    "cts": ServiceSpec(
        name="cts",
        display_name="Cloud Trace Service (CTS)",
        implementation_name="cts",
        sdk_package_root="huaweicloudsdkcts",
        env_key="CTS",
        credential_scope="basic",
        default_api_version="v3",
        versions=_CTS_VERSIONS,
        aliases=("cloud_trace_service",),
        provisioning_prerequisites=("obs",),
        provisioning_notes="Manage trackers, traces, event delivery, and audit-export resources for cloud activity tracking.",
    ),
    "organizations": ServiceSpec(
        name="organizations",
        display_name="Organizations",
        implementation_name="organizations",
        sdk_package_root="huaweicloudsdkorganizations",
        env_key="ORGANIZATIONS",
        credential_scope="global",
        default_api_version="v1",
        versions=_ORGANIZATIONS_VERSIONS,
        aliases=("organization",),
        provisioning_prerequisites=("iam",),
        provisioning_notes="Manage organization roots, organizational units, accounts, policies, tags, and governance relationships.",
    ),
    "smn": ServiceSpec(
        name="smn",
        display_name="Simple Message Notification (SMN)",
        implementation_name="smn",
        sdk_package_root="huaweicloudsdksmn",
        env_key="SMN",
        credential_scope="basic",
        default_api_version="v2",
        versions=_SMN_VERSIONS,
        aliases=("simple_message_notification",),
        provisioning_prerequisites=("kms", "lts"),
        provisioning_notes="Manage topics, subscriptions, templates, logtanks, and notification-delivery integrations.",
    ),
    "config": ServiceSpec(
        name="config",
        display_name="Config",
        implementation_name="config",
        sdk_package_root="huaweicloudsdkconfig",
        env_key="CONFIG",
        credential_scope="basic",
        default_api_version="v1",
        versions=_CONFIG_VERSIONS,
        aliases=("resource_governance_config",),
        provisioning_prerequisites=("cts", "ces", "smn"),
        provisioning_notes="Manage resource configuration recorders, conformance packs, rules, and compliance-evaluation workflows.",
    ),
    "apig": ServiceSpec(
        name="apig",
        display_name="API Gateway (APIG)",
        implementation_name="apig",
        sdk_package_root="huaweicloudsdkapig",
        env_key="APIG",
        credential_scope="basic",
        default_api_version="v2",
        versions=_APIG_VERSIONS,
        aliases=("api_gateway",),
        provisioning_prerequisites=("vpc", "elb", "functiongraph", "cce"),
        provisioning_notes="Manage gateway instances, APIs, domains, policies, authorizers, stages, and backend integrations.",
    ),
    "esw": ServiceSpec(
        name="esw",
        display_name="Enterprise Switch (ESW)",
        implementation_name="esw",
        sdk_package_root="huaweicloudsdkesw",
        env_key="ESW",
        credential_scope="basic",
        default_api_version="v3",
        versions=_ESW_VERSIONS,
        aliases=("enterprise_switch",),
        provisioning_prerequisites=("vpc", "er"),
        provisioning_notes="Manage enterprise switches, attachments, route-domain resources, and advanced virtual networking connectivity.",
    ),
    "cfw": ServiceSpec(
        name="cfw",
        display_name="Cloud Firewall (CFW)",
        implementation_name="cfw",
        sdk_package_root="huaweicloudsdkcfw",
        env_key="CFW",
        credential_scope="basic",
        default_api_version="v1",
        versions=_CFW_VERSIONS,
        aliases=("cloud_firewall",),
        provisioning_prerequisites=("vpc", "eip", "nat"),
        provisioning_notes="Manage cloud-firewall instances, ACLs, rulebases, logs, and traffic-protection policies.",
    ),
    "waf": ServiceSpec(
        name="waf",
        display_name="Web Application Firewall (WAF)",
        implementation_name="waf",
        sdk_package_root="huaweicloudsdkwaf",
        env_key="WAF",
        credential_scope="basic",
        default_api_version="v1",
        versions=_WAF_VERSIONS,
        aliases=("web_application_firewall",),
        provisioning_prerequisites=("elb", "eip", "cdn"),
        provisioning_notes="Manage protected domains, policies, custom rules, anti-bot controls, certificates, and traffic-protection settings.",
    ),
    "aad": ServiceSpec(
        name="aad",
        display_name="Advanced Anti-DDoS (AAD)",
        implementation_name="aad",
        sdk_package_root="huaweicloudsdkaad",
        env_key="AAD",
        credential_scope="basic",
        default_api_version="v2",
        versions=_AAD_VERSIONS,
        aliases=("advanced_anti_ddos",),
        provisioning_prerequisites=("eip", "elb"),
        provisioning_notes="Manage advanced anti-DDoS instances, policies, protected objects, and traffic-scrubbing workflows.",
    ),
    "antiddos": ServiceSpec(
        name="antiddos",
        display_name="Anti-DDoS",
        implementation_name="antiddos",
        sdk_package_root="huaweicloudsdkantiddos",
        env_key="ANTIDDOS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_ANTIDDOS_VERSIONS,
        aliases=("anti_ddos", "ddos"),
        provisioning_prerequisites=("eip",),
        provisioning_notes="Manage baseline anti-DDoS protection resources, alarms, and mitigation configuration for public endpoints.",
    ),
    "cgs": ServiceSpec(
        name="cgs",
        display_name="Container Guard Service (CGS)",
        implementation_name="cgs",
        sdk_package_root="huaweicloudsdkcgs",
        env_key="CGS",
        credential_scope="basic",
        default_api_version="v5",
        versions=_CGS_VERSIONS,
        aliases=("container_guard_service",),
        provisioning_prerequisites=("cce", "swr"),
        provisioning_notes="Manage container image scanning, runtime security, and related CGS security-analysis workflows.",
    ),
    "cbh": ServiceSpec(
        name="cbh",
        display_name="Cloud Bastion Host (CBH)",
        implementation_name="cbh",
        sdk_package_root="huaweicloudsdkcbh",
        env_key="CBH",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CBH_VERSIONS,
        aliases=("cloud_bastion_host",),
        provisioning_prerequisites=("vpc", "eip", "ecs"),
        provisioning_notes="Manage bastion hosts, system settings, resources, users, permissions, and secure access workflows."
    ),
    "codearts_artifact": ServiceSpec(
        name="codearts_artifact",
        display_name="CodeArts Artifact",
        implementation_name="codeartsartifact",
        sdk_package_root="huaweicloudsdkcodeartsartifact",
        env_key="CODEARTSARTIFACT",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CODEARTS_ARTIFACT_VERSIONS,
        aliases=("codeartsartifact",),
        provisioning_prerequisites=(),
        provisioning_notes="Manage CodeArts artifact repositories, packages, versions, and artifact-governance workflows.",
    ),
    "codearts_build": ServiceSpec(
        name="codearts_build",
        display_name="CodeArts Build",
        implementation_name="codeartsbuild",
        sdk_package_root="huaweicloudsdkcodeartsbuild",
        env_key="CODEARTSBUILD",
        credential_scope="basic",
        default_api_version="v3",
        versions=_CODEARTS_BUILD_VERSIONS,
        aliases=("codeartsbuild",),
        provisioning_prerequisites=("codearts_repo",),
        provisioning_notes="Manage build jobs, triggers, task history, and build-pipeline execution resources.",
    ),
    "codearts_check": ServiceSpec(
        name="codearts_check",
        display_name="CodeArts Check",
        implementation_name="codeartscheck",
        sdk_package_root="huaweicloudsdkcodeartscheck",
        env_key="CODEARTSCHECK",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CODEARTS_CHECK_VERSIONS,
        aliases=("codeartscheck",),
        provisioning_prerequisites=("codearts_repo",),
        provisioning_notes="Manage static-analysis tasks, rule sets, scan results, and code-quality governance workflows.",
    ),
    "codearts_deploy": ServiceSpec(
        name="codearts_deploy",
        display_name="CodeArts Deploy",
        implementation_name="codeartsdeploy",
        sdk_package_root="huaweicloudsdkcodeartsdeploy",
        env_key="CODEARTSDEPLOY",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CODEARTS_DEPLOY_VERSIONS,
        aliases=("codeartsdeploy",),
        provisioning_prerequisites=("codearts_artifact", "ecs", "cce", "cae"),
        provisioning_notes="Manage deployment projects, actions, hosts, environments, and release-execution workflows.",
    ),
    "codearts_pipeline": ServiceSpec(
        name="codearts_pipeline",
        display_name="CodeArts Pipeline",
        implementation_name="codeartspipeline",
        sdk_package_root="huaweicloudsdkcodeartspipeline",
        env_key="CODEARTSPIPELINE",
        credential_scope="basic",
        default_api_version="v2",
        versions=_CODEARTS_PIPELINE_VERSIONS,
        aliases=("codeartspipeline",),
        provisioning_prerequisites=("codearts_build", "codearts_deploy", "codearts_check"),
        provisioning_notes="Manage CI/CD pipelines, stages, plugin steps, execution runs, and approval or governance flows.",
    ),
    "codearts_repo": ServiceSpec(
        name="codearts_repo",
        display_name="CodeArts Repo",
        implementation_name="codeartsrepo",
        sdk_package_root="huaweicloudsdkcodeartsrepo",
        env_key="CODEARTSREPO",
        credential_scope="basic",
        default_api_version="v4",
        versions=_CODEARTS_REPO_VERSIONS,
        aliases=("codeartsrepo",),
        provisioning_prerequisites=(),
        provisioning_notes="Manage repositories, branches, commits, pull requests, members, and repository-level governance in CodeArts Repo.",
    ),
    "codehub": ServiceSpec(
        name="codehub",
        display_name="CodeHub",
        implementation_name="codehub",
        sdk_package_root="huaweicloudsdkcodehub",
        env_key="CODEHUB",
        credential_scope="basic",
        default_api_version="v4",
        versions=_CODEHUB_VERSIONS,
        aliases=("code_hub",),
        provisioning_prerequisites=(),
        provisioning_notes="Manage the older CodeHub repository surface when users target legacy CodeArts source-control workflows."
    ),
    "dds": ServiceSpec(
        name="dds",
        display_name="Document Database Service (DDS)",
        implementation_name="dds",
        sdk_package_root="huaweicloudsdkdds",
        env_key="DDS",
        credential_scope="basic",
        default_api_version="v3",
        versions=_DDS_VERSIONS,
        aliases=("document_database_service", "mongo"),
        provisioning_prerequisites=("vpc", "kms", "cbr"),
        provisioning_notes="Provision DDS clusters, networking, backups, access rules, and lifecycle operations with the same least-input flow as other databases.",
    ),
    "dcs": ServiceSpec(
        name="dcs",
        display_name="Distributed Cache Service (DCS)",
        implementation_name="dcs",
        sdk_package_root="huaweicloudsdkdcs",
        env_key="DCS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_DCS_VERSIONS,
        aliases=("distributed_cache_service", "redis"),
        provisioning_prerequisites=("vpc", "kms"),
        provisioning_notes="Provision caches, users, ACLs, instances, and backups with automatic network setup when needed.",
    ),
    "dms": ServiceSpec(
        name="dms",
        display_name="Distributed Message Service (DMS)",
        implementation_name="dms",
        sdk_package_root="huaweicloudsdkdms",
        env_key="DMS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_DMS_VERSIONS,
        aliases=("distributed_message_service",),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Manage queues, topics, message production or consumption, and related DMS resources through the published SDK surface.",
    ),
    "kafka": ServiceSpec(
        name="kafka",
        display_name="DMS for Kafka",
        implementation_name="kafka",
        sdk_package_root="huaweicloudsdkkafka",
        env_key="KAFKA",
        credential_scope="basic",
        default_api_version="v2",
        versions=_KAFKA_VERSIONS,
        aliases=("dms_kafka",),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Extended DMS coverage for Kafka clusters, topics, users, and lifecycle management.",
    ),
    "rabbitmq": ServiceSpec(
        name="rabbitmq",
        display_name="DMS for RabbitMQ",
        implementation_name="rabbitmq",
        sdk_package_root="huaweicloudsdkrabbitmq",
        env_key="RABBITMQ",
        credential_scope="basic",
        default_api_version="v2",
        versions=_RABBITMQ_VERSIONS,
        aliases=("dms_rabbitmq",),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Extended DMS coverage for RabbitMQ instances, users, permissions, and queue management.",
    ),
    "rocketmq": ServiceSpec(
        name="rocketmq",
        display_name="DMS for RocketMQ",
        implementation_name="rocketmq",
        sdk_package_root="huaweicloudsdkrocketmq",
        env_key="ROCKETMQ",
        credential_scope="basic",
        default_api_version="v2",
        versions=_ROCKETMQ_VERSIONS,
        aliases=("dms_rocketmq",),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Extended DMS coverage for RocketMQ brokers, topics, consumer groups, and lifecycle management.",
    ),
    "asm": ServiceSpec(
        name="asm",
        display_name="Application Service Mesh (ASM)",
        implementation_name="asm",
        sdk_package_root="huaweicloudsdkasm",
        env_key="ASM",
        credential_scope="basic",
        default_api_version="v1",
        versions=_ASM_VERSIONS,
        aliases=("application_service_mesh", "service_mesh"),
        provisioning_prerequisites=("cce",),
        provisioning_notes="Manage service-mesh instances, gateways, and related resources for Kubernetes-based deployments.",
    ),
    "swr": ServiceSpec(
        name="swr",
        display_name="SoftWare Repository for Container (SWR)",
        implementation_name="swr",
        sdk_package_root="huaweicloudsdkswr",
        env_key="SWR",
        credential_scope="basic",
        default_api_version="v2",
        versions=_SWR_VERSIONS,
        aliases=("container_registry",),
        provisioning_prerequisites=(),
        provisioning_notes="Manage container registries, organizations, namespaces, repositories, and image-related settings.",
    ),
    "ucs": ServiceSpec(
        name="ucs",
        display_name="Ubiquitous Cloud Native Service (UCS)",
        implementation_name="ucs",
        sdk_package_root="huaweicloudsdkucs",
        env_key="UCS",
        credential_scope="basic",
        default_api_version="v1",
        versions=_UCS_VERSIONS,
        aliases=("ubiquitous_cloud_native_service",),
        provisioning_prerequisites=("cce",),
        provisioning_notes="Extended container-platform coverage for multi-cluster cloud native management flows.",
    ),
    "nat": ServiceSpec(
        name="nat",
        display_name="NAT Gateway",
        implementation_name="nat",
        sdk_package_root="huaweicloudsdknat",
        env_key="NAT",
        credential_scope="basic",
        default_api_version="v2",
        versions=_NAT_VERSIONS,
        aliases=("nat_gateway",),
        provisioning_prerequisites=("vpc", "eip"),
        provisioning_notes="Manage NAT gateways, DNAT, SNAT, and associated networking resources automatically when workloads need egress or ingress translation.",
    ),
    "dns": ServiceSpec(
        name="dns",
        display_name="Domain Name Service (DNS)",
        implementation_name="dns",
        sdk_package_root="huaweicloudsdkdns",
        env_key="DNS",
        credential_scope="basic",
        default_api_version="v2",
        versions=_DNS_VERSIONS,
        aliases=("domain_name_service",),
        provisioning_prerequisites=(),
        provisioning_notes="Manage zones, record sets, PTR records, and DNS configuration for networked services.",
    ),
    "er": ServiceSpec(
        name="er",
        display_name="Enterprise Router (ER)",
        implementation_name="er",
        sdk_package_root="huaweicloudsdker",
        env_key="ER",
        credential_scope="basic",
        default_api_version="v3",
        versions=_ER_VERSIONS,
        aliases=("enterprise_router",),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Manage enterprise routers, attachments, propagations, associations, and route tables.",
    ),
    "vpn": ServiceSpec(
        name="vpn",
        display_name="Virtual Private Network (VPN)",
        implementation_name="vpn",
        sdk_package_root="huaweicloudsdkvpn",
        env_key="VPN",
        credential_scope="basic",
        default_api_version="v5",
        versions=_VPN_VERSIONS,
        aliases=("virtual_private_network",),
        provisioning_prerequisites=("vpc", "eip"),
        provisioning_notes="Manage VPN gateways, customer gateways, connections, and related network encryption resources.",
    ),
    "dc": ServiceSpec(
        name="dc",
        display_name="Direct Connect (DC)",
        implementation_name="dc",
        sdk_package_root="huaweicloudsdkdc",
        env_key="DC",
        credential_scope="basic",
        default_api_version="v3",
        versions=_DC_VERSIONS,
        aliases=("direct_connect",),
        provisioning_prerequisites=("vpc", "er"),
        provisioning_notes="Manage dedicated connections, virtual gateways, hosted connections, and link lifecycle operations.",
    ),
    "geip": ServiceSpec(
        name="geip",
        display_name="Global EIP (GEIP)",
        implementation_name="geip",
        sdk_package_root="huaweicloudsdkgeip",
        env_key="GEIP",
        credential_scope="basic",
        default_api_version="v3",
        versions=_GEIP_VERSIONS,
        aliases=("global_eip",),
        provisioning_prerequisites=("eip",),
        provisioning_notes="Manage global elastic IP resources and cross-region public networking workflows.",
    ),
    "ga": ServiceSpec(
        name="ga",
        display_name="Global Accelerator (GA)",
        implementation_name="ga",
        sdk_package_root="huaweicloudsdkga",
        env_key="GA",
        credential_scope="basic",
        default_api_version="v1",
        versions=_GA_VERSIONS,
        aliases=("global_accelerator",),
        provisioning_prerequisites=("eip", "elb"),
        provisioning_notes="Manage global accelerator instances, listeners, endpoint groups, and routing acceleration resources.",
    ),
    "vpcep": ServiceSpec(
        name="vpcep",
        display_name="VPC Endpoint (VPCEP)",
        implementation_name="vpcep",
        sdk_package_root="huaweicloudsdkvpcep",
        env_key="VPCEP",
        credential_scope="basic",
        default_api_version="v1",
        versions=_VPCEP_VERSIONS,
        aliases=("vpc_endpoint",),
        provisioning_prerequisites=("vpc",),
        provisioning_notes="Manage VPC endpoints, services, gateway endpoints, and private access integrations.",
    ),
    "cc": ServiceSpec(
        name="cc",
        display_name="Cloud Connect (CC)",
        implementation_name="cc",
        sdk_package_root="huaweicloudsdkcc",
        env_key="CC",
        credential_scope="basic",
        default_api_version="v3",
        versions=_CC_VERSIONS,
        aliases=("cloud_connect",),
        provisioning_prerequisites=("vpc", "er"),
        provisioning_notes="Manage cloud connections, bandwidth packages, and inter-region networking attachments.",
    ),
}

ClientFactory = Callable[[CloudApiConfig, ResolvedServiceSpec], Any]


def build_sdk_client(config: CloudApiConfig, spec: ResolvedServiceSpec) -> Any:
    if spec.credential_scope == "global":
        if config.domain_id:
            credentials = GlobalCredentials(
                config.access_key_id,
                config.secret_access_key,
                config.domain_id,
            )
        else:
            credentials = GlobalCredentials(
                config.access_key_id,
                config.secret_access_key,
            )
        credential_identifier = config.domain_id
        identifier_name = "domain_id"
    else:
        if config.project_id:
            credentials = BasicCredentials(
                config.access_key_id,
                config.secret_access_key,
                config.project_id,
            )
        else:
            credentials = BasicCredentials(
                config.access_key_id,
                config.secret_access_key,
            )
        credential_identifier = config.project_id
        identifier_name = "project_id"

    if config.security_token:
        credentials = credentials.with_security_token(config.security_token)

    builder = spec.client_class.new_builder().with_credentials(credentials)
    if config.endpoint:
        if config.region is None and credential_identifier is None:
            raise ValueError(
                f"{spec.display_name} region is required to resolve {identifier_name} automatically"
            )
        return builder.with_endpoint(config.endpoint).build()

    if config.region is None:
        raise ValueError(f"{spec.display_name} region is required to call the SDK")

    return builder.with_region(spec.region_for(config.region)).build()


class HuaweiCloudSdkService:
    def __init__(
        self,
        config: CloudApiConfig,
        service_name: str,
        api_version: str | None = None,
        client_factory: ClientFactory = build_sdk_client,
    ):
        self._spec = resolve_service_spec(service_name, api_version)
        self._config = config
        self._client_factory = client_factory
        self._client: Any | None = None

    @property
    def endpoint(self) -> str | None:
        if self._config.endpoint:
            return self._config.endpoint
        if self._config.region is None:
            return None
        return self._spec.endpoint_for_region(self._config.region)

    def list_operations(
        self,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        operations = self._operations()
        if query:
            query_text = query.strip().lower()
            operations = [
                operation for operation in operations if query_text in operation.lower()
            ]

        page = operations[offset : offset + limit]
        return {
            "service": self._spec.name,
            "display_name": self._spec.display_name,
            "implementation": self._spec.implementation_name,
            "sdk_package_root": self._spec.sdk_package_root,
            "api_version": self._spec.api_version,
            "available_api_versions": list(self._spec.available_api_versions),
            "credential_scope": self._spec.credential_scope,
            "region": self._config.region,
            "endpoint": self.endpoint,
            "total_count": len(operations),
            "returned_count": len(page),
            "offset": offset,
            "limit": limit,
            "operations": page,
        }

    def describe_operation(
        self,
        operation: str,
        max_depth: int = 4,
    ) -> dict[str, object]:
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")

        normalized_operation = self._normalize_operation(operation)
        request_class = self._request_class(normalized_operation)
        schema = self._describe_type(request_class.__name__, max_depth, set())
        template = self._build_template(request_class.__name__, max_depth, set())

        return {
            "service": self._spec.name,
            "display_name": self._spec.display_name,
            "implementation": self._spec.implementation_name,
            "sdk_package_root": self._spec.sdk_package_root,
            "api_version": self._spec.api_version,
            "available_api_versions": list(self._spec.available_api_versions),
            "operation": normalized_operation,
            "request_model": request_class.__name__,
            "request_schema": schema,
            "request_template": template,
            "notes": (
                "Use SDK attribute names for request fields. API header/query names are also accepted. "
                "If the SDK exposes the operation in another API version, retry with `api_version`."
            ),
        }

    def call_operation(
        self,
        operation: str,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_operation = self._normalize_operation(operation)
        request_class = self._request_class(normalized_operation)
        request_payload = parameters or {}
        if not isinstance(request_payload, dict):
            raise ValueError("parameters must be an object")

        request = self._coerce_value(request_class.__name__, request_payload)

        try:
            response = getattr(self._get_client(), normalized_operation)(request)
        except sdk_exceptions.ClientRequestException as exc:
            raise HuaweiCloudSdkError(str(exc)) from exc
        except sdk_exceptions.SdkException as exc:
            raise HuaweiCloudSdkError(str(exc)) from exc

        return {
            "service": self._spec.name,
            "display_name": self._spec.display_name,
            "implementation": self._spec.implementation_name,
            "sdk_package_root": self._spec.sdk_package_root,
            "api_version": self._spec.api_version,
            "available_api_versions": list(self._spec.available_api_versions),
            "operation": normalized_operation,
            "credential_scope": self._spec.credential_scope,
            "region": self._config.region,
            "endpoint": self.endpoint,
            "response": sanitize_for_serialization(response),
        }

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self._config, self._spec)
        return self._client

    def _operations(self) -> list[str]:
        return list(self._all_operations())

    @lru_cache(maxsize=None)
    def _all_operations(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                name
                for name, value in self._spec.client_class.__dict__.items()
                if not name.startswith("_")
                and callable(value)
                and not name.endswith("_invoker")
                and name not in {"call_api", "new_builder"}
            )
        )

    def _normalize_operation(self, operation: str) -> str:
        candidate = operation.strip()
        if not candidate:
            raise ValueError("operation cannot be empty")
        if candidate not in self._operations():
            raise ValueError(
                f"Unsupported {self._spec.display_name} operation '{candidate}'"
            )
        return candidate

    def _describe_type(
        self,
        type_name: str,
        depth: int,
        visited: set[str],
    ) -> dict[str, object]:
        list_item_type = _parse_list_type(type_name)
        if list_item_type is not None:
            return {
                "kind": "list",
                "type": type_name,
                "items": self._describe_type(list_item_type, depth - 1, visited),
            }

        dict_types = _parse_dict_types(type_name)
        if dict_types is not None:
            _, value_type = dict_types
            return {
                "kind": "dict",
                "type": type_name,
                "values": self._describe_type(value_type, depth - 1, visited),
            }

        if type_name in _PASSTHROUGH_TYPES:
            return {"kind": "primitive", "type": type_name}

        if type_name == "datetime":
            return {"kind": "primitive", "type": "datetime"}

        if depth <= 0 or type_name in visited:
            return {"kind": "object", "model": type_name, "truncated": True}

        try:
            model_class = self._model_class(type_name)
        except (AttributeError, ModuleNotFoundError):
            return {"kind": "opaque", "type": type_name}

        fields = []
        next_visited = visited | {type_name}
        for attribute_name, attribute_type in model_class.openapi_types.items():
            fields.append(
                {
                    "name": attribute_name,
                    "api_name": model_class.attribute_map.get(
                        attribute_name, attribute_name
                    ),
                    "type": attribute_type,
                    "schema": self._describe_type(
                        attribute_type, depth - 1, next_visited
                    ),
                }
            )

        return {
            "kind": "object",
            "model": type_name,
            "fields": fields,
        }

    def _build_template(
        self,
        type_name: str,
        depth: int,
        visited: set[str],
    ) -> Any:
        list_item_type = _parse_list_type(type_name)
        if list_item_type is not None:
            return [self._build_template(list_item_type, depth - 1, visited)]

        dict_types = _parse_dict_types(type_name)
        if dict_types is not None:
            _, value_type = dict_types
            return {"<key>": self._build_template(value_type, depth - 1, visited)}

        if type_name == "datetime":
            return "<iso-8601-datetime>"

        if type_name in _PASSTHROUGH_TYPES:
            return f"<{type_name}>"

        if depth <= 0 or type_name in visited:
            return f"<{type_name}>"

        try:
            model_class = self._model_class(type_name)
        except (AttributeError, ModuleNotFoundError):
            return f"<{type_name}>"

        next_visited = visited | {type_name}
        return {
            attribute_name: self._build_template(
                attribute_type, depth - 1, next_visited
            )
            for attribute_name, attribute_type in model_class.openapi_types.items()
        }

    def _coerce_value(self, expected_type: str, value: Any) -> Any:
        if value is None:
            return None

        list_item_type = _parse_list_type(expected_type)
        if list_item_type is not None:
            if not isinstance(value, list):
                raise ValueError(f"Expected a list for {expected_type}")
            return [self._coerce_value(list_item_type, item) for item in value]

        dict_types = _parse_dict_types(expected_type)
        if dict_types is not None:
            key_type, value_type = dict_types
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object for {expected_type}")
            if key_type != "str":
                raise ValueError(f"Unsupported dict key type: {key_type}")
            return {
                str(key): self._coerce_value(value_type, item)
                for key, item in value.items()
            }

        if expected_type in _PRIMITIVE_TYPES:
            return _coerce_primitive(expected_type, value)

        if expected_type in {"none_type", "NoneType"}:
            return value

        if expected_type == "datetime":
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            raise ValueError("datetime values must be ISO-8601 strings")

        model_class = self._model_class(expected_type)
        if isinstance(value, model_class):
            return value
        if not isinstance(value, dict):
            raise ValueError(f"Expected an object for {expected_type}")

        attribute_types = model_class.openapi_types
        api_names = {
            api_name: attribute_name
            for attribute_name, api_name in model_class.attribute_map.items()
        }

        kwargs = {}
        unknown_fields = []
        for key, item in value.items():
            attribute_name = key if key in attribute_types else api_names.get(key)
            if attribute_name is None:
                unknown_fields.append(key)
                continue

            kwargs[attribute_name] = self._coerce_value(
                attribute_types[attribute_name], item
            )

        if unknown_fields:
            unknown_text = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown fields for {expected_type}: {unknown_text}")

        return model_class(**kwargs)

    @lru_cache(maxsize=None)
    def _request_class(self, operation: str) -> type[Any]:
        return self._import_model_class(
            f"{operation}_request",
            f"{_snake_to_pascal(operation)}Request",
        )

    @lru_cache(maxsize=None)
    def _model_class(self, type_name: str) -> type[Any]:
        return self._import_model_class(_pascal_to_snake(type_name), type_name)

    def _import_model_class(self, module_name: str, class_name: str) -> type[Any]:
        module = import_module(f"{self._spec.model_package}.{module_name}")
        return getattr(module, class_name)


def resolve_service_spec(
    service_name: str,
    api_version: str | None = None,
) -> ResolvedServiceSpec:
    normalized_name = _normalize_service_name(service_name)
    canonical_name = _SERVICE_ALIASES.get(normalized_name)
    if canonical_name is None:
        supported_names = ", ".join(sorted(SERVICE_SPECS))
        raise ValueError(
            f"Unsupported Huawei Cloud service '{service_name}'. "
            f"Supported services: {supported_names}"
        )
    return SERVICE_SPECS[canonical_name].resolve(api_version)


def list_supported_services(query: str | None = None) -> dict[str, object]:
    services = []
    query_text = query.strip().lower() if query else None

    for spec in SERVICE_SPECS.values():
        searchable_text = " ".join(
            [
                spec.name,
                spec.display_name,
                spec.implementation_name,
                *spec.aliases,
                *(spec.provisioning_prerequisites or ()),
                spec.provisioning_notes or "",
            ]
        ).lower()
        if query_text and query_text not in searchable_text:
            continue

        services.append(
            {
                "service": spec.name,
                "display_name": spec.display_name,
                "implementation": spec.implementation_name,
                "sdk_package_root": spec.sdk_package_root,
                "tool_prefix": spec.name,
                "service_tools": [
                    f"{spec.name}_list_operations",
                    f"{spec.name}_describe_operation",
                    f"{spec.name}_call_operation",
                ],
                "aliases": list(spec.aliases),
                "default_api_version": spec.default_api_version,
                "available_api_versions": list(spec.versions),
                "credential_scope": spec.credential_scope,
                "provisioning_prerequisites": list(spec.provisioning_prerequisites),
                "provisioning_notes": spec.provisioning_notes,
            }
        )

    return {
        "total_count": len(SERVICE_SPECS),
        "returned_count": len(services),
        "services": services,
    }


def summarize_service_capabilities(
    service_name: str,
    api_version: str | None = None,
    focus: str | None = None,
) -> dict[str, object]:
    resolved_spec = resolve_service_spec(service_name, api_version)
    operations = _list_operations_for_spec(resolved_spec)
    focus_terms = [term for term in _normalize_service_name(focus).split("_") if term] if focus else []

    category_operations: dict[str, list[str]] = {
        category: [] for category in _OPERATION_CATEGORY_PREFIXES
    }
    uncategorized_operations: list[str] = []

    for operation in operations:
        category = _categorize_operation(operation)
        if category is None:
            uncategorized_operations.append(operation)
        else:
            category_operations[category].append(operation)

    resource_counter: Counter[str] = Counter()
    for operation in operations:
        resource_counter.update(_extract_operation_resource_tokens(operation))

    focus_matches = []
    if focus_terms:
        focus_matches = [
            operation
            for operation in operations
            if all(term in operation.lower() for term in focus_terms)
        ]

    example_operations = {
        category: ops[:10]
        for category, ops in category_operations.items()
        if ops
    }
    if uncategorized_operations:
        example_operations["other"] = uncategorized_operations[:10]

    return {
        "service": resolved_spec.name,
        "display_name": resolved_spec.display_name,
        "implementation": resolved_spec.implementation_name,
        "sdk_package_root": resolved_spec.sdk_package_root,
        "api_version": resolved_spec.api_version,
        "available_api_versions": list(resolved_spec.available_api_versions),
        "operation_count": len(operations),
        "operation_breakdown": {
            category: len(category_operations[category])
            for category in _OPERATION_CATEGORY_PREFIXES
        }
        | {"other": len(uncategorized_operations)},
        "example_operations": example_operations,
        "top_resource_tokens": [
            {"token": token, "count": count}
            for token, count in resource_counter.most_common(20)
        ],
        "focus": focus,
        "focus_matches": focus_matches[:50],
        "notes": [
            "This summary reflects the published Huawei Python SDK surface for the selected service and API version.",
            "Cluster-internal actions such as kubectl, helm, SSH, or application-level commands are separate workflow steps unless they appear as SDK operations.",
        ],
    }


def _list_operations_for_spec(resolved_spec: ResolvedServiceSpec) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name, value in resolved_spec.client_class.__dict__.items()
            if not name.startswith("_")
            and callable(value)
            and not name.endswith("_invoker")
            and name not in {"call_api", "new_builder"}
        )
    )


def _categorize_operation(operation: str) -> str | None:
    for category, prefixes in _OPERATION_CATEGORY_PREFIXES.items():
        if operation.startswith(prefixes):
            return category
    return None


def _extract_operation_resource_tokens(operation: str) -> list[str]:
    tokens = [token for token in operation.lower().split("_") if token]
    resource_tokens = [
        token
        for token in tokens
        if token not in _OPERATION_TOKEN_STOPWORDS and len(token) > 2
    ]
    return resource_tokens


def _coerce_primitive(expected_type: str, value: Any) -> Any:
    if expected_type == "object":
        return value
    if expected_type == "str":
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        raise ValueError("String fields must be strings, numbers, or booleans")
    if expected_type == "int":
        if isinstance(value, bool):
            raise ValueError("Integer fields cannot be booleans")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        raise ValueError("Integer fields must be integers")
    if expected_type == "float":
        if isinstance(value, bool):
            raise ValueError("Float fields cannot be booleans")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value)
        raise ValueError("Float fields must be numeric")
    if expected_type == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError("Boolean fields must be true or false")
    return value


def _normalize_service_name(service_name: str) -> str:
    normalized_name = _SERVICE_KEY_PATTERN.sub("_", service_name.strip().lower())
    normalized_name = normalized_name.strip("_")
    if not normalized_name:
        raise ValueError("service_name cannot be empty")
    return normalized_name


@lru_cache(maxsize=None)
def _import_attribute(module_name: str, attribute_name: str) -> Any:
    module = import_module(module_name)
    return getattr(module, attribute_name)


@lru_cache(maxsize=None)
def _infer_endpoint_template(region_module: str, region_class_name: str) -> str:
    region_class = _import_attribute(region_module, region_class_name)
    static_fields = getattr(region_class, "static_fields", {})
    candidates = []
    for region_id, region in static_fields.items():
        endpoint = getattr(region, "endpoint", None)
        if not isinstance(endpoint, str) or region_id not in endpoint:
            continue
        score = 0 if ".myhuaweicloud.com" in endpoint else 1
        candidates.append((score, len(region_id), region_id, endpoint.rstrip("/")))

    if not candidates:
        raise ValueError(f"Unable to infer endpoint template from {region_module}")

    _, _, region_id, endpoint = sorted(candidates)[0]
    return endpoint.replace(region_id, "{region}", 1)


def _parse_list_type(type_name: str) -> str | None:
    if type_name.startswith("list[") and type_name.endswith("]"):
        return type_name[5:-1].strip()
    return None


def _parse_dict_types(type_name: str) -> tuple[str, str] | None:
    if not type_name.startswith("dict(") or not type_name.endswith(")"):
        return None

    inner = type_name[5:-1]
    parts = _split_top_level(inner)
    if len(parts) != 2:
        raise ValueError(f"Unsupported dict type declaration: {type_name}")
    return parts[0].strip(), parts[1].strip()


def _split_top_level(value: str) -> list[str]:
    parts = []
    current = []
    depth = 0
    for char in value:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue

        current.append(char)

    if current:
        parts.append("".join(current))
    return parts


def _snake_to_pascal(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _pascal_to_snake(value: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


_SERVICE_ALIASES = {
    _normalize_service_name(alias): spec.name
    for spec in SERVICE_SPECS.values()
    for alias in (spec.name, spec.display_name, *spec.aliases)
}
