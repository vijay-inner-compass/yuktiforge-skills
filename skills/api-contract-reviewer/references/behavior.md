# Behaviour of api-contract-reviewer

Rules the skill applies, as specified:

1. Attempt to parse the input JSON file to check for the `invalid-json` rule.
2. Check if the document contains a top-level `security` field; if not, and no operation defines its own security, report the `no-security` rule.
3. Iterate through all defined operations within the document to check for the `missing-operation-id` rule.
4. For every operation, check if it declares any 4xx, 5xx, or default response to report the `no-error-response` rule if none are present.
5. Construct the final JSON output containing the total count of reported issues and an array detailing each issue with its rule, path, and message.

## Assumptions

- none
