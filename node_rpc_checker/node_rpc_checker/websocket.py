import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import time
import urllib.parse
from typing import Any
from .config import validate_url
from . import __version__

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

class WebSocketConnection:
    def __init__(self, url: str, timeout: float):
        self.url = url
        self.timeout = timeout
        self.socket: socket.socket | ssl.SSLSocket | None = None

    def __enter__(self) -> "WebSocketConnection":
        validate_url(self.url, ('ws', 'wss'))
        self.deadline = time.monotonic() + self.timeout
        parsed = urllib.parse.urlsplit(self.url)
        secure = parsed.scheme == "wss"
        port = parsed.port or (443 if secure else 80)
        raw_socket = socket.create_connection((parsed.hostname, port), timeout=self.timeout)
        self.socket = raw_socket
        raw_socket.settimeout(self.timeout)
        try:
            if secure:
                context = ssl.create_default_context()
                self._remaining()
                self.socket = context.wrap_socket(raw_socket, server_hostname=parsed.hostname)

            key = base64.b64encode(os.urandom(16)).decode()
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            default_port = 443 if secure else 80
            host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
            host = host if port == default_port else f"{host}:{port}"
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                f"User-Agent: node-rpc-checker/{__version__}\r\n\r\n"
            )
            self._remaining()
            self.socket.sendall(request.encode("ascii"))
            headers, remainder = self._read_headers()
            status_line, *header_lines = headers.decode("iso-8859-1").split("\r\n")
            if " 101 " not in status_line:
                raise RuntimeError(status_line)
            response_headers = {}
            for line in header_lines:
                if ":" in line:
                    name, value = line.split(":", 1)
                    response_headers[name.strip().lower()] = value.strip()
            expected = base64.b64encode(
                hashlib.sha1((key + WS_GUID).encode()).digest()
            ).decode()
            if response_headers.get("sec-websocket-accept") != expected:
                raise RuntimeError("invalid Sec-WebSocket-Accept")
            if response_headers.get('upgrade','').lower() != 'websocket' or 'upgrade' not in {s.strip() for s in response_headers.get('connection','').lower().split(',')}:
                raise RuntimeError('invalid WebSocket upgrade headers')
            self._buffer = bytearray(remainder)
            return self
        except Exception:
            self.__exit__()
            raise

    def __exit__(self, *_: Any) -> None:
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass

    def _read_headers(self) -> tuple[bytes, bytes]:
        assert self.socket is not None
        data = bytearray()
        while b"\r\n\r\n" not in data:
            self._remaining()
            chunk = self.socket.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed during WebSocket handshake")
            data.extend(chunk)
            if len(data) > 65536:
                raise RuntimeError("WebSocket response headers are too large")
        headers, remainder = bytes(data).split(b"\r\n\r\n", 1)
        return headers, remainder

    def _read_exact(self, length: int) -> bytes:
        assert self.socket is not None
        while len(self._buffer) < length:
            self._remaining()
            chunk = self.socket.recv(max(4096, length - len(self._buffer)))
            if not chunk:
                raise RuntimeError("WebSocket connection closed")
            self._buffer.extend(chunk)
        result = bytes(self._buffer[:length])
        del self._buffer[:length]
        return result

    def send_json(self, payload: dict[str, Any]) -> None:
        assert self.socket is not None
        self._remaining()
        data = json.dumps(payload, separators=(",", ":")).encode()
        mask = os.urandom(4)
        length = len(data)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.socket.sendall(bytes(header) + mask + masked)

    def receive_json(self) -> Any:
        fragments = bytearray()
        started = False
        while True:
            self._remaining()
            first, second = self._read_exact(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            if first & 0x70 or masked:
                raise RuntimeError('invalid server frame flags')
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > 1_048_576 or len(fragments) + length > 1_048_576:
                raise RuntimeError("WebSocket message exceeds 1 MiB")
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("WebSocket server closed the connection")
            if opcode == 0x9:
                if not final or length > 125:
                    raise RuntimeError('invalid ping frame')
                self._send_control(0xA, payload)
                continue
            if opcode == 0xA:
                if not final or length > 125:
                    raise RuntimeError('invalid pong frame')
                continue
            if opcode in {0x0, 0x1}:
                if (opcode == 0x0 and not started) or (opcode == 0x1 and started):
                    raise RuntimeError('invalid continuation frame')
                started = True
                fragments.extend(payload)
                if final:
                    return json.loads(fragments.decode("utf-8"))
            else:
                raise RuntimeError('unsupported WebSocket opcode')

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('WebSocket deadline exceeded')
        self.socket.settimeout(remaining)

    def _send_control(self, opcode: int, payload: bytes) -> None:
        assert self.socket is not None
        self._remaining()
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)
