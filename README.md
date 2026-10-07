<img src="docs/assets/logo.png" alt="mcp-hwc logo" width="80" height="80">

# mcp-hwc

Control **Huawei Cloud** directly from your AI assistant.

`mcp-hwc` is a Model Context Protocol (MCP) server that connects tools like Claude Code or OpenCode to Huawei Cloud. Provision VMs, manage Kubernetes, deploy serverless code, query logs, or inspect pricing using natural language.

> ⚠️ **Resource Warning:** Operations create real, billable cloud resources. Review planned actions before approving tool execution.

---

## Quick Start

### Prerequisites
- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- Huawei Cloud credentials (`HWC_AK` and `HWC_SK` from *My Credentials → Access Keys*)

### 1. Install & Configure

```bash
git clone https://github.com/araujoviana/mcp-hwc && cd mcp-hwc
uv sync --dev

cp .env.example .env
# Edit .env with your HWC_AK and HWC_SK
```

### 2. Connect to Your Assistant

**Claude Code**
```bash
claude mcp add hwc -- uv --directory /path/to/mcp-hwc run mcp-hwc
```

**OpenCode** (add to `~/.config/opencode/opencode.jsonc` or `.opencode/opencode.json`):
```json
"mcp": {
  "hwc": {
    "type": "local",
    "command": ["uv", "--directory", "/path/to/mcp-hwc", "run", "mcp-hwc"],
    "enabled": true
  }
}
```

---

## Configuration

Set in `.env` or export in your shell:

| Variable | Required | Description |
| :--- | :---: | :--- |
| `HWC_AK` | **Yes** | Access Key ID |
| `HWC_SK` | **Yes** | Secret Access Key |
| `HWC_SECURITY_TOKEN` | No | Temporary security token (if using STS/IAM) |
| `HWC_REGION` | No | Default region (e.g. `sa-brazil-1`, `la-south-2`). Auto-inferred if omitted. |
| `HWC_PROJECT_ID` | No | Resolved automatically via IAM when region is known. |
| `MCP_HWC_ENABLE_SERVICE_TOOLS` | No | Expose raw per-service SDK tools (`all` or e.g. `ecs,vpc`). Hidden by default to minimize context overhead. |

### Multi-Account Profiles
Create profile files alongside `.env` (e.g. `.env.work`, `.env.personal`):
- Switch in chat: *"Switch to my work account"* (calls `hwc_switch_profile("work")`)
- Inspect active accounts: *"Which account is active?"* (calls `hwc_list_profiles`)

---

## Example Prompts

- **Compute**: *"Create an Ubuntu VM in São Paulo that I can SSH into"*
- **Serverless**: *"Deploy this directory as a FunctionGraph function"*
- **Containers**: *"Push local image `my-app:v1` to SWR"*
- **Kubernetes**: *"Get kubeconfig for my CCE cluster and list failing pods"*
- **Observability**: *"Query LTS logs for error traces in the last hour"*
- **Big Data**: *"Run `SHOW DATABASES` in Hive on MRS cluster `analytics`"*
- **Storage**: *"Upload this file to bucket `my-data` and get a signed URL"*
- **Pricing**: *"Estimate monthly cost for a c6.large.2 ECS with 100GB SSD in Santiago"*

---

## Architecture

To keep context windows small and token costs low, `mcp-hwc` uses a 3-tier structure:

1. **Workflow Helpers**: Curated high-level tools for common operations (`ecs_create_vm`, `obs_*`, `swr_upload_image`, `functiongraph_deploy_code`, `lts_query_logs`, `cce_*`, `k8s_*`, `mrs_*`).
2. **Resource Discovery**: Smart defaults and intent resolution (`huaweicloud_resolve_defaults`, `huaweicloud_summarize_capabilities`).
3. **Generic SDK Reflection**: Full access to 75+ Huawei Cloud SDKs and 3,000+ API operations (`huaweicloud_call_operation`) without bloating the assistant's schema.

### Highlights
- **Token Efficient**: Dense TypeScript signatures, compact table outputs, and automatic local/OBS spooling reduce token footprint by up to 98%.
- **Hardened Security**: Masked passwords/tokens in CLI output, automated `docker logout`, and host key verification for SSH.
- **Self-Contained**: `kubectl` and `helm` execute via local binaries or containerized fallbacks automatically.

---

## Development

```bash
uv run pytest          # Run unit tests (200 tests)
uv run ruff check .    # Lint and style checks
```

## Upgrading to 0.3.0

Behavior changes since 0.2.3:

- **`call_operation` responses are slimmer.** The result keeps `service`, `operation`, `region`
  and `response`; the remaining metadata is dropped, null/empty values are removed and lists
  longer than `max_items` (default 20) are cut with a `_truncated` hint. Pass `verbose=true`
  for the full result or `max_items=0` to disable the list cap.
- **SSH host keys are pinned on first use.** `ssh_*` tools trust a new host once and store
  its key in `~/.mcp-hwc/known_hosts` (override with `MCP_HWC_KNOWN_HOSTS`). A changed key is
  rejected. Pass `allow_unknown_host=false` to refuse hosts you have not already trusted.
- **`ecs_create_vm` no longer returns the generated password** unless `return_password=true`.
