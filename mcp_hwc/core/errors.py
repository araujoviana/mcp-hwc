from __future__ import annotations

import re


class HelperToolError(RuntimeError):
    """Raised when a direct convenience tool cannot complete locally."""


# Huawei Cloud's documented fine-grained IAM permission format is
# "{Service}:{Resource}:{Action}" (e.g. "ecs:servers:list", "obs:bucket:GetBucketPolicy").
# https://support.huaweicloud.com/intl/en-us/productdesc-iam/iam_01_0001.html
_POLICY_ACTION_PATTERN = re.compile(r"\b[a-z][a-zA-Z0-9]*:[A-Za-z][\w]*:[A-Za-z][\w]*\b")

_IAM_CONSOLE_URL = "https://console.huaweicloud.com/iam/#/iam/users"


def is_access_denied(
    status_code: int | None,
    error_code: str | None,
    error_msg: str | None,
) -> bool:
    """Best-effort detection of an IAM/permission-denied SDK response."""
    if status_code == 403:
        return True
    haystack = f"{error_code or ''} {error_msg or ''}".casefold()
    return any(t in haystack for t in ("access denied", "forbidden", "no permission", "not authorized"))


def build_access_denied_hint(
    *,
    service_display_name: str,
    operation: str,
    error_code: str | None,
    error_msg: str | None,
) -> str:
    """Surface an IAM policy action embedded in the SDK's own error text when present;
    otherwise point at the failing service/operation and the IAM console. Does not
    fabricate a permission name that the SDK did not report."""
    match = _POLICY_ACTION_PATTERN.search(f"{error_code or ''} {error_msg or ''}")
    if match:
        return (
            f"Huawei Cloud IAM denied this request. Grant policy action "
            f"'{match.group(0)}' to the caller's IAM policy/agency, then retry."
        )
    return (
        f"Huawei Cloud IAM denied the '{operation}' call to {service_display_name} "
        f"(error_code={error_code or 'unknown'}). The response did not include a specific "
        f"policy action, so check the account's custom IAM policies for this service in "
        f"the console ({_IAM_CONSOLE_URL}) and grant the narrowest role that covers "
        f"'{operation}'."
    )
