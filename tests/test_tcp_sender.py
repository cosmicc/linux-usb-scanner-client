"""Tests for TCP scan sending."""

from __future__ import annotations

import socket
import threading
import unittest

from linux_usb_scanner_client.config import ServerConfig
from linux_usb_scanner_client.tcp_sender import TcpScanSender


class TcpSenderTests(unittest.TestCase):
    """TCP sender tests."""

    def test_sends_crlf_terminated_scan(self) -> None:
        received = bytearray()
        ready = threading.Event()

        def server() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                port_holder.append(listener.getsockname()[1])
                ready.set()
                conn, _ = listener.accept()
                with conn:
                    received.extend(conn.recv(1024))

        port_holder: list[int] = []
        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(timeout=2))

        sender = TcpScanSender(
            ServerConfig(
                host="127.0.0.1",
                port=port_holder[0],
                connect_timeout=2,
                send_timeout=2,
            )
        )
        sender.send_scan("1234567890")
        sender.disconnect()
        thread.join(timeout=2)

        self.assertEqual(bytes(received), b"1234567890\r\n")


if __name__ == "__main__":
    unittest.main()

