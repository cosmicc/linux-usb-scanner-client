"""Persistent TCP sender for industrial-scanner-logger."""

from __future__ import annotations

import socket
from dataclasses import dataclass

from .config import ServerConfig


class TcpSenderError(OSError):
    """Raised when the TCP sender cannot connect or write."""


@dataclass
class TcpScanSender:
    """Persistent TCP client that sends scanner frames to the logger."""

    config: ServerConfig
    _socket: socket.socket | None = None

    @property
    def connected(self) -> bool:
        """Return whether a socket is currently open."""

        return self._socket is not None

    def connect(self) -> None:
        """Open the TCP connection if it is not already open."""

        if self._socket is not None:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.config.connect_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.config.tcp_keepalive:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        try:
            sock.connect((self.config.host, self.config.port))
            sock.settimeout(self.config.send_timeout)
        except OSError as exc:
            sock.close()
            raise TcpSenderError(str(exc)) from exc

        self._socket = sock

    def send_scan(self, barcode: str) -> None:
        """Send one barcode using the logger-compatible CRLF frame."""

        self.connect()
        payload = (barcode + "\r\n").encode("utf-8")
        try:
            self._socket.sendall(payload)  # type: ignore[union-attr]
        except OSError as exc:
            self.disconnect()
            raise TcpSenderError(str(exc)) from exc

    def disconnect(self) -> None:
        """Close the TCP connection."""

        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
