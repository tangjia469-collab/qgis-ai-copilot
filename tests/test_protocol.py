import json
import unittest
from tests.test_attachments import ONE_PIXEL_PNG_URL

from qgis_ai_copilot.protocol import (
    ProtocolError,
    SseDecoder,
    bounded_chat_history,
    build_chat_payload,
    classify_router_error,
    endpoint_url,
    normalized_external_link,
    parse_chat_response,
    parse_model_catalog,
    parse_sse_chat_data,
)


class ProtocolTests(unittest.TestCase):
    def test_endpoint_preserves_optional_v1_prefix(self):
        self.assertEqual(
            endpoint_url("https://router.example", "/v1/models"),
            "https://router.example/v1/models",
        )
        self.assertEqual(
            endpoint_url("https://router.example/v1/", "/v1/models"),
            "https://router.example/v1/models",
        )
        self.assertEqual(
            endpoint_url("https://router.example/proxy", "/v1/models"),
            "https://router.example/proxy/v1/models",
        )

    def test_invalid_base_url_is_rejected(self):
        with self.assertRaises(ProtocolError):
            endpoint_url("router.example", "/v1/models")
        with self.assertRaises(ProtocolError):
            endpoint_url("https://router.example?token=secret", "/v1/models")
        with self.assertRaises(ProtocolError):
            endpoint_url("http://router.example", "/v1/models")
        with self.assertRaises(ProtocolError):
            endpoint_url("https://user:secret@router.example", "/v1/models")
        self.assertEqual(
            endpoint_url("http://127.0.0.1:8000", "/v1/models"),
            "http://127.0.0.1:8000/v1/models",
        )

    def test_external_links_are_http_only_and_cannot_embed_credentials(self):
        normalized, host = normalized_external_link("https://docs.qgis.org/latest/en/")
        self.assertEqual(normalized, "https://docs.qgis.org/latest/en/")
        self.assertEqual(host, "docs.qgis.org")
        normalized, host = normalized_external_link("http://127.0.0.1:8765/help")
        self.assertEqual((normalized, host), ("http://127.0.0.1:8765/help", "127.0.0.1"))
        for value in (
            "file:///tmp/private.txt",
            "mailto:user@example.com",
            "qgis://open-project",
            "http://example.test/plaintext",
            "https://user:secret@example.com/",
            "https://example.com:bad/",
        ):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                normalized_external_link(value)

    def test_model_catalog_is_dynamic_and_deduplicated(self):
        records = parse_model_catalog(
            {
                "data": [
                    {
                        "id": "model-a",
                        "owned_by": "router",
                        "supported_reasoning_efforts": ["low", "x_high", "bogus"],
                    },
                    {"id": "model-a"},
                    {"id": "model-b"},
                ]
            }
        )
        self.assertEqual([record.id for record in records], ["model-a", "model-b"])
        self.assertEqual(records[0].explicit_thinking, ("Low", "XHigh"))
        self.assertEqual(records[1].explicit_thinking, ())

    def test_empty_or_malformed_catalog_is_not_silent(self):
        for payload in ({"data": []}, {"models": []}, b"not json"):
            with self.subTest(payload=payload):
                with self.assertRaises(ProtocolError):
                    parse_model_catalog(payload)

    def test_auto_omits_reasoning_and_configured_value_maps(self):
        messages = [{"role": "user", "content": "Hello"}]
        automatic = build_chat_payload("model-a", messages, "Auto", True)
        explicit = build_chat_payload("model-a", messages, "XHigh", False)
        self.assertNotIn("reasoning_effort", automatic)
        self.assertEqual(explicit["reasoning_effort"], "xhigh")
        self.assertFalse(explicit["stream"])

    def test_image_content_parts_are_preserved_for_multimodal_chat(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this screenshot?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": ONE_PIXEL_PNG_URL},
                    },
                ],
            }
        ]
        payload = build_chat_payload("vision-model", messages, "Auto", False)
        self.assertEqual(payload["messages"][0]["content"][1]["type"], "image_url")
        self.assertFalse(payload["stream"])

    def test_remote_or_unknown_image_parts_are_rejected(self):
        with self.assertRaises(ProtocolError):
            build_chat_payload(
                "vision-model",
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/image.png"},
                            }
                        ],
                    }
                ],
            )

    def test_malformed_or_mismatched_image_data_is_rejected(self):
        for url in ["data:image/png;base64,ZmFrZQ==", "data:image/png;base64,invalid!", "data:image/svg+xml;base64,AAAA", ONE_PIXEL_PNG_URL.replace("image/png", "image/jpeg")]:
            with self.subTest(url=url), self.assertRaises(ProtocolError):
                build_chat_payload("model", [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}])

    def test_model_image_capability_is_not_inferred_from_model_name(self):
        models = parse_model_catalog({"data": [{"id": "vision-name"}, {"id": "text", "input_modalities": ["text"]}, {"id": "visual", "architecture": {"input_modalities": ["text", "image"]}}]})
        self.assertIsNone(models[0].supports_images)
        self.assertIs(models[1].supports_images, False)
        self.assertIs(models[2].supports_images, True)

    def test_history_keeps_current_visual_message_and_bounds_images(self):
        visual = {"role": "user", "content": [{"type": "text", "text": "inspect"}, {"type": "image_url", "image_url": {"url": ONE_PIXEL_PNG_URL}}]}
        history = bounded_chat_history([visual] * 22, max_messages=25)
        self.assertEqual(len(history), 20)
        self.assertEqual(history[-1], visual)
        with self.assertRaises(ProtocolError):
            bounded_chat_history([{"role": "user", "content": "x" * 100}], max_characters=10)

    def test_chat_history_keeps_a_bounded_contiguous_tail(self):
        messages = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": str(index) * 10}
            for index in range(30)
        ]
        bounded = bounded_chat_history(messages, max_messages=5, max_characters=100)
        self.assertEqual(bounded, messages[-5:])
        bounded = bounded_chat_history(messages, max_messages=20, max_characters=40)
        self.assertEqual(bounded, messages[-2:])

    def test_nonstreaming_response(self):
        content, usage = parse_chat_response(
            {
                "choices": [{"message": {"role": "assistant", "content": "Answer"}}],
                "usage": {"total_tokens": 10},
            }
        )
        self.assertEqual(content, "Answer")
        self.assertEqual(usage["total_tokens"], 10)

    def test_sse_decoder_handles_split_utf8_and_events(self):
        first = 'data: {"choices":[{"delta":{"content":"Caf'.encode("utf-8")
        second = 'é"}}]}\n\ndata: [DONE]\n\n'.encode("utf-8")
        decoder = SseDecoder()
        events = []
        events.extend(decoder.feed(first + second[:1]))
        events.extend(decoder.feed(second[1:]))
        self.assertEqual(len(events), 2)
        self.assertEqual(parse_sse_chat_data(events[0]), ("delta", "Café"))
        self.assertEqual(parse_sse_chat_data(events[1]), ("done", None))
        self.assertFalse(decoder.has_incomplete_event)

    def test_stream_error_and_http_classification(self):
        event = json.dumps({"error": {"message": "reasoning_effort is unsupported"}})
        with self.assertRaises(ProtocolError):
            parse_sse_chat_data(event)
        self.assertEqual(
            classify_router_error(400, "reasoning_effort is unsupported"),
            "thinking_unsupported",
        )
        self.assertEqual(classify_router_error(401, "bad token"), "authentication")
        self.assertEqual(classify_router_error(429, "slow down"), "rate_limit")


if __name__ == "__main__":
    unittest.main()
