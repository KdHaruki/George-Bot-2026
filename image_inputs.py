"""Read bounded Discord attachments only when a reply is being generated."""
import asyncio
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_IMAGES = 2
MAX_IMAGE_BYTES = 4 * 1024 * 1024
SUPPORTED = {"image/png", "image/jpeg", "image/webp"}
EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


@dataclass(frozen=True)
class ImageSource:
    attachment: object
    label: str


@dataclass(frozen=True)
class LoadedImage:
    data: bytes
    mime_type: str
    label: str


@dataclass
class ImageBundle:
    images: list
    notices: list


def attachment_mime(attachment):
    declared = (getattr(attachment, "content_type", None) or "").split(";")[0].lower()
    return declared if declared in SUPPORTED else EXTENSIONS.get(PurePosixPath(getattr(attachment, "filename", "")).suffix.lower())


def detected_mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def load_images(sources):
    images, notices = [], []
    if len(sources) > MAX_IMAGES:
        notices.append("画像は最大2枚までなので、残りの添付は読んでいないぜ。")
    for source in sources[:MAX_IMAGES]:
        attachment = source.attachment
        mime = attachment_mime(attachment)
        if not mime:
            notices.append("未対応の添付があるぜ。読めるのはPNG・JPEG・WebPだ。")
            continue
        if not 0 < getattr(attachment, "size", 0) <= MAX_IMAGE_BYTES:
            notices.append("空の画像か4MiBを超える画像は読めないぜ。")
            continue
        try:
            data = await asyncio.wait_for(attachment.read(), timeout=10)
        except Exception:
            notices.append("取得できない画像があったぜ。必要ならもう一度添付してくれ。")
            continue
        if not data or len(data) > MAX_IMAGE_BYTES or detected_mime(data) != mime:
            notices.append("画像の形式か容量を確認できず、読み込めなかったぜ。")
            continue
        images.append(LoadedImage(data, mime, source.label))
    return ImageBundle(images, list(dict.fromkeys(notices)))


def ambient_image_sources(messages):
    speakers = {}
    sources = []
    for index, message in enumerate(messages):
        author_id = message[1]
        speakers.setdefault(author_id, len(speakers) + 1)
        attachments = message[3] if len(message) > 3 else ()
        for image_index, attachment in enumerate(attachments):
            if attachment_mime(attachment):
                sources.append(ImageSource(attachment, f"発言{index + 1}・参加者{speakers[author_id]}の添付画像{image_index + 1}"))
    return sources[-MAX_IMAGES:]
