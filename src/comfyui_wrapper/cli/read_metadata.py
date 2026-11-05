"""Display the LLM-PC metadata saved in a generated PNG."""
import argparse
import json
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    args=parser.parse_args()
    with Image.open(args.image) as image:
        image.load()
        text=getattr(image,'text',{})
        if 'llmpc' not in text:
            parser.exit(1,'LLM-PCメタデータがありません。更新後に生成してWebUIから保存したPNGを指定してください。\n')
        print(json.dumps(json.loads(text['llmpc']),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
