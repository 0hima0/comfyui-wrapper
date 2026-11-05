"""Update the single application version source. Does not commit or tag Git."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'internal'))
import _bootstrap
from comfyui_wrapper.versioning import parse_version, bump_version

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--part',choices=('major','minor','patch'))
    group.add_argument('--set',dest='value')
    args=parser.parse_args()
    path=ROOT/'VERSION'
    old=path.read_text(encoding='utf-8').strip()
    new=args.value if args.value is not None else bump_version(old,args.part)
    if parse_version(new)<=parse_version(old):
        parser.error('The new version must be greater than the current version.')
    path.write_text(new+'\n',encoding='utf-8')
    print(old+' -> '+new)


if __name__=='__main__':main()