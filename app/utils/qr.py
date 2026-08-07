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
    img = Image.open(io.BytesIO(image_bytes))
    decoded_objs = decode_qr(img)
    if not decoded_objs:
        return ""
    return decoded_objs[0].data.decode('utf-8')
