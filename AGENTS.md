# Agent Notes

- Required environment variables: `HWC_AK` and `HWC_SK`.
- Optional credential environment variable: `HWC_SECURITY_TOKEN` for temporary credentials.
- Do not require users to set `HWC_REGION`, `HWC_PROJECT_ID`, `HWC_ECS_*`, `HWC_RDS_*`, or `HWC_OBS_*` in normal agent flows.
- Region should come from user input, the tool call arguments, the request payload when available, or endpoint inference.
- Common human region aliases such as `santiago` and `sao paulo` should be accepted and normalized to Huawei region codes automatically.
- `project_id` should be resolved automatically by the Huawei SDK through IAM when the region is known. If automatic resolution is ambiguous, prefer an explicit `project_id` tool argument instead of asking for an env var.
- For ECS provisioning flows, use `vpc_*` tools to discover or create VPC, subnet, route, and security-group prerequisites, and use `ims_*` tools to discover the image to boot from.
- For RDS provisioning flows, use `vpc_*` tools for networking prerequisites before calling `rds_*` operations.
- OBS bucket and object operations should prefer bucket-region discovery or explicit `region` arguments instead of extra env configuration.
