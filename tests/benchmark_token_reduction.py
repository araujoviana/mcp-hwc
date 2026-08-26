from __future__ import annotations

import json

from mcp_hwc.core.config import CloudApiConfig
from mcp_hwc.core.sdk_service import HuaweiCloudSdkService, render_dense_type_schema


def run_comprehensive_token_benchmark() -> dict[str, object]:
    config = CloudApiConfig(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        project_id="project-123",
        region="sa-brazil-1",
    )

    benchmark_ops = [
        ("ecs", "create_servers", "CreateServersRequest"),
        ("rds", "create_instance", "CreateInstanceRequest"),
        ("vpc", "create_vpc", "CreateVpcRequest"),
        ("cce", "create_cluster", "CreateClusterRequest"),
        ("elb", "create_load_balancer", "CreateLoadBalancerRequest"),
        ("nat", "create_nat_gateway", "CreateNatGatewayRequest"),
        ("kms", "create_key", "CreateKeyRequest"),
        ("lts", "create_log_stream", "CreateLogStreamRequest"),
    ]

    results = []
    total_raw = 0
    total_dense = 0

    for svc_name, op_name, req_model in benchmark_ops:
        svc = HuaweiCloudSdkService(config, svc_name)
        desc = svc.describe_operation(op_name, dense_only=False)

        raw_ast_len = len(json.dumps(desc["request_schema"])) + len(
            json.dumps(desc["request_template"])
        )
        dense_str = render_dense_type_schema(svc, req_model, max_depth=3)
        dense_len = len(dense_str)

        reduction = (1.0 - (dense_len / raw_ast_len)) * 100.0
        total_raw += raw_ast_len
        total_dense += dense_len

        results.append(
            {
                "service": svc_name,
                "operation": op_name,
                "raw_ast_chars": raw_ast_len,
                "dense_chars": dense_len,
                "reduction_pct": round(reduction, 2),
            }
        )

    overall_reduction = (1.0 - (total_dense / total_raw)) * 100.0

    print("\n" + "=" * 80)
    print("HUAWEI CLOUD MCP — COMPREHENSIVE TOKEN OPTIMIZATION BENCHMARK PROOF")
    print("=" * 80)
    print(
        f"{'SERVICE':<10} | {'OPERATION':<25} | {'RAW AST':<12} | {'DENSE TS':<12} | {'REDUCTION':<10}"
    )
    print("-" * 80)
    for r in results:
        print(
            f"{r['service']:<10} | {r['operation']:<25} | {r['raw_ast_chars']:<12} | {r['dense_chars']:<12} | {r['reduction_pct']}%"
        )
    print("=" * 80)
    print(f"TOTAL ACROSS ALL TESTED SERVICES: Raw = {total_raw} chars, Dense = {total_dense} chars")
    print(f"OVERALL EMPIRICAL TOKEN REDUCTION: {overall_reduction:.2f}%\n")

    return {
        "results": results,
        "total_raw": total_raw,
        "total_dense": total_dense,
        "overall_reduction_pct": round(overall_reduction, 2),
    }


if __name__ == "__main__":
    run_comprehensive_token_benchmark()
