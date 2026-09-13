from __future__ import annotations

import json

from mcp_hwc.cloud_services.compute import normal_azs_for_flavor


def approx_tokens(text: str) -> int:
    """Rough OpenAI/Anthropic/Gemini heuristic: ~4 chars per token."""
    return len(text) // 4


def benchmark():
    print("=" * 60)
    print("TOKEN REDUCTION BENCHMARK FOR MCP-HWC")
    print("=" * 60)

    # 1. ECS Flavors
    # Synthesize 500 OpenStack flavors with typical verbose extra specs
    raw_flavors = []
    for i in range(500):
        raw_flavors.append({
            "id": f"c6.{i}xlarge.4",
            "name": f"c6.{i}xlarge.4",
            "vcpus": "8",
            "ram": 16384,
            "os_extra_specs": {
                "cond:operation:status": "normal",
                "cond:operation:az": "sa-brazil-1a(normal),sa-brazil-1b(normal)",
                "quota:sub_network_interface_max_num": "4",
                "ecs:generation": "c6",
                "flavor:benchmark": "standard",
                "hw:numa_nodes": "1",
                "hw:cpu_policy": "dedicated",
                "pci_passthrough:enable_gpu": "false",
                "info:cpu:name": "Intel Cascade Lake",
            },
            "links": [
                {"rel": "self", "href": f"https://ecs.sa-brazil-1.myhuaweicloud.com/flavors/c6.{i}xlarge.4"},
                {"rel": "bookmark", "href": f"https://ecs.sa-brazil-1.myhuaweicloud.com/flavors/c6.{i}xlarge.4"}
            ]
        })

    raw_json = json.dumps(raw_flavors)
    raw_tokens = approx_tokens(raw_json)

    # Projected with limit=25
    projected = [
        {
            "id": f["id"],
            "name": f["name"],
            "vcpus": int(f.get("vcpus", 0)),
            "ram_gb": round(f.get("ram", 0) / 1024),
            "azs": normal_azs_for_flavor(f),
            "supports_eni": True,
        }
        for f in raw_flavors[:25]
    ]
    projected_json = json.dumps(projected)
    projected_tokens = approx_tokens(projected_json)

    print("\n1. ecs_list_compatible_flavors:")
    print(f"   Before (500 raw flavors):      {len(raw_json):>8} chars | ~{raw_tokens:>6} tokens")
    print(f"   After  (25 projected flavors): {len(projected_json):>8} chars | ~{projected_tokens:>6} tokens")
    reduction_pct = (1 - (projected_tokens / raw_tokens)) * 100
    print(f"   --> Reduction: {reduction_pct:.1f}%")

    # 2. System Instructions
    old_instructions = 2852
    from mcp_hwc.server import _MCP_INSTRUCTIONS
    new_instructions = len(_MCP_INSTRUCTIONS)
    print("\n2. Server FastMCP Instructions:")
    print(f"   Before: {old_instructions:>5} chars | ~{approx_tokens(str(old_instructions) * 4):>4} tokens")
    print(f"   After:  {new_instructions:>5} chars | ~{approx_tokens(_MCP_INSTRUCTIONS):>4} tokens")
    inst_reduction = (1 - (new_instructions / old_instructions)) * 100
    print(f"   --> Reduction: {inst_reduction:.1f}% per message turn")

    # 3. K8s Pod Listing (YAML vs Tabular)
    sample_pod_yaml = """
apiVersion: v1
items:
- apiVersion: v1
  kind: Pod
  metadata:
    creationTimestamp: "2026-09-13T10:00:00Z"
    generateName: coredns-56b68b449b-
    labels:
      k8s-app: kube-dns
      pod-template-hash: 56b68b449b
    name: coredns-56b68b449b-7x89v
    namespace: kube-system
    resourceVersion: "12345"
    uid: 49b6b801-b3b3-4f9e-a0e2-7634be94b05a
  spec:
    containers:
    - args:
      - -conf
      - /etc/coredns/Corefile
      image: registry.k8s.io/coredns/coredns:v1.10.1
      imagePullPolicy: IfNotPresent
      name: coredns
      resources:
        limits:
          memory: 170Mi
        requests:
          cpu: 100m
          memory: 70Mi
    nodeName: node-1
    restartPolicy: Always
  status:
    phase: Running
    podIP: 10.244.0.2
    startTime: "2026-09-13T10:00:05Z"
""" * 10
    sample_pod_table = """
NAME                                READY   STATUS    RESTARTS   AGE
coredns-56b68b449b-7x89v            1/1     Running   0          4h
""" * 10

    yaml_tokens = approx_tokens(sample_pod_yaml)
    table_tokens = approx_tokens(sample_pod_table)
    print("\n3. k8s_resource Pod Listing (10 pods):")
    print(f"   Before (YAML output):    {len(sample_pod_yaml):>6} chars | ~{yaml_tokens:>4} tokens")
    print(f"   After  (Tabular output): {len(sample_pod_table):>6} chars | ~{table_tokens:>4} tokens")
    k8s_reduction = (1 - (table_tokens / yaml_tokens)) * 100
    print(f"   --> Reduction: {k8s_reduction:.1f}%")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    benchmark()
