#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import truststore
truststore.inject_into_ssl()

from src.config import settings
from src.outputs.typefully import schedule_post


async def main() -> None:
    print(f"API key: {settings.typefully_api_key[:8]}...")
    draft_id = await schedule_post(
        "Test post from linkedin-agent. Ignore this.",
        settings.typefully_api_key,
    )
    print(f"Draft ID: {draft_id}")


asyncio.run(main())
