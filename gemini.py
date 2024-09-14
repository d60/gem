import asyncio
import os
import random

import aiohttp

from config import config_ini

if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
DEFAULT_GEMINI_MODEL = config_ini['MAIN']['GeminiModel']
SAFETY_SETTINGS = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_NONE"
    }
]


def build_content_data(text: str | None = None, inline_data_list: list[dict] | None = None) -> dict:
    parts = []
    if text is not None:
        parts.append({'text': text})
    for i in inline_data_list or []:
        parts.append({'inline_data': i})
    return {'parts': parts, 'role': 'user'}


class Gemini:
    def __init__(self) -> None:
        self.session = aiohttp.ClientSession()

    async def generate(self, contents: list[dict], keys: list[str], model: str | None, proxy: str | None = None):
        data = {
            'contents': contents,
            'safetySettings': SAFETY_SETTINGS
        }
        errors = []

        keys = keys.copy()
        random.shuffle(keys)
        for key in keys:
            params = {'key': key}
            async with self.session.post(
                URL.format(model=model or DEFAULT_GEMINI_MODEL), params=params, json=data, proxy=proxy
            ) as response:
                status = response.status
                if 400 <= status < 600:
                    errors.append([await response.json(), status, '...' + key[-5:]])
                    continue
                return await response.json(), errors
        return None, errors

    async def close(self) -> None:
        await self.session.close()
