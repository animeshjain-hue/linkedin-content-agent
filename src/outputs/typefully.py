"""Typefully API client — schedules approved posts to the next free slot."""
import structlog

log = structlog.get_logger()

TYPEFULLY_API_BASE = "https://api.typefully.com/v2"


async def _get_social_set_id(client: "httpx.AsyncClient", headers: dict[str, str]) -> str | None:  # type: ignore[name-defined]
    resp = await client.get(f"{TYPEFULLY_API_BASE}/social-sets", headers=headers, timeout=15.0)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if results:
        return str(results[0]["id"])
    return None


async def schedule_post(body: str, api_key: str) -> str | None:
    """Schedule post to Typefully for LinkedIn. Returns draft ID or None on skip/error."""
    if not api_key or api_key == "placeholder":
        log.info("typefully_skipped", reason="api_key not configured")
        return None

    try:
        import httpx
        import truststore
        truststore.inject_into_ssl()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            social_set_id = await _get_social_set_id(client, headers)
            if not social_set_id:
                log.error("typefully_error", error="no LinkedIn social set found")
                return None

            resp = await client.post(
                f"{TYPEFULLY_API_BASE}/social-sets/{social_set_id}/drafts",
                headers=headers,
                json={
                    "platforms": {
                        "linkedin": {
                            "enabled": True,
                            "posts": [{"text": body}],
                        }
                    },
                    "publish_at": "next-free-slot",
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            draft_id: str = resp.json().get("id", "unknown")
            log.info("typefully_scheduled", draft_id=draft_id)
            return draft_id

    except Exception as exc:
        log.error("typefully_error", error=str(exc))
        return None
