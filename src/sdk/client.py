"""Orchestrator API client SDK."""

import json
import os
import socket
import time
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class DNSFailureHandler:
    """Circuit breaker for DNS resolution failures per hostname."""

    _failures: Dict[str, int] = {}
    _circuit_open_until: Dict[str, float] = {}
    FAILURE_THRESHOLD = 3
    COOLDOWN_SECONDS = 30.0

    @classmethod
    def record_failure(cls, hostname: str) -> None:
        cls._failures[hostname] = cls._failures.get(hostname, 0) + 1
        if cls._failures[hostname] >= cls.FAILURE_THRESHOLD:
            cls._circuit_open_until[hostname] = time.time() + cls.COOLDOWN_SECONDS

    @classmethod
    def record_success(cls, hostname: str) -> None:
        cls._failures.pop(hostname, None)
        cls._circuit_open_until.pop(hostname, None)

    @classmethod
    def is_open(cls, hostname: str) -> bool:
        until = cls._circuit_open_until.get(hostname, 0)
        if until == 0:
            return False
        if time.time() >= until:
            cls.reset(hostname)
            return False
        return True

    @classmethod
    def reset(cls, hostname=None):
        if hostname:
            cls._failures.pop(hostname, None)
            cls._circuit_open_until.pop(hostname, None)
        else:
            cls._failures.clear()
            cls._circuit_open_until.clear()


def _resolve_hostname(url):
    try:
        parsed = url.split("://", 1)[1] if "://" in url else url
        host = parsed.split("/")[0].split(":")[0]
        socket.getaddrinfo(host, 80)
        return host
    except (socket.gaierror, OSError, IndexError):
        return None


class OrchestratorClient:
    def __init__(self, base_url=None, api_key=None):
        self.base_url = base_url or os.getenv("AO_API_URL", "https://api.agent-orchestrator.io")
        self.api_key = api_key or os.getenv("AO_API_KEY", "")
        self._session = None

    def _request(self, method, path, data=None):
        url = f"{self.base_url}/api/v2{path}"
        host_parts = url.split("://", 1)
        hostname = host_parts[1].split("/")[0].split(":")[0] if len(host_parts) > 1 else url

        if DNSFailureHandler.is_open(hostname):
            return {"error": "dns_circuit_open", "message": "DNS resolution for " + hostname + " temporarily blocked"}

        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        body = json.dumps(data).encode() if data else None

        last_error = None
        for attempt in range(3):
            try:
                resolved = _resolve_hostname(url)
                if resolved is None:
                    DNSFailureHandler.record_failure(hostname)
                    return {"error": "dns_failure", "message": "Could not resolve hostname: " + hostname}

                req = Request(url, data=body, headers=headers, method=method)
                with urlopen(req, timeout=10) as resp:
                    DNSFailureHandler.record_success(hostname)
                    return json.loads(resp.read().decode())

            except URLError as e:
                reason_str = str(e.reason).lower() if e.reason else ""
                is_dns = any(kw in reason_str for kw in ["name or service not known", "temporary failure", "nodename nor servname", "getaddrinfo", "dns"])
                if is_dns and attempt < 2:
                    delay = (2 ** attempt) * 0.5
                    time.sleep(delay)
                    last_error = {"error": "dns_failure", "message": str(e.reason)}
                    continue
                elif is_dns:
                    DNSFailureHandler.record_failure(hostname)
                    return {"error": "dns_failure", "message": "DNS resolution failed after 3 retries for " + hostname + ": " + str(e.reason)}
                return {"error": "connection_error", "message": str(e.reason)}

            except socket.timeout:
                return {"error": "timeout", "message": "Request timed out for " + url}

            except HTTPError as e:
                DNSFailureHandler.record_success(hostname)
                return {"error": e.code, "message": e.reason}

        return last_error or {"error": "unknown", "message": "Request failed after all retries"}

    def register_agent(self, name, agent_type, config=None):
        return self._request("POST", "/agents", {"name": name, "agent_type": agent_type, "config": config or {}})

    def list_agents(self, status=None):
        path = "/agents"
        if status:
            path += "?status=" + status
        return self._request("GET", path)

    def get_agent(self, agent_id):
        return self._request("GET", "/agents/" + agent_id)

    def delete_agent(self, agent_id):
        return self._request("DELETE", "/agents/" + agent_id)

    def start_agent(self, agent_id):
        return self._request("POST", "/agents/" + agent_id + "/start")

    def stop_agent(self, agent_id):
        return self._request("POST", "/agents/" + agent_id + "/stop")
