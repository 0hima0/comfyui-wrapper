"""Validated, ordered reference images and their durable descriptions."""
from dataclasses import dataclass
import json

from PIL import Image, ImageOps

MAX_IMAGES = 4
MAX_TOTAL_PIXELS = 24_000_000
MAX_ROLE_LENGTH = 1000


@dataclass
class ReferenceImage:
    id: int
    filename: str
    role: str
    image: Image.Image

    def describe(self):
        return dict(id=self.id, label=f'画像{self.id}', filename=self.filename,
                    role=self.role, width=self.image.width, height=self.image.height)


def close_references(references):
    for reference in references:
        reference.image.close()


def load_references(uploads, raw_info=None):
    """Own all decoded images; close partial results on any validation failure."""
    if any(not item.filename for item in uploads):
        raise ValueError('画像を選択してください。')
    if len(uploads) > MAX_IMAGES:
        raise ValueError(f'参考画像は最大{MAX_IMAGES}枚です。')
    info = json.loads(raw_info) if raw_info is not None else [
        dict(id=index+1, role='') for index in range(len(uploads))]
    if not isinstance(info, list) or len(info) != len(uploads):
        raise ValueError('参考画像と使う要素の対応が不正です。')
    ids = set()
    for row in info:
        if not isinstance(row, dict) or type(row.get('id')) is not int or not 1 <= row['id'] <= 9999:
            raise ValueError('参考画像の番号が不正です。')
        if row['id'] in ids:
            raise ValueError('参考画像の番号が重複しています。')
        ids.add(row['id'])
        if not isinstance(row.get('role', ''), str) or len(row.get('role', '')) > MAX_ROLE_LENGTH:
            raise ValueError(f'使う要素は各画像{MAX_ROLE_LENGTH}文字以内で指定してください。')
    references, total_pixels = [], 0
    try:
        for upload, row in zip(uploads, info):
            with Image.open(upload.stream) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise ValueError('PNG・JPEG・WebPの画像を選択してください。')
                total_pixels += source.width * source.height
                if total_pixels > MAX_TOTAL_PIXELS:
                    raise ValueError('参考画像は合計2400万画素以内にしてください。')
                with ImageOps.exif_transpose(source) as oriented:
                    image = oriented.convert('RGBA')
            filename = upload.filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            references.append(ReferenceImage(row['id'], filename, row.get('role', '').strip(), image))
        return references
    except Exception:
        close_references(references)
        raise


def saved_references(settings):
    """Read current snapshots and older single-image history consistently."""
    if settings.get('input_images'):
        return settings['input_images']
    old = settings.get('input_image')
    return [dict(id=1, label='画像1', role='', **old)] if old else []
