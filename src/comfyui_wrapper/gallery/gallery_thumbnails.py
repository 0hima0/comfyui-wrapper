"""Small, reusable JPEG previews. Original PNGs and embedded metadata stay untouched."""
import hashlib
import tempfile
import threading
from pathlib import Path
from PIL import Image, ImageOps

SIZE=480
VERSION='jpeg-480-q78-v1'


def source_version(source):
    stat=source.stat()
    return f'{stat.st_mtime_ns:x}-{stat.st_size:x}-{VERSION}'


class ThumbnailCache:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.locks=[threading.Lock() for _ in range(16)]
        self.workers=threading.BoundedSemaphore(2)

    def path_for(self,source):
        source=Path(source)
        key=hashlib.sha256((str(source.resolve())+'/'+source_version(source)).encode()).hexdigest()
        return self.directory/(key+'.jpg')

    def get(self,source):
        source=Path(source)
        target=self.path_for(source);key=target.stem
        if target.is_file():return target
        with self.locks[int(key[:2],16)%len(self.locks)]:
            if target.is_file():return target
            with self.workers:
                self.directory.mkdir(parents=True,exist_ok=True)
                with Image.open(source) as original:
                    preview=ImageOps.exif_transpose(original)
                    try:
                        preview.thumbnail((SIZE,SIZE),Image.Resampling.LANCZOS,reducing_gap=3)
                        rgb=Image.new('RGB',preview.size,'white')
                        try:
                            if 'A' in preview.getbands():
                                rgba=preview.convert('RGBA')
                                try:
                                    with rgba.getchannel('A') as mask:rgb.paste(rgba,mask=mask)
                                finally:rgba.close()
                            else:
                                with preview.convert('RGB') as converted:rgb.paste(converted)
                            with tempfile.NamedTemporaryFile(dir=self.directory,suffix='.tmp',delete=False) as temp:
                                pending=Path(temp.name)
                            try:
                                rgb.save(pending,format='JPEG',quality=78,optimize=True,progressive=True)
                                pending.replace(target)
                            finally:pending.unlink(missing_ok=True)
                        finally:rgb.close()
                    finally:preview.close()
        return target
