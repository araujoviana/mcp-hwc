# mcp-hwc

Huawei Cloud MCP server for provisioning, operating, and inspecting cloud resources with a mix of direct service integrations, SDK-backed tools, and execution helpers for SSH, Kubernetes, and Helm.

## What It Does

- exposes compact workflow tools for common provisioning tasks
- keeps generic Huawei Cloud SDK operations available for advanced cases
- supports direct OBS, SSH, SWR image push, FunctionGraph deploy, and LTS log query workflows
- provides least-input defaults for common provisioning flows
- supports Kubernetes and Helm operations against CCE clusters

## Tooling Model

The server is split into three layers.

1. Discovery
- `huaweicloud_list_services`
- `huaweicloud_summarize_capabilities`
- `huaweicloud_resolve_defaults`

2. Workflow helpers
- ECS: `ecs_create_vm`
- SWR: `swr_upload_image`
- FunctionGraph: `functiongraph_deploy_code`
- LTS: `lts_query_logs`

3. Dynamic Toolsets (load with `use_toolset`)
- OBS (`obs`): `obs_*`
- SSH (`ssh`): `ssh_*`
- Kubernetes (`k8s`): `cce_get_kubeconfig`, `k8s_execute`, `k8s_apply_manifest`, `helm_*`, etc.
- Pricing (`pricing`): `price_*`

4. Generic SDK execution
- `huaweicloud_list_operations`
- `huaweicloud_describe_operation`
- `huaweicloud_call_operation`

Generated service-specific SDK tools such as `ecs_call_operation` still exist in code, but are hidden from the MCP catalog by default to reduce model context. Set `MCP_HWC_ENABLE_SERVICE_TOOLS=all` or a comma-separated allowlist such as `MCP_HWC_ENABLE_SERVICE_TOOLS=ecs,vpc,ims` to expose them.

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

## Installation in OpenCode
Add the MCP server to your OpenCode configuration file. This is usually `~/.config/opencode/opencode.jsonc` or `.opencode/opencode.json` in the project root.

```json
"mcp": {
  "hwc": {
    "type": "local",
    "command": ["uv", "run", "mcp-hwc"],
    "enabled": true
  }
}
```

## Installation in Claude Code
Install the server by running this command in your terminal:
`claude mcp add hwc -- uv run mcp-hwc`

Environment variables like HWC_AK and HWC_SK can be passed using the `--env` flag if they are not already exported.

## Try it using MaaS
Test the MCP server using ModelArts Studio (MaaS). This is our accessible AI model API. Get started here: https://www.huaweicloud.com/intl/en-us/product/maas.html.

## Notes

- Use `huaweicloud_summarize_capabilities` when you want a fast answer about what a service can do through the SDK surface.
- Use `huaweicloud_resolve_defaults` when the request is vague and you want the least-input provisioning profile first.
- Use workflow tools such as `ecs_create_vm` before generic SDK tools.
- Use the generic SDK tools when no workflow helper covers the operation.
- Use `cce_get_kubeconfig` before `k8s_*` or `helm_*` when operating on a CCE cluster.

## Testing

```bash
uv run pytest
```
