# mcp-hwc

Huawei Cloud MCP server for provisioning, operating, and inspecting cloud resources with a mix of direct service integrations, SDK-backed tools, and execution helpers for SSH, Kubernetes, and Helm.

## What It Does

- exposes Huawei Cloud SDK operations through MCP tools
- supports direct OBS, SSH, SWR image push, FunctionGraph deploy, and LTS log query workflows
- provides least-input defaults for common provisioning flows
- supports Kubernetes and Helm operations against CCE clusters

## Tooling Model

The server is split into three layers.

1. Discovery
- `huaweicloud_list_services`
- `huaweicloud_summarize_capabilities`
- `huaweicloud_resolve_defaults`

2. Generic SDK execution
- `huaweicloud_list_operations`
- `huaweicloud_describe_operation`
- `huaweicloud_call_operation`
- service-specific `*_list_operations`, `*_describe_operation`, `*_call_operation`

3. Direct workflow helpers
- OBS: `obs_*`
- SSH: `ssh_*`
- SWR: `swr_upload_image`
- FunctionGraph: `functiongraph_deploy_code`
- LTS: `lts_query_logs`
- CCE access: `cce_get_kubeconfig`
- Kubernetes: `k8s_apply_manifest`, `k8s_get_resources`, `k8s_wait`, `k8s_logs`, `k8s_exec`
- Helm: `helm_install`, `helm_upgrade`, `helm_uninstall`

## Service Coverage

Supported service families include:

- Compute and platforms: `ecs`, `ims`, `cce`, `mrs`, `functiongraph`, `cae`, `workspace`, `workspaceapp`, `asm`, `swr`, `ucs`
- Databases and data: `rds`, `dws`, `cloudtable`, `gaussdb`, `taurusdb`, `gaussdb_nosql`, `gaussdb_opengauss`, `dds`, `dcs`, `ddm`, `das`, `drs`, `ugo`, `css`
- Networking: `vpc`, `nat`, `dns`, `eip`, `elb`, `er`, `vpcep`, `vpn`, `dc`, `geip`, `ga`, `cc`, `esw`, `cdn`, `apig`
- Storage and backup: `obs`, `evs`, `sfs`, `cbr`
- Messaging: `dms`, `kafka`, `rabbitmq`, `rocketmq`, `smn`
- Ops, governance, and security: `apm`, `aom`, `lts`, `ces`, `cts`, `config`, `organizations`, `kms`, `iam`, `secmaster`, `cfw`, `waf`, `aad`, `antiddos`, `cgs`, `cbh`
- AI and dev services: `modelarts_studio`, `maas`, `metastudio`, `ocr`, `codearts_artifact`, `codearts_build`, `codearts_check`, `codearts_deploy`, `codearts_pipeline`, `codearts_repo`, `codehub`

Aliases are supported where useful. Examples:

- `geminidb` -> `gaussdb_nosql`
- `vbs` -> `cbr`
- `cloud_eye` -> `ces`

Current gaps:

- standalone `ModelArts` core APIs are not wired because Huawei does not publish the Python SDK package needed here
- `cci` is not wired because there is no published `huaweicloudsdkcci` package

## Execution Backends

Kubernetes and Helm tools support:

- `execution_backend="local"`: use binaries installed on the MCP host
- `execution_backend="container"`: run through a container runtime on the MCP host
- `execution_backend="auto"`: prefer local binaries, then fall back to containers

Default containerized runners are configured for:

- `kubectl`
- `helm`

This avoids depending on the end user machine for those tools.

## Setup

1. Copy `.env.example` to `.env`
2. Set credentials
3. Install dependencies
4. Start the server

Example:

```dotenv
HWC_AK=your-access-key-id
HWC_SK=your-secret-access-key
# HWC_SECURITY_TOKEN=temporary-token
```

Run:

```bash
uv sync --dev
uv run mcp-hwc
```

Required environment variables:

- `HWC_AK`
- `HWC_SK`

Optional:

- `HWC_SECURITY_TOKEN`

Most flows should not require `HWC_REGION`, `HWC_PROJECT_ID`, or service-specific environment variables. Region and project are resolved from tool arguments, payloads, and IAM when possible.

## Notes

- Use `huaweicloud_summarize_capabilities` when you want a fast answer about what a service can do through the SDK surface.
- Use `huaweicloud_resolve_defaults` when the request is vague and you want the least-input provisioning profile first.
- Use the generic SDK tools when you need breadth.
- Use the direct helpers when you need end-to-end workflows.
- Use `cce_get_kubeconfig` before `k8s_*` or `helm_*` when operating on a CCE cluster.

## Testing

```bash
uv run pytest
```
