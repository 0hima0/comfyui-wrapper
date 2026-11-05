"""Application version format and increment rules."""
import re


def parse_version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Version must use MAJOR.MINOR.PATCH (for example 0.1.0).')
    return tuple(map(int, value.split('.')))


def bump_version(value, part):
    major, minor, patch = parse_version(value)
    if part == 'major':return f'{major+1}.0.0'
    if part == 'minor':return f'{major}.{minor+1}.0'
    if part == 'patch':return f'{major}.{minor}.{patch+1}'
    raise ValueError('Unknown version component.')