from __future__ import annotations

import base64
import hashlib
import select
import socket
import socketserver
import threading
import time
from typing import Any

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials, RemoteProfile


class SSHError(RuntimeError):
    pass


class HostKeyConfirmationRequired(SSHError):
    def __init__(self, fingerprint: str) -> None:
        super().__init__(f"首次连接需要确认 SSH 主机指纹：{fingerprint}")
        self.fingerprint = fingerprint


class HostKeyMismatchError(SSHError):
    pass


def ssh_runtime_available() -> bool:
    try:
        import paramiko  # noqa: F401
    except ImportError:
        return False
    return True


def format_fingerprint(key: Any) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class _ExpectedFingerprintPolicy:
    def __init__(self, expected: str) -> None:
        self.expected = expected

    def missing_host_key(self, client, hostname: str, key) -> None:
        actual = format_fingerprint(key)
        if actual != self.expected:
            raise HostKeyMismatchError(
                f"SSH 主机指纹不匹配。已保存 {self.expected}，当前 {actual}。"
            )
        client.get_host_keys().add(hostname, key.get_name(), key)


class _ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _handler_for(transport, remote_host: str, remote_port: int):
    class ForwardHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            channel = transport.open_channel(
                "direct-tcpip",
                (remote_host, remote_port),
                self.request.getpeername(),
            )
            if channel is None:
                return
            try:
                while True:
                    readable, _, _ = select.select([self.request, channel], [], [], 1.0)
                    if self.request in readable:
                        data = self.request.recv(65536)
                        if not data:
                            break
                        channel.sendall(data)
                    if channel in readable:
                        data = channel.recv(65536)
                        if not data:
                            break
                        self.request.sendall(data)
            finally:
                channel.close()

    return ForwardHandler


class SshTunnel:
    def __init__(
        self,
        profile: RemoteProfile,
        connect_timeout: float = 15.0,
        *,
        local_bind_host: str = "127.0.0.1",
        local_bind_port: int = 0,
    ) -> None:
        self.profile = profile
        self.connect_timeout = connect_timeout
        self.local_bind_host = local_bind_host
        self.local_bind_port = local_bind_port
        self.client = None
        self.server: _ForwardServer | None = None
        self.thread: threading.Thread | None = None
        self.local_port = 0

    @property
    def base_url(self) -> str:
        if not self.local_port:
            raise SSHError("SSH 隧道尚未建立。")
        return f"http://127.0.0.1:{self.local_port}"

    def probe_fingerprint(self) -> str:
        paramiko = self._paramiko()
        sock = socket.create_connection(
            (self.profile.ssh_host, self.profile.ssh_port),
            timeout=self.connect_timeout,
        )
        transport = paramiko.Transport(sock)
        try:
            transport.start_client(timeout=self.connect_timeout)
            key = transport.get_remote_server_key()
            return format_fingerprint(key)
        finally:
            transport.close()
            sock.close()

    def open(self, credentials: RemoteCredentials | None = None) -> SshTunnel:
        credentials = credentials or RemoteCredentials()
        actual = self.probe_fingerprint()
        expected = self.profile.known_host_fingerprint.strip()
        if not expected:
            raise HostKeyConfirmationRequired(actual)
        if actual != expected:
            raise HostKeyMismatchError(f"SSH 主机指纹不匹配。已保存 {expected}，当前 {actual}。")

        paramiko = self._paramiko()
        connect_args: dict[str, Any] = {
            "hostname": self.profile.ssh_host,
            "port": self.profile.ssh_port,
            "username": self.profile.ssh_user,
            "timeout": self.connect_timeout,
            "banner_timeout": self.connect_timeout,
            "auth_timeout": self.connect_timeout,
        }
        if self.profile.auth_type == RemoteAuthType.PASSWORD:
            if not credentials.password:
                raise SSHError("该云主机配置需要 SSH 密码。")
            connect_args.update(password=credentials.password, look_for_keys=False, allow_agent=False)
        elif self.profile.auth_type == RemoteAuthType.PRIVATE_KEY:
            if self.profile.private_key_path:
                connect_args["key_filename"] = self.profile.private_key_path
            connect_args.update(
                passphrase=credentials.passphrase or None,
                look_for_keys=not bool(self.profile.private_key_path),
                allow_agent=True,
            )
        else:
            connect_args.update(look_for_keys=True, allow_agent=True)
        client = None
        last_error: Exception | None = None
        for attempt in range(3):
            candidate = paramiko.SSHClient()
            candidate.load_system_host_keys()
            candidate.set_missing_host_key_policy(_ExpectedFingerprintPolicy(expected))
            try:
                candidate.connect(**connect_args)
                transport = candidate.get_transport()
                if transport is None or not transport.is_active():
                    raise SSHError("SSH 已连接，但传输通道不可用。")
                client = candidate
                break
            except (paramiko.AuthenticationException, HostKeyMismatchError):
                candidate.close()
                raise
            except (paramiko.SSHException, EOFError, OSError) as exc:
                candidate.close()
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        if client is None:
            raise SSHError(f"SSH 握手连续 3 次失败：{last_error}") from last_error
        try:
            server = _ForwardServer(
                (self.local_bind_host, self.local_bind_port),
                _handler_for(transport, self.profile.comfy_host, self.profile.comfy_port),
            )
            thread = threading.Thread(target=server.serve_forever, name="anima-ssh-tunnel", daemon=True)
            thread.start()
        except Exception:
            client.close()
            raise
        self.client = client
        self.server = server
        self.thread = thread
        self.local_port = int(server.server_address[1])
        return self

    def run_command(self, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
        if not self.client:
            raise SSHError("SSH 尚未连接。")
        _, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace")

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.client:
            self.client.close()
            self.client = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        self.thread = None
        self.local_port = 0

    def __enter__(self) -> SshTunnel:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _paramiko():
        try:
            import paramiko
        except ImportError as exc:
            raise SSHError("SSH 依赖未安装，请运行 pip install -e .[remote]") from exc
        return paramiko
