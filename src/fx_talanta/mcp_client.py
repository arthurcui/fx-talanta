"""Bounded loopback-only MT5 MCP calendar transport. No execution tools."""

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LIMIT = 2 * 1024 * 1024
TOOLS = frozenset(
    {
        "get_time_information",
        "terminal_get_info",
        "economic_calendar_list_events_by_currency",
        "economic_calendar_list_values",
        "economic_calendar_list_values_last",
        "economic_calendar_get_value_by_id",
    }
)


class McpError(ValueError):
    """Only fixed diagnostic codes cross the credential/transport boundary."""


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise McpError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def constant(_):
        raise McpError("NONFINITE_JSON_NUMBER")

    def real(value):
        result = float(value)
        if not math.isfinite(result):
            raise McpError("NONFINITE_JSON_NUMBER")
        return result

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=real)


def validate_endpoint(endpoint):
    url = urllib.parse.urlsplit(endpoint)
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or url.port is None
        or url.username
        or url.password
        or url.path != "/mcp"
        or url.query
        or url.fragment
    ):
        raise McpError("LOOPBACK_ENDPOINT_REQUIRED")
    return endpoint


def credential(export_file, endpoint):
    """Read the terminal entry from MT5 Copy's JSON block, never log its contents."""
    validate_endpoint(endpoint)
    with Path(export_file).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise McpError("EXPORT_SIZE_BOUND")
    text = raw.decode("utf-8-sig")
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = json.JSONDecoder().raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or "mcpServers" not in value:
            continue
        value = strict_json(text[offset : offset + end])
        entry = value["mcpServers"]["terminal"]
        auth = entry.get("headers", {}).get("Authorization", "")
        if (
            entry.get("url") != endpoint
            or not isinstance(auth, str)
            or not auth.startswith("Bearer ")
            or not 8 <= len(auth) <= 4096
            or "\r" in auth
            or "\n" in auth
        ):
            raise McpError("EXPORT_ENDPOINT_OR_AUTH_INVALID")
        return auth
    raise McpError("TERMINAL_EXPORT_REQUIRED")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_sse(response, request_id, deadline):
    parts, size = [], 0
    while True:
        if time.monotonic() > deadline:
            raise McpError("RESPONSE_DEADLINE")
        line = response.readline(LIMIT + 1 - size)
        size += len(line)
        if size > LIMIT:
            raise McpError("RESPONSE_SIZE_BOUND")
        if line.startswith(b"data:"):
            part = line[5:].rstrip(b"\r\n")
            parts.append(part[1:] if part.startswith(b" ") else part)
        if (not line or not line.strip()) and parts:
            raw, parts = b"\n".join(parts).strip(), []
            if raw and raw != b"[DONE]":
                value = strict_json(raw)
                if isinstance(value, dict) and value.get("id") == request_id:
                    return value
        if not line:
            raise McpError("MISSING_RPC_RESPONSE")


class Client:
    def __init__(self, export_file, endpoint, *, timeout=12):
        if not 0 < timeout <= 12:
            raise McpError("INVALID_TIMEOUT")
        self.endpoint = validate_endpoint(endpoint)
        self._authorization = credential(export_file, endpoint)
        self.timeout, self.serial, self.session = timeout, 0, None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.attempts = []

    def rpc(self, method, params=None, *, notification=False):
        params = params or {}
        if method not in {"initialize", "notifications/initialized", "tools/call"} or (
            method == "tools/call" and params.get("name") not in TOOLS
        ):
            raise McpError("READ_ONLY_TOOL_REQUIRED")
        self.serial += 1
        request_id = self.serial
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = request_id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": self._authorization,
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        began = time.monotonic()
        attempt = {"method": method, "tool": params.get("name"), "ok": False}
        try:
            request = urllib.request.Request(
                self.endpoint, data=json.dumps(body).encode(), headers=headers, method="POST"
            )
            with self.opener.open(request, timeout=self.timeout) as response:
                attempt["http_status"] = response.status
                self.session = response.headers.get("Mcp-Session-Id", self.session)
                if notification and response.status in {200, 202, 204}:
                    attempt["ok"] = True
                    return {}
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    message = read_sse(response, request_id, began + self.timeout)
                else:
                    raw = response.read(LIMIT + 1)
                    if len(raw) > LIMIT:
                        raise McpError("RESPONSE_SIZE_BOUND")
                    message = strict_json(raw)
            if time.monotonic() - began > self.timeout:
                raise McpError("RESPONSE_DEADLINE")
            if (
                not isinstance(message, dict)
                or type(message.get("id")) is not int
                or message.get("id") != request_id
                or message.get("jsonrpc") != "2.0"
                or "error" in message
                or not isinstance(message.get("result"), dict)
            ):
                raise McpError("RPC_RESPONSE_INVALID")
            result = message["result"]
            if result.get("isError"):
                raise McpError("TOOL_ERROR")
            attempt["ok"] = True
            return result
        except McpError as exc:
            attempt["error"] = str(exc)
            raise
        except urllib.error.HTTPError as exc:
            attempt["http_status"] = exc.code
            attempt["error"] = "HTTP_FAILURE"
            raise McpError("HTTP_FAILURE") from None
        except TimeoutError:
            attempt["error"] = "REQUEST_TIMEOUT"
            raise McpError("REQUEST_TIMEOUT") from None
        except urllib.error.URLError as exc:
            code = (
                "REQUEST_TIMEOUT" if isinstance(exc.reason, TimeoutError) else "TRANSPORT_FAILURE"
            )
            attempt["error"] = code
            raise McpError(code) from None
        except Exception:
            attempt["error"] = "TRANSPORT_OR_SCHEMA_FAILURE"
            raise McpError("TRANSPORT_OR_SCHEMA_FAILURE") from None
        finally:
            attempt["duration_seconds"] = time.monotonic() - began
            self.attempts.append(attempt)

    def start(self):
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "fx-talanta-calendar-readonly", "version": "1"},
            },
        )
        if result.get("protocolVersion") != "2025-06-18":
            raise McpError("PROTOCOL_CHANGED")
        self.rpc("notifications/initialized", notification=True)

    def tool(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        try:
            data = result.get("structuredContent")
            if data is None:
                data = strict_json(
                    "\n".join(
                        block["text"] for block in result["content"] if block.get("type") == "text"
                    )
                )
            if not isinstance(data, dict) or data.get("ok") is False:
                raise McpError("TOOL_DATA_INVALID")
            return data
        except McpError:
            raise
        except Exception:
            raise McpError("TOOL_SCHEMA_INVALID") from None
