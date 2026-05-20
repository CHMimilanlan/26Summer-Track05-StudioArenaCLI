"""Small HTTP wrapper for calling a local Synergy agent from studio-arena."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import httpx


class SynergyClientError(Exception):
    """Raised when the local Synergy server returns an error or cannot be reached."""


class SynergyClient:
    """Client for the Synergy local HTTP API.

    This intentionally stays tiny: the CLI only needs to create/find a session
    and send a prompt to a named agent such as ``scholar``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4096",
        directory: Optional[str] = None,
        timeout: float = 600.0,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        self._base_url = base_url.rstrip("/")
        self._directory = directory
        self._timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._directory:
            headers["x-synergy-directory"] = self._directory
        return headers

    @property
    def directory(self) -> Optional[str]:
        return self._directory

    def web_session_url(self, session_id: str) -> str:
        directory = self._directory or "global"
        encoded = base64.urlsafe_b64encode(directory.encode("utf-8")).decode("ascii").rstrip("=")
        return f"{self._base_url}/{encoded}/session/{session_id}"

    async def health(self) -> dict:
        return await self._get("/global/health")

    async def list_agents(self) -> List[dict]:
        data = await self._get("/agent")
        if isinstance(data, list):
            return data
        raise SynergyClientError("Unexpected /agent response from Synergy")

    async def ensure_agent(self, agent: str) -> dict:
        agents = await self.list_agents()
        for item in agents:
            if item.get("name") == agent:
                return item
        names = ", ".join(sorted(str(item.get("name")) for item in agents if item.get("name")))
        raise SynergyClientError(f'Synergy agent "{agent}" not found. Available agents: {names}')

    async def create_session(self, title: Optional[str] = None) -> str:
        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        data = await self._post("/session", payload)
        session_id = data.get("id") if isinstance(data, dict) else None
        if not session_id:
            raise SynergyClientError("Synergy did not return a session id")
        return str(session_id)

    async def prompt(
        self,
        prompt: str,
        *,
        agent: str = "scholar",
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        model: Optional[dict] = None,
        system: Optional[str] = None,
    ) -> dict:
        await self.ensure_agent(agent)
        sid = session_id or await self.create_session(title=title)

        payload: Dict[str, Any] = {
            "agent": agent,
            "parts": [{"type": "text", "text": prompt}],
        }
        if model:
            payload["model"] = model
        if system:
            payload["system"] = system

        data = await self._post(f"/session/{sid}/message", payload)
        if isinstance(data, dict):
            data.setdefault("sessionID", sid)
            data.setdefault("webUrl", self.web_session_url(sid))
            return data
        raise SynergyClientError("Unexpected prompt response from Synergy")

    async def prompt_async(
        self,
        prompt: str,
        *,
        agent: str = "scholar",
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        model: Optional[dict] = None,
        system: Optional[str] = None,
    ) -> dict:
        await self.ensure_agent(agent)
        sid = session_id or await self.create_session(title=title)

        payload: Dict[str, Any] = {
            "agent": agent,
            "parts": [{"type": "text", "text": prompt}],
        }
        if model:
            payload["model"] = model
        if system:
            payload["system"] = system

        await self._post(f"/session/{sid}/prompt_async", payload)
        return {
            "accepted": True,
            "sessionID": sid,
            "agent": agent,
            "directory": self._directory,
            "webUrl": self.web_session_url(sid),
        }

    async def create_agenda(self, payload: dict) -> dict:
        data = await self._post("/agenda", payload)
        if isinstance(data, dict):
            return data
        raise SynergyClientError("Unexpected agenda create response from Synergy")

    async def trigger_agenda(self, agenda_id: str) -> dict:
        data = await self._post(f"/agenda/{agenda_id}/trigger", {})
        if isinstance(data, dict):
            return data
        raise SynergyClientError("Unexpected agenda trigger response from Synergy")

    @staticmethod
    def extract_text(response: dict) -> str:
        parts = response.get("parts") or []
        texts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        ]
        return "\n".join(texts).strip()

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(self._base_url + path, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as exc:
                raise SynergyClientError(
                    f"Cannot connect to Synergy at {self._base_url}. Start it with `synergy start` or `synergy server`."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise SynergyClientError(self._format_http_error(exc.response)) from exc

    async def _post(self, path: str, payload: dict) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(self._base_url + path, headers=self._headers(), json=payload)
                resp.raise_for_status()
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()
            except httpx.ConnectError as exc:
                raise SynergyClientError(
                    f"Cannot connect to Synergy at {self._base_url}. Start it with `synergy start` or `synergy server`."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise SynergyClientError(self._format_http_error(exc.response)) from exc

    @staticmethod
    def _format_http_error(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return f"Synergy HTTP {response.status_code}: {body}"


def parse_model(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    if "/" not in value:
        raise SynergyClientError("Model must be in provider/model format, for example openai/gpt-4o")
    provider_id, model_id = value.split("/", 1)
    if not provider_id or not model_id:
        raise SynergyClientError("Model must be in provider/model format, for example openai/gpt-4o")
    return {"providerID": provider_id, "modelID": model_id}
