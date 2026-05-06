import aiohttp
import asyncio
import boto3
import os
import uuid
import logging
from io import BytesIO
from PIL import Image

log = logging.getLogger(__name__)

def _upload_to_s3(img_bytes: bytes, bucket: str, key: str) -> str:
    s3 = boto3.client('s3')
    # ExtraArgs={'ACL': 'public-read'} is often used, but depends on bucket settings.
    # We will assume bucket policies allow public read or we're using presigned URLs,
    # but the instructions requested returning a new public S3 URL.
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=img_bytes,
        ContentType='image/jpeg'
    )
    region = boto3.session.Session().region_name or 'us-east-1'
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

async def process_image(image_url: str) -> str:
    """
    Asynchronously downloads an image from a scraped URL, compresses it to an 
    optimized JPEG (quality 85), and uploads it to an S3 bucket.
    """
    bucket_name = os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        log.warning("S3_BUCKET_NAME not set. Returning original image URL.")
        return image_url

    try:
        # 1. Download
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                resp.raise_for_status()
                img_data = await resp.read()

        # 2. Compress
        def _compress(data: bytes) -> bytes:
            with Image.open(BytesIO(data)) as img:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                out = BytesIO()
                img.save(out, format="JPEG", quality=85, optimize=True)
                return out.getvalue()

        compressed_data = await asyncio.to_thread(_compress, img_data)

        # 3. Upload to S3
        key = f"products/{uuid.uuid4().hex}.jpg"
        s3_url = await asyncio.to_thread(_upload_to_s3, compressed_data, bucket_name, key)
        return s3_url

    except Exception as e:
        log.error(f"Failed to process image {image_url}: {e}", exc_info=True)
        return image_url
