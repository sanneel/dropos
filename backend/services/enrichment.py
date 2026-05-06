import json
import os
import logging
from openai import AsyncOpenAI

log = logging.getLogger(__name__)

async def enrich_product(title: str, description: str) -> dict:
    """
    Prompts the LLM to return a clean, native-English Instagram caption
    and 5 relevant hashtags in JSON format.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set. Using fallback mock data for enrichment.")
        return {
            "caption": f"🌟 Check out this amazing product: {title}\n\nPerfect for your everyday needs. Don't miss out! ✨",
            "hashtags": ["#musthave", "#shopping", "#deals", "#trendy", "#lifestyle"]
        }

    client = AsyncOpenAI(api_key=api_key)
    prompt = (
        f"Create a native-English Instagram caption for the following product:\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        "Return the output STRICTLY as a JSON object with two keys:\n"
        "1. 'caption': A fun, engaging Instagram caption (include a few emojis).\n"
        "2. 'hashtags': An array of 5 relevant hashtags.\n"
        "Do not include any other text, just the raw JSON."
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert social media manager and copywriter."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        return {
            "caption": data.get("caption", ""),
            "hashtags": data.get("hashtags", [])
        }
    except Exception as e:
        log.error(f"Failed to enrich product: {e}", exc_info=True)
        return {"caption": title, "hashtags": []}
