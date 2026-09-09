"""Turning a user's attachment into something a model may be shown.

Everything here is a boundary. An attachment arrives from a person, carries
bytes we did not produce, and is on its way out of the building to a third
party -- so this module answers four questions before any of it leaves:

* **may this user read it?** Odoo will not answer that for us. The docstring on
  ``mail.thread._process_attachments_for_post`` says so outright: attachments
  are linked in ``sudo`` and *"the caller must verify the access rights
  accordingly"*. For an INTERNAL user core performs no ownership check at all,
  so an id belonging to somebody else's record would otherwise be posted and
  read quite happily. We check, as the posting user, never sudo.
* **is it an image at all, of a kind the model accepts?** Four types, checked
  against the decoded bytes rather than the declared mimetype, because the
  declared one is user input.
* **is it small enough?** Twice: bytes on the way in, and pixels on the way out.
* **what does it cost?** An image is billed as input tokens, and neither history
  cap bounds it -- ``MAX_HISTORY_CHARS`` counts characters and an image has
  none. So it is downscaled to a known ceiling instead of being trusted.

What is deliberately NOT here: any reading of a path, a URL, or the filestore by
name. The only input is an ``ir.attachment`` recordset the caller already holds.
"""

import base64
import logging

from odoo.exceptions import AccessError, UserError
from odoo.tools.image import image_process

_logger = logging.getLogger(__name__)

#: What the model can actually read. Anything else is refused rather than
#: converted: silently transcoding a user's file changes what they think they
#: sent.
ALLOWED_MEDIA_TYPES = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')

#: Magic numbers, because ``mimetype`` on the attachment is whatever the client
#: claimed. A .exe renamed to .png announces itself as image/png.
_SIGNATURES = (
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
)

#: Per image, before processing. The vendor's own ceiling is 10 MB base64; this
#: is lower on purpose, because a demo user photographing a pallet has no reason
#: to send 10 MB and the cost of finding out is a wasted provider call.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: Per turn. More than a handful of images in one question is not a question.
MAX_IMAGES_PER_TURN = 4

#: Longest edge after downscaling.
#:
# ponytail: fixed ceiling, not a per-model lookup. Visual tokens are
# ceil(w/28) * ceil(h/28), so 1568px caps one image near 1,568 tokens. The
# models in use would accept 2576px and up to ~4,784 tokens -- three times the
# cost -- and nothing in this product reads fine print off a photograph. Make it
# a profile field if a use case ever needs the detail.
MAX_LONG_EDGE = 1568


class ImageRejected(UserError):
    """Refused for a reason the user should see and can act on.

    Deliberately a UserError and deliberately specific: unlike a guard denial,
    "your file was too big" leaks nothing and telling somebody their photograph
    was ignored without saying why is a support ticket.
    """


def _sniff(raw):
    """The media type the BYTES claim, not the one the record claims."""
    for signature, media_type in _SIGNATURES:
        if raw.startswith(signature):
            return media_type
    if raw[0:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    return None


def collect(attachments, user, model=None, provider=None):
    """``(blocks, rejections)`` for one turn's attachments.

    ``blocks`` are neutral image blocks in the shape ``services/provider.py``
    documents. ``rejections`` are human sentences, already safe to show.

    Never raises for a bad file: one unreadable attachment must not lose the
    question the user typed alongside it.
    """
    blocks, rejections = [], []
    if not attachments:
        return blocks, rejections

    if provider is not None and not provider.supports_images(model=model):
        return blocks, [
            "This agent's model cannot read images, so the attached file was "
            "not sent. The written question was answered on its own."]

    for attachment in attachments:
        if len(blocks) >= MAX_IMAGES_PER_TURN:
            rejections.append(
                "Only the first %d images were sent; the rest were ignored."
                % MAX_IMAGES_PER_TURN)
            break
        try:
            block = _one(attachment, user)
        except ImageRejected as rejected:
            rejections.append(str(rejected))
            continue
        if block:
            blocks.append(block)
    return blocks, rejections


def _one(attachment, user):
    """Validate and normalise a single attachment, or raise ImageRejected."""
    # 1. May this user read it? As the user. Odoo does not do this for us.
    try:
        attachment.with_user(user).check_access('read')
    except AccessError:
        # Deliberately the same sentence as "there is no such file". Telling an
        # attacker which ids exist is the whole of an enumeration oracle.
        raise ImageRejected("An attached file could not be read.")

    # Read the bytes as the user too, so a record rule cannot be sidestepped
    # by having passed the access check on a different recordset.
    raw = attachment.with_user(user).raw or b''
    if not raw:
        raise ImageRejected("An attached file was empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageRejected(
            "%s is larger than the %d MB limit for images."
            % (attachment.name or 'A file', MAX_IMAGE_BYTES // (1024 * 1024)))

    # 2. Is it an image, really?
    sniffed = _sniff(raw)
    if sniffed not in ALLOWED_MEDIA_TYPES:
        raise ImageRejected(
            "%s is not an image the agent can read. Supported: JPEG, PNG, GIF "
            "and WebP." % (attachment.name or 'A file'))

    # 3. Downscale. verify_resolution rejects a decompression bomb before PIL
    # allocates it -- a 40 MP image inside a 200 KB file is a real shape.
    try:
        processed = image_process(
            raw, size=(MAX_LONG_EDGE, MAX_LONG_EDGE), verify_resolution=True)
    except (UserError, ValueError):
        raise ImageRejected(
            "%s could not be decoded as an image."
            % (attachment.name or 'A file'))
    processed = processed or raw

    # image_process returns the ORIGINAL bytes untouched for WebP, so the type
    # is re-sniffed rather than assumed to have survived.
    media_type = _sniff(processed)
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise ImageRejected(
            "%s could not be prepared for the agent."
            % (attachment.name or 'A file'))

    # Nothing above logs `raw`, `processed` or the base64, and nothing below
    # returns them anywhere except into the provider call itself.
    _logger.info(
        "ai image accepted: attachment=%s type=%s bytes=%s->%s",
        attachment.id, media_type, len(raw), len(processed))
    return {
        'type': 'image',
        'media_type': media_type,
        'data': base64.b64encode(processed).decode('ascii'),
        # Kept for the audit row. The DATA is never audited; this is.
        'name': attachment.name or '',
        'bytes': len(processed),
    }


def audit_summary(blocks):
    """What may be written down about an image. Never the image."""
    return [{'name': block.get('name'), 'media_type': block.get('media_type'),
             'bytes': block.get('bytes')} for block in blocks]


def to_provider_blocks(blocks):
    """Strip the bookkeeping keys the provider has no business receiving."""
    return [{'type': 'image', 'media_type': block['media_type'],
             'data': block['data']} for block in blocks]
