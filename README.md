<img src="docs/assets/logo.png" alt="mcp-hwc logo" width="96" height="96">

# mcp-hwc

Control Huawei Cloud from an AI assistant. `mcp-hwc` is an **MCP server**: it exposes Huawei Cloud as tools an assistant like Claude Code or OpenCode can call directly, so you provision a VM, deploy a function, or tail a cluster's logs by just asking, instead of hand-rolling SDK calls or clicking through the console.

It wraps 75+ Huawei Cloud SDKs and 3,000+ API operations, but the assistant only ever sees a small, curated surface: a handful of workflow tools for the jobs people actually do, backed by a generic reflection layer for everything else. That split is deliberate: it keeps the tool catalog cheap enough to fit in an agent's context every turn, instead of eating half the window before the conversation even starts.

> **⚠️ This creates real, billable cloud resources.** Every VM, cluster, or bucket the assistant provisions costs money and keeps costing money until you tear it down. Review what a tool call is about to do before approving it, and don't run this in a fully auto-approve mode unless you genuinely don't care what gets created or what it costs.

## New to MCP?

MCP (Model Context Protocol) is how AI assistants talk to external systems. An MCP server is a small program that runs on your machine and exposes "tools" (like `ecs_create_vm`) that the assistant can call on your behalf.

You never call these tools yourself. You tell your assistant *"create a small Ubuntu VM in São Paulo"*, and it picks the right tool, fills in sensible defaults, and asks you only when a choice really matters (cost, region, security).

## Quick start

You need [uv](https://docs.astral.sh/uv/) installed, and a Huawei Cloud **Access Key** (AK) and **Secret Key** (SK). Create them in the Huawei Cloud console under *My Credentials → Access Keys*.

```bash
# 1. Get the code and install dependencies
git clone https://github.com/araujoviana/mcp-hwc && cd mcp-hwc
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

## Configuration

Set these in `.env` (or export them):

| Variable | Required | What it is |
|---|---|---|
| `HWC_AK` | yes | Access Key ID |
| `HWC_SK` | yes | Secret Access Key |
| `HWC_SECURITY_TOKEN` | no | Only for temporary credentials |
| `HWC_REGION`, `HWC_PROJECT_ID` | no | Usually resolved automatically from your request and IAM |
| `MCP_HWC_ENABLE_SERVICE_TOOLS` | no | Expose per-service SDK tools (`all` or e.g. `ecs,vpc`); hidden by default to keep the assistant's context small |

### Multiple accounts

Keep one credential file per account next to `.env`: e.g. `.env.work`, `.env.personal` (same format as `.env`; they are gitignored). Then just ask your assistant:

> "Switch to my work account"

It calls `hwc_switch_profile("work")` and every later call uses that account, no restart needed. `hwc_list_profiles` shows what's available and which is active. `.env` itself is the `default` profile.

Prefer picking the account at startup instead? Register the server twice (e.g. `hwc-work`, `hwc-personal`), each with `MCP_HWC_ENV_FILE` pointing at a different file.

## What can I ask for?

- *"Create a small Debian VM in Santiago I can SSH into"* → provisions the VPC, subnet, security group, and server, and returns the IP
- *"Deploy this folder as a FunctionGraph function"*
- *"Push this Docker image to SWR"*
- *"Get the kubeconfig for my CCE cluster and show failing pods"*
- *"Query the LTS logs of my app for errors in the last hour"*
- *"Run `SHOW DATABASES` in Hive on my MRS cluster"* or *"list the Kafka topics on cluster analytics"*

## How it works

The server offers tools in three layers, and the assistant picks the highest one that fits:

1. **Discovery** — `huaweicloud_list_services`, `huaweicloud_summarize_capabilities`, `huaweicloud_resolve_defaults`: find out what's possible and get least-input defaults.
2. **Workflow helpers** — one-call tools for common jobs: `ecs_create_vm`, `obs_*` (object storage), `ssh_*`, `swr_upload_image`, `functiongraph_deploy_code`, `lts_query_logs`, `cce_get_kubeconfig`, `k8s_*`, `helm_*`, `mrs_*` (Hive/Spark SQL, jobs, and node/component CLIs on MRS clusters).
3. **Generic SDK access** — `huaweicloud_list_operations` / `describe_operation` / `call_operation` can call any operation of any supported Huawei Cloud SDK, for the cases no helper covers.

Coverage spans 75+ services (ECS, CCE, RDS, OBS, VPC, MRS, DMS, and more) with aliases like `geminidb` → `gaussdb_nosql`. Not wired: ModelArts core and CCI (no published Python SDKs). `kubectl` and `helm` run from local binaries or fall back to a container, so your machine doesn't need them installed.

## Highlights

- **Small context footprint.** The generic SDK layer renders dense, TypeScript-style schemas instead of raw SDK ASTs (~83% smaller), supports response field projection to strip hypervisor/API noise, and can format list results as Markdown tables instead of nested JSON. Benchmarked in `tests/test_stream2_token_optimization.py`.
- **Hardened by default.** SSH connections verify host keys against `known_hosts` and reject unknown hosts unless explicitly allowed; secrets are masked in config `repr()` and CLI error output; shell arguments are quoted before reaching SSH/subprocess calls; SFS shares default to `root_squash`.

## Development

```bash
uv run pytest   # 161 tests
```

`ruff` is configured in `pyproject.toml` for linting and formatting.
