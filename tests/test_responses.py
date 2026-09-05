import json
import unittest

from qgis_ai_copilot import protocol
from tests.test_attachments import ONE_PIXEL_PNG_URL


class ResponsesTests(unittest.TestCase):
    def builder(self):
        self.assertTrue(hasattr(protocol, "build_responses_payload"), "Missing Responses activity adapter")
        return protocol.build_responses_payload

    def decoder(self):
        self.assertTrue(hasattr(protocol, "ResponsesStream"), "Missing Responses stream decoder")
        return protocol.ResponsesStream()

    def test_payload_preserves_model_messages_images_and_summary_opt_in(self):
        build = self.builder()
        messages = [{"role":"system","content":"Only inspect attached evidence."}, {"role":"assistant","content":"Earlier answer"}, {"role":"user","content":[{"type":"text","text":"Inspect"}, {"type":"image_url","image_url":{"url":ONE_PIXEL_PNG_URL}}]}]
        payload = build("original-model", messages, "Max", True, True)
        self.assertEqual(payload["model"], "original-model")
        self.assertEqual(payload["instructions"], "Only inspect attached evidence.")
        self.assertEqual(payload["input"][0], {"role":"assistant","content":"Earlier answer"})
        self.assertEqual(payload["input"][1]["content"][1], {"type":"input_image","image_url":ONE_PIXEL_PNG_URL})
        self.assertEqual(payload["reasoning"], {"effort":"max","summary":"auto"})
        self.assertFalse(payload["store"])
        automatic = build("original-model", [{"role":"user","content":"Hello"}], "Auto", True, False)
        self.assertNotIn("reasoning", automatic)

    def test_summary_and_commentary_are_distinct_from_final_answer(self):
        stream = self.decoder()
        events = [
            {"type":"response.created"},
            {"type":"response.output_item.added","output_index":0,"item":{"id":"note","type":"message","phase":"commentary","content":[]}},
            {"type":"response.output_text.delta","output_index":0,"item_id":"note","delta":"I will check the CRS."},
            {"type":"response.reasoning_summary_text.delta","item_id":"reason","summary_index":0,"delta":"Checking coordinate units"},
            {"type":"response.reasoning_text.delta","item_id":"reason","delta":"DO_NOT_DISPLAY_RAW_REASONING"},
            {"type":"response.output_item.added","output_index":2,"item":{"id":"answer","type":"message","phase":"final_answer","content":[]}},
            {"type":"response.output_text.delta","output_index":2,"item_id":"answer","delta":"Use a projected CRS."},
            {"type":"response.reasoning_summary_text.done","item_id":"reason","summary_index":0,"text":"Checking coordinate units"},
            {"type":"response.completed","response":{"status":"completed","output":[{"id":"note","type":"message","phase":"commentary","content":[{"type":"output_text","text":"I will check the CRS."}]},{"id":"answer","type":"message","phase":"final_answer","content":[{"type":"output_text","text":"Use a projected CRS."}]}]}}
        ]
        results = [value for event in events for value in stream.feed(json.dumps(event))]
        self.assertEqual(stream.answer, "Use a projected CRS.")
        activities = [value for kind,value in results if kind=="activity"]
        self.assertTrue(any(value["kind"]=="commentary" and value["text"]=="I will check the CRS." for value in activities))
        self.assertTrue(any(value["kind"]=="summary" and "coordinate units" in value["text"] for value in activities))
        self.assertNotIn("DO_NOT_DISPLAY", str(results))
        self.assertNotIn("CRS.", "".join(value for kind,value in results if kind=="delta").replace("Use a projected CRS.", ""))
        self.assertEqual(results[-1][0], "completed")

    def test_failure_and_incomplete_keep_partial_text(self):
        for event_type in ("response.failed", "response.incomplete"):
            with self.subTest(type=event_type):
                stream=self.decoder()
                stream.feed(json.dumps({"type":"response.output_text.delta","output_index":0,"item_id":"answer","delta":"Partial"}))
                with self.assertRaises(protocol.ProtocolError):
                    stream.feed(json.dumps({"type":event_type,"response":{"error":{"message":"fixture failed"},"incomplete_details":{"reason":"max_output_tokens"}}}))
                self.assertEqual(stream.answer,"Partial")

    def test_raw_reasoning_fields_are_not_exposed_from_completed_snapshot(self):
        stream=self.decoder()
        events=stream.feed(json.dumps({"type":"response.completed","response":{"status":"completed","output":[{"type":"reasoning","id":"r","encrypted_content":"PRIVATE_BLOB","content":[{"type":"reasoning_text","text":"PRIVATE_RAW"}],"summary":[{"type":"summary_text","text":"Safe public summary"}]},{"type":"message","id":"m","content":[{"type":"output_text","text":"Answer"}]}]}}))
        self.assertEqual(stream.answer,"Answer")
        self.assertIn("Safe public summary",str(events))
        self.assertNotIn("PRIVATE_",str(events))

    def test_empty_and_malformed_responses_are_not_success(self):
        stream=self.decoder()
        with self.assertRaises(protocol.ProtocolError):
            stream.feed("not json")
        with self.assertRaises(protocol.ProtocolError):
            stream.feed(json.dumps({"type":"response.completed","response":{"status":"completed","output":[]}}))


if __name__=="__main__":
    unittest.main()
