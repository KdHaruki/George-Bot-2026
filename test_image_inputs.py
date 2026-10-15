import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from image_inputs import ImageSource, load_images, ambient_image_sources, MAX_IMAGE_BYTES
from ambient_chat import AmbientChat

PNG = b"\x89PNG\r\n\x1a\n" + b"test-image-data"


def attachment(data=PNG, size=None, filename="image.png", content_type="image/png"):
    return SimpleNamespace(filename=filename, content_type=content_type, size=len(data) if size is None else size,
                           read=AsyncMock(return_value=data))


class ImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_images_and_no_extra_download(self):
        items = [attachment() for _ in range(3)]
        result = await load_images([ImageSource(item, str(index)) for index, item in enumerate(items)])
        self.assertEqual(len(result.images), 2)
        self.assertTrue(result.notices)
        items[2].read.assert_not_awaited()
        self.assertEqual(result.images[0].data, PNG)

    async def test_invalid_and_oversized_attachments_not_forwarded(self):
        oversized = attachment(size=MAX_IMAGE_BYTES + 1)
        unsupported = attachment(filename="document.pdf", content_type="application/pdf")
        for item in (oversized, unsupported, attachment(data=b"not-a-png")):
            result = await load_images([ImageSource(item, "今回の画像")])
            self.assertFalse(result.images)
            self.assertTrue(result.notices)
        oversized.read.assert_not_awaited()
        unsupported.read.assert_not_awaited()

    async def test_expired_attachment_is_reported_without_exception_text(self):
        item = attachment()
        item.read.side_effect = RuntimeError("signed-secret-url")
        result = await load_images([ImageSource(item, "画像")])
        self.assertFalse(result.images)
        self.assertNotIn("signed-secret-url", str(result.notices))

    async def test_latest_images_keep_author_and_message_association(self):
        a, b, c = attachment(), attachment(), attachment()
        messages = [(0, 10, "Aの画像", (a,)), (3600, 20, "Bの画像", (b,)), (7200, 10, "次の画像", (c,))]
        sources = ambient_image_sources(messages)
        self.assertIs(sources[0].attachment, b)
        self.assertIs(sources[1].attachment, c)
        self.assertIn("発言2・参加者2", sources[0].label)
        self.assertIn("発言3・参加者1", sources[1].label)

    async def test_image_only_messages_are_retained_without_download(self):
        chat = AmbientChat()
        item = attachment()
        chat.observe(1, 10, "", attachments=(item,), now=0)
        chat.observe(1, 20, "かわいいね", now=3600)
        state = chat.observe(1, 10, "でしょ", now=7200)
        self.assertIsNotNone(state)
        self.assertIs(state.messages[0][3][0], item)
        item.read.assert_not_awaited()
