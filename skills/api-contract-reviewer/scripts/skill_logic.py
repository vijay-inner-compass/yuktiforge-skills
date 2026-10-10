import json
from typing import Dict, Any, List

def run(text: str) -> Dict[str, Any]:
    """
    Reviews an OpenAPI 3 document provided as a JSON string to identify common contract problems.
    """
    issues: List[Dict[str, str]] = []
    doc: Dict[str, Any] = {}

    # 1. Attempt to parse the input JSON file to check for the invalid-json rule.
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return {
            "issue_count": 1,
            "issues": [
                {
                    "rule": "invalid-json",
                    "path": "N/A",
                    "message": "The provided text is not valid JSON."
                }
            ]
        }

    if not isinstance(doc, dict):
        # If the root element is not a dictionary (e.g., it's a list or primitive)
        return {
            "issue_count": 1,
            "issues": [
                {
                    "rule": "invalid-json",
                    "path": "N/A",
                    "message": "The parsed JSON root element is not an object."
                }
            ]
        }

    # --- Rule 2: no-security ---
    has_top_level_security = "security" in doc and isinstance(doc["security"], list)
    has_operation_security = False
    
    paths = doc.get("paths")
    
    # Check for operation-level security
    if isinstance(paths, dict):
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if isinstance(operation, dict) and "security" in operation and isinstance(operation["security"], list):
                    has_operation_security = True
                    break
            if has_operation_security:
                break

    if not has_top_level_security and not has_operation_security:
        issues.append({
            "rule": "no-security",
            "path": "Document Level",
            "message": "The document lacks a top-level 'security' definition, and no operation defines its own security requirements."
        })

    # --- Rules 3 & 4: Iterating through operations ---
    if isinstance(paths, dict):
        for path_url, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            for method, operation in path_item.items():
                if not isinstance(method, str) or method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue
                
                if not isinstance(operation, dict):
                    continue

                # Construct path for reporting
                path_str = f"{method.upper()} {path_url}"

                # Rule 3: missing-operation-id
                if "operationId" not in operation or not operation["operationId"]:
                    issues.append({
                        "rule": "missing-operation-id",
                        "path": path_str,
                        "message": "Operation is missing the required 'operationId'."
                    })

                # Rule 4: no-error-response
                responses = operation.get("responses")
                has_error_response = False
                if isinstance(responses, dict):
                    response_keys = list(responses.keys())
                    # Check for 4xx, 5xx, or default
                    if any(key.startswith("4") or key.startswith("5") for key in response_keys):
                        has_error_response = True
                    if "default" in response_keys:
                        has_error_response = True
                
                if not has_error_response:
                    issues.append({
                        "rule": "no-error-response",
                        "path": path_str,
                        "message": "Operation does not declare any explicit 4xx, 5xx, or 'default' error response."
                    })

    return {
        "issue_count": len(issues),
        "issues": issues
    }
