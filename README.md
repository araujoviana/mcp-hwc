# mcp-hwc

Control Huawei Cloud from an AI assistant. This is an **MCP server** for Huawei Cloud: it lets tools like Claude Code or OpenCode create servers, deploy containers, query logs, estimate prices, and run commands on your cloud resources — you just ask in plain language.

## New to MCP?

MCP (Model Context Protocol) is how AI assistants talk to external systems. An MCP server is a small program that runs on your machine and exposes "tools" (like `ecs_create_vm` or `price_quote`) that the assistant can call on your behalf.

You never call these tools yourself. You tell your assistant *"create a small Ubuntu VM in São Paulo"*, and it picks the right tool, fills in sensible defaults, and asks you only when a choice really matters (cost, region, security).

## Quick start

You need [uv](https://docs.astral.sh/uv/) installed, and a Huawei Cloud **Access Key** (AK) and **Secret Key** (SK) — create them in the Huawei Cloud console under *My Credentials → Access Keys*.

```bash
# 1. Get the code and install dependencies
git clone <this-repo> && cd mcp-hwc
uv sync --dev

# 2. Set your credentials
cp .env.example .env
# edit .env and fill in HWC_AK and HWC_SK
```

Then connect it to your assistant:

**Claude Code**

```bash
claude mcp add hwc -- uv --directory /path/to/mcp-hwc run mcp-hwc
```

**OpenCode** — add to `~/.config/opencode/opencode.jsonc` (or `.opencode/opencode.json` in a project):

```json
"mcp": {
  "hwc": {
    "type": "local",
    "command": ["uv", "--directory", "/path/to/mcp-hwc", "run", "mcp-hwc"],
    "enabled": true
  }
}
```

That's it. Open your assistant and try one of the prompts below.

## What can I ask for?

- *"Create a small Debian VM in Santiago I can SSH into"* → provisions the VPC, subnet, security group, and server, and returns the IP
- *"How much would a c6.large.2 ECS cost per month in São Paulo?"* → returns a price quote you can export or share
- *"Deploy this folder as a FunctionGraph function"*
- *"Push this Docker image to SWR"*
- *"Get the kubeconfig for my CCE cluster and show failing pods"*
- *"Query the LTS logs of my app for errors in the last hour"*
- *"Run `SHOW DATABASES` in Hive on my MRS cluster"* or *"list the Kafka topics on cluster analytics"*

## Configuration

Set these in `.env` (or export them):

| Variable | Required | What it is |
|---|---|---|
| `HWC_AK` | yes | Access Key ID |
| `HWC_SK` | yes | Secret Access Key |
| `HWC_SECURITY_TOKEN` | no | Only for temporary credentials |
| `HWC_REGION`, `HWC_PROJECT_ID` | no | Usually resolved automatically from your request and IAM |
| `MCP_HWC_ENABLE_SERVICE_TOOLS` | no | Expose per-service SDK tools (`all` or e.g. `ecs,vpc`); hidden by default to keep the assistant's context small |

## Multiple accounts

Keep one credential file per account next to `.env`: e.g. `.env.work`, `.env.personal` (same format as `.env`; they are gitignored). Then just ask your assistant:

> "Switch to my work account"

It calls `hwc_switch_profile("work")` and every later call uses that account — no restart. `hwc_list_profiles` shows what's available and which is active. `.env` itself is the `default` profile.

Prefer picking the account at startup instead? Register the server twice (e.g. `hwc-work`, `hwc-personal`), each with `MCP_HWC_ENV_FILE` pointing at a different file.

## How it works

The server offers tools in three layers, and the assistant picks the highest one that fits:

1. **Discovery** — `huaweicloud_list_services`, `huaweicloud_summarize_capabilities`, `huaweicloud_resolve_defaults`: find out what's possible and get least-input defaults.
2. **Workflow helpers** — one-call tools for common jobs: `ecs_create_vm`, `obs_*` (object storage), `ssh_*`, `swr_upload_image`, `functiongraph_deploy_code`, `lts_query_logs`, `cce_get_kubeconfig`, `k8s_*`, `helm_*`, `price_*` (quotes and pricing), `mrs_*` (Hive/Spark SQL, jobs, and node/component CLIs on MRS clusters; normal-mode clusters, SSH defaults via `MRS_SSH_USER`/`MRS_SSH_KEY`/`MRS_SSH_PASSWORD`).
3. **Generic SDK access** — `huaweicloud_list_operations` / `describe_operation` / `call_operation` can call any operation of any supported Huawei Cloud SDK, for the cases no helper covers.

Coverage spans 70+ services (ECS, CCE, RDS, OBS, VPC, MRS, DMS, and more) with aliases like `geminidb` → `gaussdb_nosql`. Not wired: ModelArts core and CCI (no published Python SDKs). `kubectl` and `helm` run from local binaries or fall back to a container, so your machine doesn't need them installed.

## Development

```bash
uv run pytest
```
