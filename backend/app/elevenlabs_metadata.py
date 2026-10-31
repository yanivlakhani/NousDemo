from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import httpx

BASE_URL = "https://api.elevenlabs.io/v1"
CACHE_SECONDS = 60
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


def _mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"


def _attached_tools(agent: dict[str, Any]) -> list[dict[str, str | None]]:
    found: dict[str, dict[str, str | None]] = {}

    def visit(value: Any, parent_key: str = "") -> None:
        if isinstance(value, dict):
            if parent_key in {"tools", "tool", "tool_config"}:
                identifier = value.get("tool_id") or value.get("id") or value.get("name")
                if identifier:
                    found[str(identifier)] = {"id": str(identifier), "name": value.get("name"), "type": value.get("type")}
            for key, item in value.items():
                if key == "tool_ids" and isinstance(item, list):
                    for identifier in item:
                        found[str(identifier)] = {"id": str(identifier), "name": None, "type": None}
                else:
                    visit(item, key)
        elif isinstance(value, list):
            for item in value:
                if parent_key == "tools" and isinstance(item, dict):
                    identifier = item.get("tool_id") or item.get("id") or item.get("name")
                    if identifier:
                        found[str(identifier)] = {"id": str(identifier), "name": item.get("name"), "type": item.get("type")}
                visit(item, parent_key)

    visit(agent)
    return sorted(found.values(), key=lambda row: row["name"] or row["id"])


def _tool_summary(payload: Any, tool_id: str) -> dict[str, str | None]:
    """Extract display-safe tool metadata from ElevenLabs' nested tool response."""
    if not isinstance(payload, dict):
        return {"id": tool_id, "name": None, "type": None}
    config = payload.get("tool_config") if isinstance(payload.get("tool_config"), dict) else {}
    webhook = config.get("webhook") if isinstance(config.get("webhook"), dict) else {}
    return {
        "id": str(payload.get("tool_id") or payload.get("id") or tool_id),
        "name": payload.get("name") or config.get("name") or webhook.get("name"),
        "type": payload.get("type") or config.get("type") or ("webhook" if webhook else None),
    }


