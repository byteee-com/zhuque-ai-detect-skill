import base64
from contextlib import ExitStack, redirect_stdout
import getpass
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from zipfile import ZipFile

from scripts import zhuque


def text_response(*, ai=0.2, tokens=30):
    response = {
        "status": "success",
        "labels_ratio": {"0": 1 - ai, "1": ai, "2": 0},
        "ratio_confidence": ai,
        "softmax_confidence": 0.6,
        "segment_labels": [{"label": 1, "order": 2, "conf": 0.6, "position": [0, 4], "text": "不公开的原文"}],
        "usage": {"total_tokens": 50},
    }
    if tokens is not None:
        response["makers_models_usage"] = {"total_tokens": tokens}
    return response


class FakeOpener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode())


class ZhuqueTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(Path, "home", return_value=self.home))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def file(self, name, contents="第一段\n\n第二段"):
        path = self.home / name
        path.write_bytes(contents.encode() if isinstance(contents, str) else contents)
        return path

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            status = zhuque.main([str(arg) for arg in args])
        return status, out.getvalue()

    def fake(self, *responses):
        opener = FakeOpener(*responses)
        self.stack.enter_context(patch.object(zhuque, "build_opener", return_value=opener))
        return opener

    def test_setup_saves_key_for_next_invocation_and_preserves_pro(self):
        location = self.home / ".config" / "zhuque-detect" / "credentials.json"
        with patch.object(zhuque.getpass, "getpass", side_effect=["test-initial-key", "test-rotated-key"]):
            status, output = self.cli("setup")
            self.assertEqual(status, 0)
            self.assertNotIn("test-initial-key", output)
            if os.name == "posix":
                self.assertEqual(location.stat().st_mode & 0o777, 0o600)
            config = json.loads(location.read_text(encoding="utf-8"))
            config.update(ZHUQUE_PRO_GATEWAY="https://pro.example.com", ZHUQUE_PRO_API_KEY="test-pro")
            location.write_text(json.dumps(config), encoding="utf-8")
            status, output = self.cli("setup")
        self.assertEqual(status, 0)
        self.assertNotIn("test-rotated-key", output)
        self.assertEqual(zhuque.credentials("makers")[1], "test-rotated-key")
        self.assertEqual(zhuque.credentials("pro"), ("https://pro.example.com", "test-pro"))
        status, output = self.cli("doctor")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["makers"]["status"], "ready")

    def test_setup_rejects_echoing_input_without_overwriting_key(self):
        with patch.object(zhuque.getpass, "getpass", return_value="test-existing-key"):
            self.assertEqual(self.cli("setup")[0], 0)
        with patch.object(zhuque.getpass, "getpass", side_effect=getpass.GetPassWarning):
            self.assertEqual(self.cli("setup")[0], 2)
        self.assertEqual(zhuque.credentials("makers")[1], "test-existing-key")

    def test_makers_uses_official_route_and_reports_billing_field(self):
        os.environ["MAKERS_MODELS_KEY"] = "test-makers-secret"
        opener = self.fake(text_response())
        path = self.file("稿件.txt", b"\xef\xbb\xbf" + "原稿\r\n\r\n尾段".encode())
        status, output = self.cli("text", "--file", path, "--paragraphs")
        self.assertEqual(status, 0)
        request, = opener.requests
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-makers-secret")
        self.assertEqual(json.loads(request.data), {"text": "原稿\r\n\r\n尾段", "is_merge": False})
        report = json.loads(output)
        self.assertEqual(report["makers_usage"], {"known_total_tokens": 30, "items_with_usage": 1})
        result = report["items"][0]["result"]
        self.assertEqual(result["usage"]["total_tokens"], 50)
        self.assertEqual(result["segment_labels"][0], {"label": 1, "order": 2, "conf": 0.6, "position": [0, 4]})
        for private in ("test-makers-secret", "不公开的原文", "原稿", str(self.home)):
            self.assertNotIn(private, output)

    def test_pro_file_and_url_use_pro_key_and_image_request(self):
        os.environ.update(MAKERS_MODELS_KEY="test-makers", ZHUQUE_PRO_API_KEY="test-pro",
                          ZHUQUE_PRO_GATEWAY="https://pro.example.com/")
        response = {"status": "success", "data": {"confidence": 0.23}}
        opener = self.fake(response, response)
        contents = b"\x89PNG\r\n\x1a\nfixture"
        path = self.file("样本.png", contents)
        status, report = self.cli("image", "--provider", "pro", "--file", path, "--format", "markdown")
        self.assertEqual(status, 0)
        self.assertIn("图片 AI 置信度：23.00%", report)
        self.assertNotIn("实际扣减", report)
        url = "https://assets.example.com/a.jpg?download=1"
        self.assertEqual(self.cli("image", "--provider", "pro", "--url", url)[0], 0)
        file_request, url_request = opener.requests
        for request in opener.requests:
            self.assertEqual(request.get_header("Authorization"), "Bearer test-pro")
            self.assertEqual(request.full_url, "https://pro.example.com/v1/providers/zhuque-image/classify")
        self.assertEqual(json.loads(file_request.data), {"imageBase64": base64.b64encode(contents).decode()})
        self.assertEqual(json.loads(url_request.data), {"imageUrl": url})
        self.assertEqual(self.cli("image", "--provider", "pro", "--url", "https://127.0.0.1/a.jpg")[0], 1)
        self.assertEqual(len(opener.requests), 2)

    def test_pro_text_from_stdin_defaults_to_merged_paragraphs(self):
        os.environ.update(ZHUQUE_PRO_API_KEY="test-pro", ZHUQUE_PRO_GATEWAY="https://pro.example.com")
        opener = self.fake(text_response(tokens=None))
        sample = "首段\n\n尾段"
        with io.TextIOWrapper(io.BytesIO(sample.encode()), encoding="utf-8") as stdin:
            with patch.object(sys, "stdin", stdin):
                status, output = self.cli("text", "--provider", "pro", "--stdin")
        self.assertEqual(status, 0)
        request, = opener.requests
        self.assertEqual(request.full_url, "https://pro.example.com/v1/providers/zhuque-text/classify")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-pro")
        self.assertEqual(json.loads(request.data), {"text": sample, "is_merge": True})
        self.assertNotIn("makers_usage", json.loads(output))

    def test_docx_order_and_markdown_comparison(self):
        os.environ["MAKERS_MODELS_KEY"] = "test-makers"
        opener = self.fake(text_response(ai=0.2), text_response(ai=0.5, tokens=None))
        first = self.file("初稿.md", "# 标题\n\n原稿文字")
        second = self.home / "修改稿.docx"
        with ZipFile(second, "w") as docx:
            docx.writestr("word/header1.xml", "不要发送的页眉")
            docx.writestr("word/document.xml", """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
              <w:p><w:r><w:t>中文正文</w:t></w:r></w:p>
              <w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格文字</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
              <w:p><w:del><w:r><w:delText>已删除</w:delText></w:r></w:del><w:r><w:t>正文尾段</w:t></w:r></w:p>
            </w:body></w:document>
            """)
        self.assertEqual(self.cli("batch", "--dry-run", first, second)[0], 0)
        self.assertFalse(opener.requests)
        status, report = self.cli("batch", "--compare", "--paragraphs", "--format", "markdown", first, second)
        self.assertEqual(status, 0)
        self.assertIn("- AI：+30.00", report)
        self.assertIn("有请求的扣减量无法从报告确认", report)
        self.assertNotIn("中文正文", report)
        self.assertEqual(
            [json.loads(request.data) for request in opener.requests],
            [
                {"text": "# 标题\n\n原稿文字", "is_merge": False},
                {"text": "中文正文\n表格文字\n正文尾段", "is_merge": False},
            ],
        )

    def test_batch_continues_after_item_error_and_stops_on_incomplete_response(self):
        os.environ["MAKERS_MODELS_KEY"] = "test-makers"
        rejected = HTTPError("https://example.com", 422, "", {}, io.BytesIO(b"{}"))
        opener = self.fake(rejected, text_response(), IncompleteRead(b"partial"))
        files = [self.file(f"{i}.txt", f"测试文件 {i}") for i in range(4)]
        status, output = self.cli("batch", self.home / "缺失.txt", *files)
        self.assertEqual(status, 1)
        report = json.loads(output)
        self.assertEqual([item["status"] for item in report["items"]],
                         ["failed", "failed", "success", "failed", "not_submitted"])
        self.assertEqual(report["items"][-2]["error"]["code"], "submission_unknown")
        self.assertEqual(len(opener.requests), 3)

    def test_batch_stops_on_auth_rate_limit_quota_and_unexpected_body(self):
        os.environ["MAKERS_MODELS_KEY"] = "test-makers"
        files = [self.file("一.txt"), self.file("二.txt")]
        cases = [
            (HTTPError("", 401, "", {}, io.BytesIO(b"{}")), "authentication"),
            (HTTPError("", 429, "", {}, io.BytesIO(b"{}")), "rate_limit"),
            (HTTPError("", 400, "", {}, io.BytesIO(b'{"code":"quota_exceeded"}')), "quota"),
            ({"status": "success", "labels_ratio": {"0": 1}}, "invalid_response"),
        ]
        for response, error_code in cases:
            with self.subTest(error_code=error_code):
                opener = FakeOpener(response)
                with patch.object(zhuque, "build_opener", return_value=opener):
                    status, output = self.cli("batch", *files)
                self.assertEqual(status, 1)
                first, second = json.loads(output)["items"]
                self.assertEqual(first["error"]["code"], error_code)
                self.assertEqual(second["status"], "not_submitted")
                self.assertEqual(len(opener.requests), 1)

    def test_doctor_never_mixes_pro_credentials_or_outputs_secrets(self):
        directory = self.home / ".config" / "zhuque-detect"
        directory.mkdir(parents=True)
        config = directory / "credentials.json"
        config.write_text(json.dumps({
            "MAKERS_MODELS_KEY": "local-secret",
            "ZHUQUE_PRO_GATEWAY": "https://pro.example.com",
            "ZHUQUE_PRO_API_KEY": "local-pro-secret",
        }))
        config.chmod(0o600)
        opener = self.fake()
        status, output = self.cli("doctor")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["pro"]["status"], "ready")
        os.environ["ZHUQUE_PRO_GATEWAY"] = "https://different.example.com"
        status, output = self.cli("doctor")
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output)["pro"]["status"], "invalid")
        self.assertEqual(json.loads(output)["makers"]["status"], "ready")
        self.assertNotIn("secret", output)
        self.assertFalse(opener.requests)

    def test_transport_rejects_redirect_without_a_second_request(self):
        paths = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                paths.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/must-not-follow")
                self.end_headers()

            def do_GET(self):
                paths.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(text_response()).encode())

            def log_message(self, *_args):
                pass

        with HTTPServer(("127.0.0.1", 0), RedirectHandler) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                with self.assertRaises(zhuque.Issue) as failure:
                    zhuque.classify(f"http://127.0.0.1:{server.server_port}", "fixture",
                                    "text", {"text": "测试"})
                self.assertEqual(failure.exception.code, "redirect")
                self.assertEqual(paths, ["/v1/providers/zhuque-text/classify"])
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
