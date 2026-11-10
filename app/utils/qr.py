import io
import qrcode
from PIL import Image
from pyzbar.pyzbar import decode as decode_qr

def _raise_if_data_overflow(data: str) -> None:
    """Raise ``DataOverflowError`` if *data* cannot fit in any QR version.

    qrcode's auto-fit path (``fit=True``) assigns version 41 to
    ``QRCode.version`` before checking capacity; the setter's range check
    then raises a bare ``ValueError`` and the library's own
    ``DataOverflowError`` is never reached (verified on qrcode 7.4.2, 8.0
    and 8.2). Encoding at the fixed maximum version uses the capacity check
    that does raise ``DataOverflowError``, so no message matching is needed.
    Returns normally when the data does fit, so the caller can re-raise the
    original, unrelated ``ValueError``.
    """
    probe = qrcode.QRCode(version=40)
    probe.add_data(data)
    probe.make(fit=False)


def _version_from_image(qr_img) -> int | None:
    """QR version (1-40) of an image returned by ``qrcode.make``, or None.

    ``width`` is the module count per side (17 + 4 * version) in qrcode 7.x
    and 8.x. If the attribute is missing or odd the version is unknown and
    callers simply skip density-based hints (fail safe).
    """
    modules = getattr(qr_img, "width", None)
    if isinstance(modules, int) and modules >= 21 and (modules - 17) % 4 == 0:
        return (modules - 17) // 4
    return None


def generate_qr_with_version(data: str) -> tuple[io.BytesIO, int | None]:
    """Return ``(png_buffer, qr_version)``; the version is None if unknown."""
    try:
        qr_img = qrcode.make(data)
    except ValueError:
        # Oversized input surfaces as DataOverflowError (from the probe);
        # any other ValueError is re-raised unchanged.
        _raise_if_data_overflow(data)
        raise
    version = _version_from_image(qr_img)
    bio = io.BytesIO()
    qr_img.save(bio, 'PNG')
    bio.seek(0)
    return bio, version


def generate_qr_buffer(data: str) -> io.BytesIO:
    """Unchanged public API: the PNG buffer only."""
    return generate_qr_with_version(data)[0]

def scan_qr_from_bytes(image_bytes: bytes) -> str:
    """Legacy single-result scan — preserved for backward compatibility."""
    img = Image.open(io.BytesIO(image_bytes))
    decoded_objs = decode_qr(img)
    if not decoded_objs:
        return ""
    return decoded_objs[0].data.decode('utf-8', errors='replace')


def scan_qr_all_from_bytes(image_bytes: bytes) -> list[dict]:
    """
    Phase 2K — multi-QR detection with format/type metadata.

    Returns a list of dicts, one per detected barcode:
        {
            "data":   str,   # decoded text
            "type":   str,   # e.g. "QRCODE", "EAN13", "CODE128"
        }
    Returns [] when nothing is detected.
    """
    img = Image.open(io.BytesIO(image_bytes))
    decoded_objs = decode_qr(img)
    results = []
    for obj in decoded_objs:
        results.append({
            "data": obj.data.decode('utf-8', errors='replace'),
            "type": str(obj.type),
        })
    return results
