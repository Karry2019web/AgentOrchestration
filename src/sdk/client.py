"""Orchestrator API client SDK."""

import json
import os
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class OrchestratorClient:
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or os.getenv("AO_API_URL", "https://api.agent-orchestrator.io")
        self.api_key = api_key or os.getenv("AO_API_KEY", "")
        self._session = None

    def _request(self, method: str, path: str, data: Dict = None) -> Dict:
        url = f"{self.base_url}/api/v2{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            error_detail = {
                "error": e.code,
                "message": e.reason,
                "method": method,
                "path": path,
            }
            return error_detail
        except URLError as e:
            return {
                "error": "connection_error",
                "message": str(e.reason) if e.reason else "Unknown network error",
                "method": method,
                "path": path,
            }
        except OSError as e:
            return {
                "error": "transport_error",
                "message": str(e),
                "method": method,
                "path": path,
            }

    def register_agent(self, name: str, agent_type: str, config: Dict = None) -> Dict:
        return self._request("POST", "/agents", {
            "name": name,
            "agent_type": agent_type,
            "config": config or {},
        })

    def list_agents(self, status: str = None) -> Dict:
        path = "/agents"
        if status:
            path += f"?status={status}"
        return self._request("GET", path)

    def get_agent(self, agent_id: str) -> Dict:
        return self._request("GET", f"/agents/{agent_id}")

    def delete_agent(self, agent_id: str) -> Dict:
        return self._request("DELETE", f"/agents/{agent_id}")

    def start_agent(self, agent_id: str) -> Dict:
        return self._request("POST", f"/agents/{agent_id}/start")

    def stop_agent(self, agent_id: str) -> Dict:
        return self._request("POST", f"/agents/{agent_id}/stop")
