import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import json
import unittest
import skill_logic

class TestSkillLogicRun(unittest.TestCase):

    def test_defective_api(self):
        """Tests an API structure expected to fail multiple checks (Example 'defective-api')."""
        input_json = '{"openapi": "3.0.0", "info": {"title": "Pets", "version": "1"}, "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}, "post": {"operationId": "addPet", "responses": {"201": {"description": "created"}, "400": {"description": "bad"}}}}}}'
        result = skill_logic.run(input_json)

        self.assertEqual(result['issue_count'], 3)
        
        issues = result['issues']
        
        # Check for missing-operation-id (GET /pets)
        self.assertTrue(any(issue['rule'] == 'missing-operation-id' and issue['path'] == 'GET /pets' for issue in issues))
        
        # Check for no-error-response (GET /pets)
        self.assertTrue(any(issue['rule'] == 'no-error-response' and issue['path'] == 'GET /pets' for issue in issues))
        
        # Check for no-security (Top level missing, and no operation defines it)
        self.assertTrue(any(issue['rule'] == 'no-security' for issue in issues))

    def test_clean_api(self):
        """Tests an API structure expected to pass all checks (Example 'clean-api')."""
        input_json = '{"openapi": "3.0.0", "info": {"title": "Pets", "version": "1"}, "security": [{"key": []}], "paths": {"/pets": {"get": {"operationId": "listPets", "responses": {"200": {"description": "ok"}, "default": {"description": "err"}}}}}}'
        result = skill_logic.run(input_json)

        self.assertEqual(result['issue_count'], 0)
        self.assertEqual(len(result['issues']), 0)

    def test_not_json(self):
        """Tests invalid JSON input (Example 'not-json')."""
        input_text = 'this is { not json'
        result = skill_logic.run(input_text)

        self.assertEqual(result['issue_count'], 1)
        self.assertEqual(result['issues'][0]['rule'], 'invalid-json')
        self.assertEqual(result['issues'][0]['path'], 'N/A')

    def test_path_format_error(self):
        """Tests a specific path format error (no error response) (Example 'path-format')."""
        input_json = '{"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "security": [{"k": []}], "paths": {"/pets/{id}": {"delete": {"operationId": "d", "responses": {"200": {"description": "ok"}}}}}}'
        result = skill_logic.run(input_json)

        self.assertEqual(result['issue_count'], 1)
        
        issues = result['issues']
        
        # Check for no-error-response on DELETE /pets/{id}
        self.assertTrue(any(issue['rule'] == 'no-error-response' and issue['path'] == 'DELETE /pets/{id}' for issue in issues))
        
        # Ensure no other rules are triggered (e.g., no-security is covered by top-level security)
        self.assertEqual(len(issues), 1)

    def test_missing_operation_id_and_security(self):
        """Tests missing operationId and no top-level security."""
        # This structure has:
        # 1. No top-level security -> no-security issue
        # 2. GET /pets has no operationId -> missing-operation-id issue
        # 3. GET /pets only has 200, no 4xx/5xx/default -> no-error-response issue
        # Expected count: 3
        input_json = '{"openapi": "3.0.0", "info": {"title": "Test", "version": "1"}, "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}}}'
        result = skill_logic.run(input_json)

        self.assertEqual(result['issue_count'], 3)
        
        issues = result['issues']
        
        # Check for missing-operation-id
        self.assertTrue(any(issue['rule'] == 'missing-operation-id' and issue['path'] == 'GET /pets' for issue in issues))
        
        # Check for no-error-response
        self.assertTrue(any(issue['rule'] == 'no-error-response' and issue['path'] == 'GET /pets' for issue in issues))
        
        # Check for no-security
        self.assertTrue(any(issue['rule'] == 'no-security' for issue in issues))

    def test_multiple_issues_combined(self):
        """Tests a scenario triggering multiple distinct rules."""
        # This structure has:
        # 1. No top-level security -> no-security issue
        # 2. POST /items has no operationId -> missing-operation-id issue
        # 3. POST /items only has 201, no 4xx/5xx/default -> no-error-response issue
        input_json = '{"openapi": "3.0.0", "info": {"title": "Test", "version": "1"}, "paths": {"/items": {"post": {"responses": {"201": {"description": "created"}}}}}}'
        result = skill_logic.run(input_json)

        self.assertEqual(result['issue_count'], 3)
        
        issues = result['issues']
        
        # Check for missing-operation-id
        self.assertTrue(any(issue['rule'] == 'missing-operation-id' and issue['path'] == 'POST /items' for issue in issues))
        
        # Check for no-error-response
        self.assertTrue(any(issue['rule'] == 'no-error-response' and issue['path'] == 'POST /items' for issue in issues))
        
        # Check for no-security
        self.assertTrue(any(issue['rule'] == 'no-security' for issue in issues))
