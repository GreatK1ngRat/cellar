"""Compresses a user-uploaded wine photo before it's saved to disk.

Unlike everywhere else in this app, an uploaded photo is real image data
that has to actually be stored -- there's no listing URL to point at
instead. Pillow is the one genuinely new dependency in this project (every
other addition avoided one, e.g. hashing wine label text with stdlib
PBKDF2 instead of adding bcrypt) because there's no way to decode and
resize an image in pure Python without an imaging library.
"""
import io
import logging

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger("cellar.photos")

# Long-edge cap and JPEG quality chosen to keep a label's text readable --
# a wine label lives or dies on its text, so this errs toward "still
# legible" over "as small as possible." A typical phone photo compresses
# from several MB down to roughly 150-400 KB at these settings.
MAX_DIMENSION = 1200
JPEG_QUALITY = 85
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # reject absurdly large uploads outright


class UnsupportedImage(Exception):
    """Raised when the upload isn't a format Pillow can decode."""


def process_upload(raw_bytes: bytes) -> bytes:
    """Returns compressed JPEG bytes for a user-uploaded photo.

    Raises UnsupportedImage if the bytes aren't a decodable image (e.g. a
    non-image file, or a format Pillow doesn't support -- notably HEIC,
    which some iPhones produce, isn't decodable without an extra plugin
    this project deliberately doesn't add).
    """
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise UnsupportedImage("File is too large")

    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()  # force a full decode now, not lazily on first use
    except UnidentifiedImageError:
        raise UnsupportedImage("Not a recognizable image file (HEIC isn't supported -- use JPEG or PNG)")

    # Phones store rotation as EXIF metadata rather than rotating the
    # pixels -- without this, a portrait label photo can come out sideways.
    image = ImageOps.exif_transpose(image)

    # JPEG has no alpha channel; flatten transparency onto white first,
    # or Pillow raises trying to save an RGBA image as JPEG.
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    if max(image.size) > MAX_DIMENSION:
        image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    result = out.getvalue()

    logger.info("photo upload: %d bytes in, %d bytes out, %dx%d",
                len(raw_bytes), len(result), image.width, image.height)
    return result
