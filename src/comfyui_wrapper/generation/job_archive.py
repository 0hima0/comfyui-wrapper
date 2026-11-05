"""Build and verify an archive before publishing it in the output directory."""
import os
import tempfile
import zipfile
from pathlib import Path


def available(directory):
    path = directory / 'results.zip'
    return not directory.is_symlink() and not path.is_symlink() and path.is_file() and zipfile.is_zipfile(path)


def build(directory):
    if directory.is_symlink():
        raise OSError('Invalid artifact directory')
    descriptor, temporary = tempfile.mkstemp(prefix='.results.', suffix='.part', dir=directory)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.iterdir()):
                if path.name != 'results.zip' and not path.name.endswith('.part') and not path.is_symlink() and path.is_file():
                    archive.write(path, path.name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise zipfile.BadZipFile('Archive verification failed')
        os.replace(temporary, directory / 'results.zip')
    finally:
        Path(temporary).unlink(missing_ok=True)


def create(directory, logger):
    try:
        build(directory)
        return dict(zip_ready=True, zip_error='')
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
        logger.exception('ZIP creation failed')
        return dict(zip_ready=available(directory),
                    zip_error='ZIPの作成に失敗しました。個別の成果物は保存されています。「ZIPを再作成」を試してください。')
