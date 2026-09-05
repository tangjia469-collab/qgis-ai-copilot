"""QGIS network smoke test against the deterministic local router."""

import json
import os
import sys
import tempfile
import threading

from qgis.PyQt.QtCore import QEventLoop, QTimer
from qgis.core import QgsApplication

from qgis_ai_copilot.network import RouterClient
from qgis_ai_copilot.protocol import RouterProfile, build_chat_payload
from tests.mock_router import FixtureHandler, start_fixture
from tests.test_attachments import ONE_PIXEL_PNG_URL
from tests.qgis_runtime import configure_prefix


def wait_for(signal, trigger, timeout_ms=5000):
    loop = QEventLoop()
    received = []

    def done(*args):
        received.append(args)
        loop.quit()

    signal.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    trigger()
    loop.exec_()
    try:
        signal.disconnect(done)
    except TypeError:
        pass
    if not received:
        raise TimeoutError("QGIS network smoke test timed out.")
    return received[0]


def collect_for(signals, trigger, duration_ms=400):
    loop = QEventLoop()
    received = []

    def record(name):
        return lambda *args: received.append((name, args))

    slots = []
    for name, signal in signals:
        slot = record(name)
        slots.append((signal, slot))
        signal.connect(slot)
    trigger()
    QTimer.singleShot(duration_ms, loop.quit)
    loop.exec_()
    for signal, slot in slots:
        try:
            signal.disconnect(slot)
        except TypeError:
            pass
    return received


