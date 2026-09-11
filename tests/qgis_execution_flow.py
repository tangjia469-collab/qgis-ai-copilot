"""Model -> approved QGIS action -> model continuation, using a loopback router."""

import importlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qgis.PyQt.QtCore import QEventLoop, QTimer
from qgis.analysis import QgsNativeAlgorithms
from qgis.core import QgsApplication

from qgis_ai_copilot.protocol import RouterProfile, build_responses_payload
from tests.qgis_runtime import configure_prefix, synthetic_project
from tests.qgis_smoke import FakeIface


class ExecutionRouter(BaseHTTPRequestHandler):
    layer_id = ""
    requests = []
    tool_name = "run_processing"

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(payload)
        results = [item for item in payload["input"] if item.get("type") == "function_call_output"]
        if not any(tool["name"] == "run_processing" for tool in payload.get("tools", [])):
            output = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Chat-only answer."}]}]
        elif not results:
            output = [
                {"id": "reasoning1", "type": "reasoning", "summary": [], "encrypted_content": "OPAQUE_CONTINUATION"},
                {
                    "id": "fc1",
                    "type": "function_call",
                    "call_id": "call1",
                    "name": self.tool_name,
                    "arguments": json.dumps(
                        {"layer_id": self.layer_id} if self.tool_name == "remove_temporary_layer" else {
                            "algorithm_id": "native:buffer",
                            "parameters_json": json.dumps({"INPUT": self.layer_id, "DISTANCE": 5}),
                            "result_name": "Agent buffer",
                        }
                    ),
                }
            ]
        else:
            output = [
                {
                    "id": "answer",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Removed the temporary layer." if self.tool_name == "remove_temporary_layer" else "Created a buffer layer."}],
                }
            ]
        value = {
            "status": "completed",
            "output": output,
            "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        }
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/event-stream" if payload["stream"] else "application/json"
        )
        self.end_headers()
        if payload["stream"]:
            self.wfile.write(
                (
                    "data: "
                    + json.dumps({"type": "response.completed", "response": value})
                    + "\n\n"
                ).encode()
            )
        else:
            self.wfile.write(json.dumps(value).encode())


class ExecutionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        if not QgsApplication.processingRegistry().algorithmById("native:buffer"):
            QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ExecutionRouter)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.project, self.layer = synthetic_project()
        self.iface = FakeIface()
        self.iface.set_active_layer(self.layer)
        self.profile = RouterProfile(
            base_url=f"http://127.0.0.1:{self.server.server_port}", adapter="responses"
        )
        ExecutionRouter.layer_id = self.layer.id()
        ExecutionRouter.tool_name = "run_processing"
        ExecutionRouter.requests = []
        try:
            module = importlib.import_module("qgis_ai_copilot.execution")
        except ImportError:
            self.fail("Missing model execution loop")
        self.session = module.ExecuteSession(self.iface, self.profile)

    def tearDown(self):
        if hasattr(self, "session"):
            self.session.cancel()
        self.project.clear()
        self.iface.window.close()

    def wait(self, approve=True, stream=True):
        loop = QEventLoop()
        results = []
        self.approvals = []

        def asked(plan):
            self.approvals.append(plan)
            self.assertEqual(len(self.project.mapLayers()), 2)
            if approve:
                QTimer.singleShot(0, self.session.approve)
            else:
                QTimer.singleShot(0, self.session.cancel)

        self.session.approvalRequested.connect(asked)
        self.session.finished.connect(lambda *args: (results.append(args), loop.quit()))
        self.session.start(
            build_responses_payload(
                "fixture", [{"role": "user", "content": "Make a 5 metre buffer"}], stream=stream
            )
        )
        QTimer.singleShot(10000, loop.quit)
        loop.exec_()
        self.assertTrue(results, "Execution loop timed out")
        return results[0]

    def test_approved_tool_executes_once_and_continues_with_result(self):
        status, text, error = self.wait()
        self.assertEqual(status, "complete", error)
        self.assertEqual(text, "Created a buffer layer.")
        self.assertEqual(self.session.usage["total_tokens"], 16)
        self.assertEqual([item["total_tokens"] for item in getattr(self.session, "usage_rounds", [])], [8, 8])
        self.assertEqual(len(self.project.mapLayers()), 3)
        self.assertEqual(len(self.approvals), 1)
        self.assertEqual(len(ExecutionRouter.requests), 2)
        result = next(
            item
            for item in ExecutionRouter.requests[-1]["input"]
            if item.get("type") == "function_call_output"
        )
        self.assertEqual(result["call_id"], "call1")
        self.assertTrue(json.loads(result["output"])["ok"])

    def test_stop_at_approval_does_not_modify_or_continue(self):
        status, _, _ = self.wait(False)
        self.assertEqual(status, "stopped")
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(len(ExecutionRouter.requests), 1)

    def test_nonstreamed_tool_response_also_works(self):
        self.assertEqual(self.wait(stream=False)[0], "complete")
        self.assertEqual(self.session.usage["total_tokens"], 16)
        self.assertEqual(len(self.project.mapLayers()), 3)


if __name__ == "__main__":
    unittest.main()