async def fetch_elevenlabs_metadata(
    api_key: str,
    agent_id: str,
    phone_number_id: str | None = None,
    *,
    refresh: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    cache_key = f"{agent_id}:{phone_number_id or ''}"
    now = time.monotonic()
    if not refresh and cache_key in _cache and now - _cache[cache_key][0] < CACHE_SECONDS:
        return {**_cache[cache_key][1], "cached": True}

    async with _cache_lock:
        now = time.monotonic()
        if not refresh and cache_key in _cache and now - _cache[cache_key][0] < CACHE_SECONDS:
            return {**_cache[cache_key][1], "cached": True}
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=12, headers={"xi-api-key": api_key})
        try:
            requests = [
                client.get(f"{BASE_URL}/convai/agents/{agent_id}"),
                client.get(f"{BASE_URL}/convai/settings"),
                client.get(f"{BASE_URL}/workspace/webhooks", params={"include_usages": "true"}),
            ]
            if phone_number_id:
                requests.append(client.get(f"{BASE_URL}/convai/phone-numbers/{phone_number_id}"))
            else:
                requests.append(client.get(f"{BASE_URL}/convai/phone-numbers", params={"agent_id": agent_id}))
            responses = await asyncio.gather(*requests, return_exceptions=True)

            payloads: list[Any] = []
            checks: dict[str, str] = {}
            for name, response in zip(("agent", "settings", "webhooks", "phone"), responses):
                if isinstance(response, Exception):
                    checks[name] = "unavailable"
                    payloads.append({})
                elif response.is_success:
                    checks[name] = "ok"
                    payloads.append(response.json())
                else:
                    checks[name] = f"http_{response.status_code}"
                    payloads.append({})
            agent, workspace_settings, webhook_payload, phone_payload = payloads
            attached_tools = _attached_tools(agent)
            unresolved_tools = [tool for tool in attached_tools if not tool.get("name")]
            if unresolved_tools:
                tool_responses = await asyncio.gather(
                    *(client.get(f"{BASE_URL}/convai/tools/{tool['id']}") for tool in unresolved_tools),
                    return_exceptions=True,
                )
                resolved_by_id: dict[str, dict[str, str | None]] = {}
                for tool, response in zip(unresolved_tools, tool_responses):
                    if not isinstance(response, Exception) and response.is_success:
                        resolved_by_id[str(tool["id"])] = _tool_summary(response.json(), str(tool["id"]))
                attached_tools = [resolved_by_id.get(str(tool["id"]), tool) for tool in attached_tools]
            phones = phone_payload if isinstance(phone_payload, list) else ([phone_payload] if phone_payload else [])
            selected_webhook_id = (workspace_settings.get("webhooks") or {}).get("post_call_webhook_id")
            webhooks = webhook_payload.get("webhooks", []) if isinstance(webhook_payload, dict) else []
            selected_webhook = next((item for item in webhooks if item.get("webhook_id") == selected_webhook_id), None)
            result = {
                "provider": "elevenlabs",
                "configured": True,
                "cached": False,
                "fetched_at": datetime.now(UTC).isoformat(),
                "checks": checks,
                "agent": {
                    "id": agent.get("agent_id", agent_id),
                    "name": agent.get("name"),
                    "version_id": agent.get("version_id"),
                    "branch_id": agent.get("branch_id"),
                    "main_branch_id": agent.get("main_branch_id"),
                    "tags": agent.get("tags", []),
                    "attached_tools": attached_tools,
                },
                "phone_assignment": {
                    "configured_id": phone_number_id,
                    "assigned": any((item.get("assigned_agent") or {}).get("agent_id") == agent_id for item in phones),
                    "phones": [{"id": item.get("phone_number_id"), "label": item.get("label"), "provider": item.get("provider"), "number": _mask_phone(item.get("phone_number")), "branch_id": (item.get("assigned_agent") or {}).get("branch_id")} for item in phones],
                },
                "webhook": {
                    "configured": bool(selected_webhook_id),
                    "id": selected_webhook_id,
                    "active": bool(selected_webhook and not selected_webhook.get("is_disabled") and not selected_webhook.get("is_auto_disabled")),
                    "auth_type": selected_webhook.get("auth_type") if selected_webhook else None,
                    "events": (workspace_settings.get("webhooks") or {}).get("events", []),
                    "retry_enabled": selected_webhook.get("retry_enabled") if selected_webhook else None,
                    "most_recent_failure_code": selected_webhook.get("most_recent_failure_error_code") if selected_webhook else None,
                },
            }
            first_phone = phones[0] if phones else {}
            webhook_status = "Active" if result["webhook"]["active"] else ("Configured but inactive" if selected_webhook_id else "Not configured")
            failed_checks = [name for name, status in checks.items() if status != "ok"]
            result.update({
                "available": checks.get("agent") == "ok",
                "agent_id": result["agent"]["id"],
                "agent_name": result["agent"]["name"],
                "agent_version": result["agent"]["version_id"],
                "version": result["agent"]["version_id"],
                "branch": result["agent"]["branch_id"],
                "attached_tools": [{**tool, "name": tool["name"] or tool["id"]} for tool in result["agent"]["attached_tools"]],
                "tools": [{**tool, "name": tool["name"] or tool["id"]} for tool in result["agent"]["attached_tools"]],
                "phone_number": _mask_phone(first_phone.get("phone_number")),
                "phone_number_id": first_phone.get("phone_number_id") or phone_number_id,
                "webhook_status": webhook_status,
                "last_sync_at": result["fetched_at"],
                "last_error": f"Unavailable checks: {', '.join(failed_checks)}" if failed_checks else None,
            })
            _cache[cache_key] = (time.monotonic(), result)
            return result
        finally:
            if owns_client:
                await client.aclose()


def unavailable_metadata(reason: str) -> dict[str, Any]:
    return {"provider": "elevenlabs", "configured": False, "cached": False, "reason": reason, "agent": None, "phone_assignment": {"assigned": False, "phones": []}, "webhook": {"configured": False, "active": False}}
