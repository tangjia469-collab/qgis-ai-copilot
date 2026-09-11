import json
import unittest

from qgis_ai_copilot.protocol import ProtocolError, ResponsesStream


class ExecutionProtocolTests(unittest.TestCase):
    def decoder(self):
        try:
            return ResponsesStream(allow_tools=True)
        except TypeError:
            self.fail("Execute mode needs an explicitly enabled tool-call decoder")

    def test_completed_tool_only_response_is_handoff_not_empty_answer(self):
        stream = self.decoder()
        call = {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "inspect_project",
            "arguments": "{}",
        }
        output = [
            {
                "type": "reasoning",
                "id": "r1",
                "summary": [],
                "encrypted_content": "OPAQUE_CONTINUATION",
            },
            call,
        ]
        events = stream.feed(
            json.dumps(
                {
                    "type": "response.completed",
                    "response": {"status": "completed", "output": output},
                }
            )
        )
        handoff = [value for kind, value in events if kind == "tool_calls"]
        self.assertEqual(len(handoff), 1)
        self.assertEqual(handoff[0]["calls"], [call])
        self.assertEqual(
            handoff[0]["output"],
            [
                {"type": "reasoning", "id": "r1", "encrypted_content": "OPAQUE_CONTINUATION", "summary": []},
                {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "inspect_project", "arguments": "{}"},
            ],
        )
        self.assertTrue(stream.completed)
        self.assertEqual(stream.answer, "")

    def test_chat_mode_does_not_enable_model_tools(self):
        stream = ResponsesStream()
        with self.assertRaises(ProtocolError):
            stream.feed(
                json.dumps(
                    {
                        "type": "response.completed",
                        "response": {
                            "output": [
                                {
                                    "type": "function_call",
                                    "call_id": "c",
                                    "name": "inspect_project",
                                    "arguments": "{}",
                                }
                            ]
                        },
                    }
                )
            )

    def test_partial_call_events_never_dispatch(self):
        stream = self.decoder()
        for event in [
            {"type": "response.function_call_arguments.delta", "delta": "{bad"},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "x",
                    "name": "inspect_project",
                    "arguments": "{}",
                },
            },
        ]:
            self.assertFalse(
                any(kind == "tool_calls" for kind, _ in stream.feed(json.dumps(event)))
            )

    def test_cancelled_or_pending_responses_never_dispatch_tools(self):
        for status in ("cancelled", "in_progress", "queued", "failed", "incomplete"):
            with self.subTest(status=status), self.assertRaises(ProtocolError):
                self.decoder().feed(json.dumps({
                    "type": "response.completed",
                    "response": {"status": status, "output": [{
                        "type": "function_call", "call_id": "c",
                        "name": "inspect_project", "arguments": "{}",
                    }]},
                }))

    def test_continuation_keeps_public_commentary_and_reasoning_summary(self):
        note = {"type": "message", "id": "m1", "role": "assistant", "phase": "commentary",
                "content": [{"type": "output_text", "text": "Checking the layer."}]}
        reason = {"type": "reasoning", "id": "r1", "encrypted_content": "OPAQUE", "summary": []}
        call = {"type": "function_call", "call_id": "c", "name": "inspect_project", "arguments": "{}"}
        stream = self.decoder()
        stream.feed(json.dumps({"type": "response.completed", "response": {
            "status": "completed", "output": [note, reason, call],
        }}))
        self.assertEqual(stream.handoff["output"], [note, reason, call])

    def test_continuation_strips_undocumented_private_fields(self):
        output = [
            {"type": "reasoning", "id": "r1", "summary": [], "encrypted_content": "OPAQUE", "reasoning_text": "PRIVATE_RAW", "custom": "PRIVATE_METADATA"},
            {"type": "function_call", "call_id": "c", "name": "inspect_project", "arguments": "{}", "custom": "PRIVATE_CALL"},
        ]
        stream = self.decoder()
        stream.feed(json.dumps({"type": "response.completed", "response": {"output": output}}))
        self.assertNotIn("PRIVATE_", json.dumps(stream.handoff))
        self.assertIn("OPAQUE", json.dumps(stream.handoff["output"]))
        with self.assertRaises(ProtocolError):
            stream.feed(
                json.dumps(
                    {"type": "response.failed", "response": {"error": {"message": "broken"}}}
                )
            )

    def test_oversize_or_duplicate_call_identity_is_rejected(self):
        for calls in [
            [{"type": "function_call", "name": "inspect_project", "arguments": "{}"}],
            [
                {
                    "type": "function_call",
                    "call_id": "c",
                    "name": "inspect_project",
                    "arguments": "x" * 17000,
                }
            ],
            [
                {
                    "type": "function_call",
                    "call_id": "c",
                    "name": "inspect_project",
                    "arguments": "{}",
                }
            ]
            * 2,
        ]:
            with self.subTest(calls=len(calls)), self.assertRaises(ProtocolError):
                self.decoder().feed(
                    json.dumps({"type": "response.completed", "response": {"output": calls}})
                )


if __name__ == "__main__":
    unittest.main()
