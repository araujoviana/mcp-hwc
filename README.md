# mcp-hwc

MCP server for Huawei Cloud with OBS, ECS, RDS, VPC, and IMS support.

This build focuses on a clean foundation with a broad control surface:

- `mcp` Python SDK server over stdio
- Huawei OBS integration via `esdk-obs-python`
- Huawei ECS, RDS, VPC, and IMS integration via the generated Huawei Cloud Python SDKs
- `.env`-based credential loading with automatic OBS endpoint resolution and IAM-backed project discovery
- schema inspection tools so an AI client can discover large ECS/RDS/VPC/IMS request shapes before making calls
- pytest coverage for config loading, OBS response mapping, generic SDK dispatch, and MCP tool wiring

## Implemented OBS Tools

- `obs_list_buckets`
- `obs_create_bucket`
- `obs_list_objects`
- `obs_get_bucket_location`
- `obs_head_bucket`
- `obs_get_text_object`
- `obs_head_object`
- `obs_put_text_object`
- `obs_delete_object`
- `obs_delete_bucket`

These tools now cover the normal CRUD lifecycle for OBS buckets and text objects.

## Implemented ECS Tools

- `ecs_list_operations`
- `ecs_describe_operation`
- `ecs_call_operation`

`ecs_call_operation` accepts optional `region`, `project_id`, and `endpoint` overrides. When `project_id` is omitted, the Huawei SDK resolves it from IAM automatically once a region is known.

## Implemented RDS Tools

- `rds_list_operations`
- `rds_describe_operation`
- `rds_call_operation`

## Implemented VPC Tools

- `vpc_list_operations`
- `vpc_describe_operation`
- `vpc_call_operation`

## Implemented IMS Tools

- `ims_list_operations`
- `ims_describe_operation`
- `ims_call_operation`

`ecs_list_operations`, `rds_list_operations`, `vpc_list_operations`, and `ims_list_operations` let the model search the generated SDK surface.

`ecs_describe_operation`, `rds_describe_operation`, `vpc_describe_operation`, and `ims_describe_operation` return the request model schema and a request template. This is the main mechanism that lets an AI agent configure VM, network, image, and database resources without hardcoding hundreds of parameters into the MCP server.

`ecs_call_operation`, `rds_call_operation`, `vpc_call_operation`, and `ims_call_operation` accept a structured `parameters` object and dispatch it to the corresponding Huawei Cloud SDK request model.

Adding VPC and IMS fills the main prerequisites that were missing for ECS and RDS provisioning flows: VPCs, subnets, security groups, and image discovery.

The server no longer requires you to hardcode an OBS endpoint for normal use. It uses the global OBS endpoint for discovery and then switches to the correct regional endpoint for bucket and object operations.

## Setup

1. Copy `.env.example` to `.env` and fill in your credentials.
2. Install dependencies with `uv sync --dev`.
3. Start the server with `uv run mcp-hwc`.

Example `.env`:

```dotenv
HWC_AK=your-access-key-id
HWC_SK=your-secret-access-key
# HWC_SECURITY_TOKEN=temporary-token
```

- `HWC_AK` and `HWC_SK` are the only required environment variables.
- `HWC_SECURITY_TOKEN` is only needed for temporary credentials.
- `project_id` no longer needs to be provided by env. The SDK resolves it from IAM automatically when the target region is known.
- For ECS, RDS, VPC, and IMS calls, pass `region` in the tool call when it cannot be inferred from the request payload or endpoint.
- Common aliases such as `santiago` and `sao paulo` are normalized automatically. Ambiguous names like `mexico city` return the valid region-code options instead of guessing.

## Test

Run the test suite with:

```bash
uv run pytest
```

## Claude Desktop Example

```json
{
  "mcpServers": {
    "huawei-cloud": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mcp-hwc",
        "run",
        "mcp-hwc"
      ]
    }
  }
}
```

## Notes

- Huawei documents OBS endpoints per region in its official endpoint directory and uses the `obs.{region}.myhuaweicloud.com` pattern.
- This server defaults to `https://obs.myhuaweicloud.com` for discovery, then resolves the bucket location and switches to the matching regional endpoint automatically.
- Prefer explicit tool arguments for `region`, `project_id`, and `endpoint` over additional env configuration.
- ECS, RDS, VPC, and IMS requests are executed through the generated Huawei Cloud SDKs instead of handwritten REST clients.
- Because these services expose hundreds of operations, this server exposes `list`, `describe`, and `call` tools rather than a separate MCP tool for every SDK method.
- Avoid writing to stdout from the server outside MCP responses.
- Tests mock the OBS SDK, so they run without live Huawei credentials.

## Docs Used

- MCP Python SDK: `mcp.server.fastmcp.FastMCP`
- Huawei OBS Python SDK package: `esdk-obs-python`
- Huawei ECS Python SDK package: `huaweicloudsdkecs`
- Huawei IMS Python SDK package: `huaweicloudsdkims`
- Huawei RDS Python SDK package: `huaweicloudsdkrds`
- Huawei VPC Python SDK package: `huaweicloudsdkvpc`
- Huawei OBS SDK docs: bucket listing, object listing, object upload, and object download pages in the Huawei Cloud Python SDK reference
- Huawei OBS endpoint references: `developer.huaweicloud.com/endpoint?OBS` and `console-intl.huaweicloud.com/apiexplorer/#/endpoint/OBS`
