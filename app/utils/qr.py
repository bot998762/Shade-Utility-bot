import io
import qrcode
from PIL import Image
from pyzbar.pyzbar import decode as decode_qr

def generate_qr_buffer(data: str) -> io.BytesIO:
    qr_img = qrcode.make(data)
    bio = io.BytesIO()
    qr_img.save(bio, 'PNG')
    bio.seek(0)
    return bio

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