def main() -> int:
    temporary = tempfile.TemporaryDirectory()
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = temporary.name
    configure_prefix()
    app = QgsApplication([arg.encode("utf-8") for arg in sys.argv], False)
    app.initQgis()
    server = start_fixture()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    profile = RouterProfile(name="Fixture", base_url=base, streaming=True, timeout_seconds=10)
    client = RouterClient()

    records, timestamp = wait_for(client.catalogLoaded, lambda: client.fetch_models(profile))
    assert [record.id for record in records] == ["fixture-model", "fixture-reasoning-model"]

    messages = [{"role": "user", "content": "Check the map"}]
    streaming = build_chat_payload("fixture-model", messages, "Auto", True)
    content, non_streaming, usage = wait_for(
        client.chatCompleted, lambda: client.send_chat(profile, streaming)
    )
    assert content == "The local fixture received QGIS metadata only."
    assert non_streaming is False
    assert "reasoning_effort" not in FixtureHandler.last_payload

    multimodal = build_chat_payload(
        "fixture-model",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Inspect the attached image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": ONE_PIXEL_PNG_URL},
                    },
                ],
            }
        ],
        "Auto",
        False,
    )
    content, non_streaming, usage = wait_for(
        client.chatCompleted, lambda: client.send_chat(profile, multimodal)
    )
    assert non_streaming is True
    received_parts = FixtureHandler.last_payload["messages"][0]["content"]
    assert received_parts[1]["type"] == "image_url"
    assert received_parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    complete = build_chat_payload("fixture-reasoning-model", messages, "High", False)
    content, non_streaming, usage = wait_for(
        client.chatCompleted, lambda: client.send_chat(profile, complete)
    )
    assert non_streaming is True
    assert usage["total_tokens"] == 12
    assert FixtureHandler.last_payload["reasoning_effort"] == "high"

    stopped_payload = build_chat_payload("fixture-model", messages, "Auto", True)

    def start_then_stop():
        client.chatDelta.connect(stop_after_first_delta)
        client.send_chat(profile, stopped_payload)

    def stop_after_first_delta(_text):
        client.chatDelta.disconnect(stop_after_first_delta)
        QTimer.singleShot(0, client.abort_chat)

    partial, = wait_for(client.chatStopped, start_then_stop)
    assert partial
    assert partial != "The local fixture received QGIS metadata only."

    broken_payload = build_chat_payload("fixture-broken-stream", messages, "Auto", True)
    kind, message, status, partial = wait_for(
        client.chatFailed, lambda: client.send_chat(profile, broken_payload)
    )
    assert kind == "broken_stream"
    assert partial == "The local fixture received QGIS metadata only."

    rate_payload = build_chat_payload("fixture-rate-limit", messages, "Auto", False)
    kind, message, status, partial = wait_for(
        client.chatFailed, lambda: client.send_chat(profile, rate_payload)
    )
    assert (kind, status) == ("rate_limit", 429)

    auth_profile = RouterProfile(base_url=f"{base}/authfail", timeout_seconds=10)
    kind, message, status = wait_for(
        client.catalogFailed, lambda: client.fetch_models(auth_profile)
    )
    assert (kind, status) == ("authentication", 401)

    malformed_profile = RouterProfile(base_url=f"{base}/malformed", timeout_seconds=10)
    kind, message, status = wait_for(
        client.catalogFailed, lambda: client.fetch_models(malformed_profile)
    )
    assert kind == "protocol"

    server_profile = RouterProfile(base_url=f"{base}/serverfail", timeout_seconds=10)
    kind, message, status = wait_for(
        client.catalogFailed, lambda: client.fetch_models(server_profile)
    )
    assert (kind, status) == ("server", 503)

    missing_profile = RouterProfile(base_url=f"{base}/missing", timeout_seconds=10)
    kind, message, status = wait_for(
        client.catalogFailed, lambda: client.fetch_models(missing_profile)
    )
    assert (kind, status) == ("protocol", 404)

    malformed_chat = build_chat_payload("fixture-malformed-response", messages, "Auto", False)
    kind, message, status, partial = wait_for(
        client.chatFailed, lambda: client.send_chat(profile, malformed_chat)
    )
    assert (kind, status, partial) == ("protocol", 200, "")

    server_chat = build_chat_payload("fixture-server-error", messages, "Auto", False)
    kind, message, status, partial = wait_for(
        client.chatFailed, lambda: client.send_chat(profile, server_chat)
    )
    assert (kind, status) == ("server", 503)

    catalog_race = collect_for(
        [
            ("loaded", client.catalogLoaded),
            ("failed", client.catalogFailed),
        ],
        lambda: (
            client.fetch_models(RouterProfile(base_url=f"{base}/slow", timeout_seconds=10)),
            QTimer.singleShot(10, lambda: client.fetch_models(profile)),
        ),
    )
    loaded_catalogs = [args[0] for name, args in catalog_race if name == "loaded"]
    assert len(loaded_catalogs) == 1
    assert [record.id for record in loaded_catalogs[0]] == [
        "fixture-model",
        "fixture-reasoning-model",
    ]

    slow_chat = build_chat_payload("fixture-slow-old", messages, "Auto", True)
    replacement_chat = build_chat_payload("fixture-model", messages, "Auto", False)
    chat_race = collect_for(
        [
            ("complete", client.chatCompleted),
            ("failed", client.chatFailed),
            ("stopped", client.chatStopped),
        ],
        lambda: (
            client.send_chat(profile, slow_chat),
            QTimer.singleShot(10, lambda: client.send_chat(profile, replacement_chat)),
        ),
    )
    completed = [args for name, args in chat_race if name == "complete"]
    assert len(completed) == 1
    assert completed[0][0] == "The local fixture received QGIS metadata only."
    assert not [event for event in chat_race if event[0] in {"failed", "stopped"}]

    print(
        json.dumps(
            {
                "catalog_models": len(records),
                "streaming": "passed",
                "non_streaming": "passed",
                "auto_omits_reasoning": True,
                "explicit_reasoning": "high",
                "authentication_error": 401,
                "malformed_catalog": "protocol",
                "stop_preserved_partial": True,
                "broken_stream": "classified",
                "rate_limit": 429,
                "server_error": 503,
                "missing_endpoint": 404,
                "malformed_chat": "protocol",
                "catalog_reply_race": "passed",
                "chat_reply_race": "passed",
            },
            sort_keys=True,
        )
    )
    client.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    app.exitQgis()
    temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
