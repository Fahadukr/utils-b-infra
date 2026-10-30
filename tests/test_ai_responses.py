import json
import unittest
from unittest.mock import patch

import httpx
import openai

from utils_b_infra.ai import TextGenerator


class TextGeneratorResponsesTest(unittest.TestCase):
    """Exercise the public helper through real SDK request serialization."""

    def setUp(self):
        self.requests = []
        self.statuses = []
        self.output_text = '{"command": "answer", "answer": "Hello!"}'
        self.client = openai.OpenAI(
            api_key="synthetic-test-key",
            base_url="https://api.openai.test/v1",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self.respond)),
        )
        self.generator = TextGenerator(self.client)

    def tearDown(self):
        self.client.close()

    def respond(self, request):
        self.assertEqual(str(request.url), "https://api.openai.test/v1/responses")
        self.assertEqual(request.method, "POST")
        body = json.loads(request.content)
        self.requests.append(body)
        self.assertTrue(body["input"], "Responses requires a nonempty input")
        if body["text"]["format"]["type"] == "json_object":
            self.assertIn("json", json.dumps(body["input"]).lower(),
                          "JSON mode checks input messages, not instructions")
        status = self.statuses.pop(0) if self.statuses else 200
        if status != 200:
            return httpx.Response(status, json={"error": {
                "message": "Synthetic provider error",
                "type": "invalid_request_error",
                "code": "unsupported_parameter" if status == 400 else None,
                "param": "temperature" if status == 400 else None,
            }})
        return httpx.Response(200, json={
            "id": "resp_synthetic_test",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": body["model"],
            "output": [{
                "id": "msg_synthetic_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{
                    "type": "output_text",
                    "text": self.output_text,
                    "annotations": [],
                }],
            }],
        })

    def test_hakim_reasoning_request_omits_sampling_options(self):
        answer = self.generator.generate_ai_response(
            prompt="Return a JSON object with command and answer.",
            user_text=[{"role": "user", "content": "Hi!"}],
            gpt_model="gpt-6.1-sol",
            reasoning_effort="high",
            json_mode=True,
        )

        self.assertEqual(answer, {"command": "answer", "answer": "Hello!"})
        body = self.requests[0]
        self.assertEqual(body["model"], "gpt-6.1-sol")
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertFalse(body["store"])
        self.assertNotIn("temperature", body)
        self.assertNotIn("max_output_tokens", body)

    def test_unrecognized_model_and_effort_need_no_registry(self):
        self.generator.generate_ai_response(
            prompt="Return JSON.", gpt_model="future-model-2027",
            reasoning_effort="future-effort", verbosity="low", json_mode=True,
        )

        body = self.requests[0]
        self.assertEqual(body["model"], "future-model-2027")
        self.assertEqual(body["reasoning"], {"effort": "future-effort"})
        self.assertEqual(body["text"]["verbosity"], "low")
        self.assertNotIn("temperature", body)

    def test_omitted_options_use_api_defaults_for_every_model(self):
        for model in ("gpt-4.1", "gpt-5", "o3", "future-model-2027"):
            with self.subTest(model=model):
                self.generator.generate_ai_response(prompt="Hello", gpt_model=model)
                body = self.requests[-1]
                self.assertEqual(body, {
                    "model": model,
                    "input": [{
                        "role": "developer",
                        "content": [{"type": "input_text", "text": "Hello"}],
                    }],
                    "store": False,
                    "text": {"format": {"type": "text"}},
                })

    def test_explicit_sampling_options_and_store_are_preserved(self):
        self.output_text = "plain text"
        answer = self.generator.generate_ai_response(
            prompt="Answer briefly.", user_text="Hi!", gpt_model="gpt-4.1",
            temperature=0, max_output_tokens=100, store=True,
        )

        self.assertEqual(answer, "plain text")
        body = self.requests[0]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_output_tokens"], 100)
        self.assertTrue(body["store"])
        self.assertNotIn("reasoning", body)
        self.assertNotIn("verbosity", body["text"])
        self.assertEqual(body["input"][1:], [{
            "role": "user", "content": [{"type": "input_text", "text": "Hi!"}],
        }])

    def test_reasoning_token_limit_is_honored(self):
        self.generator.generate_ai_response(
            prompt="Return JSON.", gpt_model="gpt-6.1-sol",
            reasoning_effort="high", max_output_tokens=2048,
        )

        self.assertEqual(self.requests[0]["max_output_tokens"], 2048)
        self.assertEqual(self.requests[0]["reasoning"], {"effort": "high"})

    def test_structured_user_input_stays_serialized_as_user_text(self):
        history = [{"role": "system", "content": "Remember this"},
                   {"role": "user", "content": "Hi!"}]
        self.generator.generate_ai_response(prompt="Return JSON.", user_text=history)

        body = self.requests[0]
        self.assertEqual(body["input"][0]["content"][0]["text"], "Return JSON.")
        self.assertEqual(body["input"][0]["role"], "developer")
        self.assertEqual(json.loads(body["input"][1]["content"][0]["text"]), history)
        self.assertEqual(body["input"][1]["role"], "user")

    def test_legacy_literal_json_parser_and_empty_text_are_preserved(self):
        self.output_text = "{'answer': 'Hello!'}"
        self.assertEqual(self.generator.generate_ai_response(
            prompt="Return JSON.", json_mode=True,
        ), {"answer": "Hello!"})
        self.output_text = "''"
        self.assertEqual(self.generator.generate_ai_response(prompt="Hello"), "")

    @patch("utils_b_infra.generic.time.sleep")
    def test_permanent_api_errors_propagate_once_without_backoff(self, sleep):
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                self.statuses = [status]
                before = len(self.requests)
                with self.assertRaises(openai.APIStatusError) as caught:
                    self.generator.generate_ai_response(prompt="Hello")
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(len(self.requests), before + 1)
        sleep.assert_not_called()

    @patch("utils_b_infra.generic.time.sleep")
    def test_rejected_explicit_setting_is_not_silently_removed(self, sleep):
        self.statuses = [400]
        with self.assertRaises(openai.BadRequestError) as caught:
            self.generator.generate_ai_response(
                prompt="Hello", gpt_model="gpt-6.1-sol",
                reasoning_effort="high", temperature=0.5,
            )

        self.assertEqual(caught.exception.param, "temperature")
        self.assertEqual(self.requests[0]["temperature"], 0.5)
        self.assertEqual(len(self.requests), 1)
        sleep.assert_not_called()

    @patch("utils_b_infra.generic.time.sleep")
    def test_transient_api_errors_still_retry(self, sleep):
        for status in (408, 409, 429, 500, 503):
            with self.subTest(status=status):
                self.statuses = [status, 200]
                before = len(self.requests)
                self.generator.generate_ai_response(prompt="Hello")
                self.assertEqual(len(self.requests), before + 2)
        self.assertEqual(sleep.call_count, 5)


if __name__ == "__main__":
    unittest.main()
