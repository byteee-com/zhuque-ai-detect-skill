#!/usr/bin/env python3
"""Run the documented EdgeOne Zhuque classifiers without extra dependencies."""

import argparse
import base64
from contextlib import suppress
import getpass
import html
from http.client import HTTPException
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import warnings
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile
from zlib import error as DeflateError


MAKERS_ORIGIN = "https://ai-gateway.edgeone.link"
MAKERS_KEY = "MAKERS_MODELS_KEY"
PRO_FIELDS = ("ZHUQUE_PRO_GATEWAY", "ZHUQUE_PRO_API_KEY")
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".docx"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
LABELS = {"0": "人工", "1": "AI", "2": "疑似 AI"}
MAX_TEXT_BYTES = 20 * 1024 * 1024  # Local resource guard, not a provider limit.
MAX_IMAGE_BYTES = 10_000_000
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
READ_ONLY = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)


class Issue(Exception):
    def __init__(self, code, message, *, stop=True):
        super().__init__(message)
        self.code = code
        self.stop = stop

    def report(self):
        return {"code": self.code, "message": str(self)}


def input_error(message):
    return Issue("invalid_input", message, stop=False)


def private_config_path():
    return Path.home() / ".config" / "zhuque-detect" / "credentials.json"


def load_private_config(*, allow_empty=False):
    path = private_config_path()
    try:
        fd = os.open(path, READ_ONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            mode = os.fstat(handle.fileno())
            if not stat.S_ISREG(mode.st_mode):
                raise Issue("invalid_config", "私有凭证配置须为普通文件。")
            if hasattr(os, "getuid") and (mode.st_uid != os.getuid() or mode.st_mode & 0o077):
                raise Issue("invalid_config", "私有凭证须归当前用户且仅本人可读写（如 0600）。")
            if mode.st_size > 16 * 1024:
                raise Issue("invalid_config", "私有凭证配置超出大小限制。")
            data = handle.read(16 * 1024).decode("utf-8-sig")
            config = {} if allow_empty and not data.strip() else json.loads(data)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        raise Issue("invalid_config", "无法读取私有凭证配置，请检查文件及 JSON 格式。") from None
    if not isinstance(config, dict):
        raise Issue("invalid_config", "私有凭证配置须为 JSON 对象。")
    return config


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[!-~]+", key):
        raise Issue("invalid_config", "API Key 为空或包含无效字符。")
    return key


def setup_makers():
    config = load_private_config(allow_empty=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Makers API Key（输入不回显）：").strip()
    except getpass.GetPassWarning:
        raise Issue("setup_requires_terminal", "请在可隐藏输入的交互式终端运行 setup。") from None
    except (EOFError, KeyboardInterrupt):
        raise Issue("setup_cancelled", "已取消配置。") from None
    config[MAKERS_KEY] = validate_key(key)

    path = private_config_path()
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".credentials-", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        raise Issue("invalid_config", "无法保存本地配置，请检查用户目录的写入权限。") from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def parse_https_url(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.fragment
        or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", url.netloc)
        or (url.port is not None and url.port == 0)
    ):
        raise ValueError
    return url


def image_url(value):
    try:
        host = parse_https_url(value).hostname.rstrip(".").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError from None
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError
    except ValueError:
        raise input_error("请提供公网可访问的 HTTPS 图片 URL。") from None
    return {"imageUrl": value}


def credentials(provider):
    fields = (MAKERS_KEY,) if provider == "makers" else PRO_FIELDS
    from_environment = any(field in os.environ for field in fields)
    source = os.environ if from_environment else load_private_config()
    if not any(field in source for field in fields):
        raise Issue("missing_config", "未配置 " + " 和 ".join(fields) + "。")
    if not all(field in source for field in fields):
        raise Issue("invalid_config", "企业网关和 Key 必须在同一处成对配置。")
    key = validate_key(source[fields[-1]])
    if provider == "makers":
        return MAKERS_ORIGIN, key
    try:
        url = parse_https_url(source[PRO_FIELDS[0]])
        if url.path not in ("", "/") or url.query or "?" in source[PRO_FIELDS[0]] or "#" in source[PRO_FIELDS[0]]:
            raise ValueError
    except ValueError:
        raise Issue("invalid_config", "企业网关须为控制台分配的 HTTPS origin。") from None
    return "https://" + url.netloc, key


def read_bounded(handle, limit, description):
    data = handle.read(limit + 1)
    if len(data) > limit:
        raise input_error(f"{description}超出读取上限。请提供较小的输入。")
    return data


def read_docx(handle):
    with ZipFile(handle) as document:
        with document.open("word/document.xml") as body_file:
            data = read_bounded(body_file, MAX_TEXT_BYTES, "DOCX 正文")
    root = ElementTree.fromstring(data)
    ns = root.tag.removesuffix("document")
    if ns not in (
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
        "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
    ):
        raise input_error("DOCX 缺少有效的 Word 正文。")
    body = root.find(ns + "body")
    if body is None:
        raise input_error("DOCX 缺少有效的 Word 正文。")

    hidden = {ns + tag for tag in ("del", "moveFrom", "drawing", "pict", "object")}
    tokens = {ns + "tab": "\t", ns + "br": "\n", ns + "cr": "\n"}
    paragraphs = []
    # Skip deleted text and embedded objects, while traversing table cells in place.
    stack = [(body, None)]
    while stack:
        node, paragraph = stack.pop()
        if node.tag in hidden:
            continue
        if node.tag == ns + "p":
            paragraph = []
            paragraphs.append(paragraph)
        if paragraph is not None:
            if node.tag == ns + "t":
                paragraph.append(node.text or "")
            elif node.tag in tokens:
                paragraph.append(tokens[node.tag])
        stack.extend((child, paragraph) for child in reversed(node))
    return "\n".join("".join(paragraph) for paragraph in paragraphs)


def read_text(handle, suffix):
    try:
        content = (
            read_docx(handle) if suffix == ".docx"
            else read_bounded(handle, MAX_TEXT_BYTES, "文本").decode("utf-8-sig")
        )
    except (BadZipFile, DeflateError, EOFError, ElementTree.ParseError, KeyError, RuntimeError, ValueError):
        raise input_error("无法提取文本，请检查 UTF-8 编码或 DOCX 文件完整性。") from None
    if not content.strip():
        raise input_error("没有可检测的文本。")
    return content


def file_kind(path):
    if path.suffix.lower() in TEXT_SUFFIXES:
        return "text"
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return "image"
    raise input_error("文件类型不受支持。")


def read_file(path, kind, paragraphs):
    if file_kind(path) != kind:
        raise input_error("文件与所选检测类型不符。")
    try:
        with os.fdopen(os.open(path, READ_ONLY), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise input_error("输入须为可读取的普通文件。")
            if kind == "text":
                return {"text": read_text(handle, path.suffix.lower()), "is_merge": not paragraphs}
            image = read_bounded(handle, MAX_IMAGE_BYTES, "图片")
    except OSError:
        raise input_error("无法读取指定文件。") from None
    signatures = {
        ".jpg": image.startswith(b"\xff\xd8\xff"),
        ".jpeg": image.startswith(b"\xff\xd8\xff"),
        ".png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": image.startswith(b"RIFF") and image[8:12] == b"WEBP",
    }
    if not signatures[path.suffix.lower()]:
        raise input_error("图片内容与文件扩展名不符。")
    return {"imageBase64": base64.b64encode(image).decode("ascii")}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def service_error(status, data):
    values = []
    if isinstance(data, dict):
        for obj in (data, data.get("error")):
            if isinstance(obj, dict):
                for field in ("code", "type", "msg", "message"):
                    value = obj.get(field)
                    if isinstance(value, str):
                        values.append(value[:512].lower())
    detail = " ".join(values)
    if status == 401 or "invalid api key" in detail or "invalid_api_key" in detail:
        return Issue("authentication", "API Key 无效或已失效。")
    if status == 402 or re.search(r"quota|token limit|insufficient (balance|credit)|额度|余额", detail):
        return Issue("quota", "额度或余额不可用，请检查腾讯云控制台。")
    if status == 403 or "provider_not_allowed" in detail:
        return Issue("permission", "网关未授权调用该模型。")
    if status == 429 or re.search(r"rate.?limit|too many requests|限流", detail):
        return Issue("rate_limit", "腾讯返回限流，请稍后手动重试。")
    if status in (400, 413, 415, 422):
        return Issue("rejected_input", f"腾讯拒绝这项输入（HTTP {status}）。", stop=False)
    if status is not None and 300 <= status < 400:
        return Issue("redirect", "网关要求重定向，请核对地址。")
    suffix = f"（HTTP {status}）" if status is not None else ""
    return Issue("service_error", f"腾讯未返回成功结果{suffix}。请核对服务状态和用量后再提交。")


def classify(origin, key, kind, payload):
    request = Request(
        f"{origin}/v1/providers/zhuque-{kind}/classify",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        with error:
            try:
                body = json.loads(error.read(16 * 1024))
            except (ValueError, OSError, HTTPException, RecursionError):
                body = None
        raise service_error(error.code, body) from None
    except (URLError, OSError, HTTPException, ValueError):
        raise Issue("submission_unknown", "连接或读取响应失败，无法确认是否已处理或扣费。") from None

    try:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        if data.get("status") != "success":
            raise service_error(None, data)
        return parse_result(kind, data)
    except (ValueError, KeyError, TypeError, RecursionError):
        raise Issue("invalid_response", "响应格式无法确认，请核对服务状态和用量后再提交。") from None


def fraction(value):
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError
    return value


def nonnegative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def parse_result(kind, data):
    if kind == "image":
        return {"ai_confidence": fraction(data["data"]["confidence"])}
    result = {"labels_ratio": {label: fraction(data["labels_ratio"][label]) for label in LABELS}}
    for field in ("ratio_confidence", "softmax_confidence"):
        if data.get(field) is not None:
            result[field] = fraction(data[field])
    segments = data.get("segment_labels", [])
    if not isinstance(segments, list):
        raise ValueError
    result["segment_labels"] = []
    for segment in segments:
        label = nonnegative_int(segment["label"])
        if str(label) not in LABELS:
            raise ValueError
        item = {"label": label, "order": nonnegative_int(segment["order"])}
        if segment.get("conf") is not None:
            item["conf"] = fraction(segment["conf"])
        if segment.get("position") is not None:
            position = segment["position"]
            if not isinstance(position, list) or len(position) != 2:
                raise ValueError
            item["position"] = [nonnegative_int(offset) for offset in position]
        result["segment_labels"].append(item)
    for field in ("usage", "makers_models_usage"):
        usage = data.get(field)
        if usage is not None:
            if not isinstance(usage, dict):
                raise ValueError
            if usage.get("total_tokens") is not None:
                result[field] = {"total_tokens": nonnegative_int(usage["total_tokens"])}
    return result


def batch_preflight(paths, provider, paragraphs, compare):
    items = []
    for path in paths:
        item = {"name": path.name, "status": "ready"}
        try:
            kind = file_kind(path)
            item["kind"] = kind
            if kind == "image" and (provider != "pro" or compare):
                raise input_error("当前设置仅支持文本。")
            read_file(path, kind, paragraphs)
        except Issue as issue:
            item.update(status="failed", error=issue.report())
        items.append(item)
    return items


def run_item(item, origin, key, payload):
    try:
        item.update(status="success", result=classify(origin, key, item["kind"], payload))
    except Issue as issue:
        item.update(status="failed", error=issue.report())
        return issue.stop
    return False


def run_batch(args, items, origin, key):
    stopped = False
    for path, item in zip(args.files, items):
        if item["status"] != "ready":
            continue
        if stopped:
            item["status"] = "not_submitted"
            continue
        try:
            payload = read_file(path, item["kind"], args.paragraphs)
        except Issue as issue:
            item.update(status="failed", error=issue.report())
            stopped = args.compare
            continue
        stopped = run_item(item, origin, key, payload)
        if args.compare and item["status"] != "success":
            stopped = True


def make_report(provider, items, *, dry_run=False, compare=False):
    report = {"provider": provider, "dry_run": dry_run, "items": items}
    report["counts"] = {
        status: sum(item["status"] == status for item in items)
        for status in ("success", "failed", "not_submitted", "ready")
    }
    if provider == "makers" and not dry_run:
        known = [
            item["result"]["makers_models_usage"]["total_tokens"]
            for item in items if "makers_models_usage" in item.get("result", {})
        ]
        report["makers_usage"] = {"known_total_tokens": sum(known), "items_with_usage": len(known)}
    if compare and report["counts"]["success"] == 2:
        first, second = [item["result"]["labels_ratio"] for item in items]
        report["comparison"] = {
            "delta_percentage_points": {label: round((second[label] - first[label]) * 100, 8) for label in LABELS}
        }
    return report


def percent(value):
    return f"{value:.2%}"


def markdown(report):
    provider = {"makers": "EdgeOne Makers", "pro": "EdgeOne Makers Model Pro"}[report["provider"]]
    lines = ["# 朱雀 AI 检测报告", "", f"入口：{provider}", ""]
    statuses = {"success": "成功", "failed": "失败", "not_submitted": "未提交", "ready": "可提交"}
    counts = report["counts"]
    lines.append(" · ".join(f"{name} {counts[status]}" for status, name in statuses.items()))
    if "makers_usage" in report:
        usage = report["makers_usage"]
        if usage["items_with_usage"]:
            lines.append(f"已知实际扣减：{usage['known_total_tokens']} token（{usage['items_with_usage']} 项返回用量）")
        if usage["items_with_usage"] < counts["success"] or any(
            item.get("error", {}).get("code") in {"submission_unknown", "invalid_response", "service_error"}
            for item in report["items"]
        ):
            lines.append("有请求的扣减量无法从报告确认，请查看腾讯云控制台。")
    for index, item in enumerate(report["items"], 1):
        name = html.escape(" ".join(item["name"].split()))
        name = re.sub(r"([\\\x60*_[\]~])", r"\\\1", name)
        lines.extend(["", f"## {index}. {name}", "", statuses[item["status"]]])
        if "error" in item:
            lines.append(item["error"]["message"])
        result = item.get("result")
        if not result:
            continue
        if item["kind"] == "image":
            lines.append(f"- 图片 AI 置信度：{percent(result['ai_confidence'])}")
            continue
        for label, name in LABELS.items():
            lines.append(f"- {name}内容占比：{percent(result['labels_ratio'][label])}")
        for field, name in (("softmax_confidence", "整体置信度"), ("ratio_confidence", "整体疑似风险占比")):
            if field in result:
                lines.append(f"- {name}：{percent(result[field])}")
        if "makers_models_usage" in result:
            lines.append(f"- 实际扣减：{result['makers_models_usage']['total_tokens']} token")
        for segment in result["segment_labels"]:
            label = LABELS[str(segment["label"])]
            confidence = f"（置信度 {percent(segment['conf'])}）" if "conf" in segment else ""
            lines.append(f"- 分段 {segment['order']}：{label}{confidence}")
    if "comparison" in report:
        lines.extend(["", "## 两版稿件占比变化", "", "第二份减第一份，单位为百分点。"])
        for label, delta in report["comparison"]["delta_percentage_points"].items():
            lines.append(f"- {LABELS[label]}：{delta:+.2f}")
    lines.extend(["", "检测结果仅供复核。", ""])
    return "\n".join(lines)


def parser():
    cli = argparse.ArgumentParser(description="腾讯朱雀官方 API 检测")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="在终端交互配置普通 Makers API Key")
    commands.add_parser("doctor", help="仅检查本地配置")
    for command in ("text", "image", "batch"):
        sub = commands.add_parser(command)
        if command == "image":
            sub.add_argument("--provider", choices=("pro",), required=True)
        else:
            sub.add_argument("--provider", choices=("makers", "pro"), default="makers")
        sub.add_argument("--format", choices=("json", "markdown"), default="json")
        if command != "image":
            sub.add_argument("--paragraphs", action="store_true")
        if command == "batch":
            sub.add_argument("--compare", action="store_true")
            sub.add_argument("--dry-run", action="store_true")
            sub.add_argument("files", nargs="+", type=Path)
        else:
            source = sub.add_mutually_exclusive_group(required=True)
            source.add_argument("--file", type=Path)
            if command == "text":
                source.add_argument("--stdin", action="store_true")
            else:
                source.add_argument("--url")
    return cli


def single_input(args):
    name = args.file.name if args.file else ("标准输入" if args.command == "text" else "公网图片 URL")
    item = {"name": name, "kind": args.command, "status": "ready"}
    try:
        if args.file:
            payload = read_file(args.file, args.command, getattr(args, "paragraphs", False))
        elif args.command == "text":
            payload = {"text": read_text(sys.stdin.buffer, ".txt"), "is_merge": not args.paragraphs}
        else:
            payload = image_url(args.url)
    except Issue as issue:
        item.update(status="failed", error=issue.report())
        payload = None
    return item, payload


def submit(args, items, payload, compare):
    pending = [item for item in items if item["status"] == "ready"]
    if not pending:
        return 0
    if compare and len(pending) < 2:
        pending[0]["status"] = "not_submitted"
        return 0
    try:
        origin, key = credentials(args.provider)
    except Issue as issue:
        for item in pending:
            item.update(status="not_submitted", error=issue.report())
        return 2
    if args.command == "batch":
        run_batch(args, items, origin, key)
    else:
        run_item(items[0], origin, key, payload)
    return 0


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.command == "setup":
        try:
            setup_makers()
        except Issue as issue:
            print(str(issue), file=sys.stderr)
            return 2
        print("Makers API Key 已保存到本机。")
        if MAKERS_KEY in os.environ:
            print("当前终端已设置 MAKERS_MODELS_KEY，运行时会优先使用环境变量。")
        return 0
    if args.command == "doctor":
        checks = {}
        for provider in ("makers", "pro"):
            try:
                credentials(provider)
            except Issue as issue:
                state = "missing" if issue.code == "missing_config" else "invalid"
                checks[provider] = {"status": state, "message": str(issue)}
            else:
                checks[provider] = {"status": "ready"}
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 2 if any(check["status"] == "invalid" for check in checks.values()) else 0

    dry_run = args.command == "batch" and args.dry_run
    compare = args.command == "batch" and args.compare
    if compare and len(args.files) != 2:
        cli.error("--compare 需要恰好两份文本文件。")
    if args.command == "batch":
        items = batch_preflight(args.files, args.provider, args.paragraphs, compare)
        payload = None
    else:
        item, payload = single_input(args)
        items = [item]
    exit_code = 0 if dry_run else submit(args, items, payload, compare)
    report = make_report(args.provider, items, dry_run=dry_run, compare=compare)
    print(markdown(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code or int(bool(report["counts"]["failed"] or report["counts"]["not_submitted"]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
