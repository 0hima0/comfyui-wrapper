"""Command-line analysis and workflow generation."""
import argparse
import secrets
from pathlib import Path
from comfyui_wrapper.app_metadata import BASE
from comfyui_wrapper.analysis.generate import analyze, write_json
from comfyui_wrapper.analysis.wd_tagger import wd_tags
from comfyui_wrapper.workflows.builders import patch_anima, animagine_workflow, load_anima_template

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--instruction', default='画像の見た目を参考にした画像を生成したい')
    parser.add_argument('--target', choices=['anima','animagine'], default='anima')
    parser.add_argument('--template', type=Path, default=BASE/'workflows/anima_template.json')
    parser.add_argument('--checkpoint', default='AnimagineXL_v31.safetensors')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    parser.add_argument('--model', default='qwen3-vl:8b-instruct')
    parser.add_argument('--tags-file', type=Path)
    parser.add_argument('--wd-dir', type=Path, help='model.onnx and selected_tags.csv directory')
    parser.add_argument('--threshold', type=float, default=0.35)
    parser.add_argument('--width', type=int, default=1024)
    parser.add_argument('--height', type=int, default=1024)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    if any(n < 256 or n > 2048 or n % 64 for n in (args.width,args.height)):
        parser.error('幅・高さは256〜2048の64の倍数で指定してください')
    if not 0 <= args.threshold <= 1:
        parser.error('thresholdは0〜1です')
    if args.seed is not None and not 0 <= args.seed <= 2**53-1:
        parser.error('seedは0〜2^53-1です')
    if args.out.exists():
        parser.error('出力先は未作成のディレクトリを指定してください（上書き防止）')
    from PIL import Image, ImageOps
    with Image.open(args.image, formats=("PNG", "JPEG", "WEBP")) as source:
        image = ImageOps.exif_transpose(source).convert('RGBA')
    tags = args.tags_file.read_text(encoding='utf-8-sig') if args.tags_file else ''
    wd_report = []
    if args.wd_dir:
        extracted, wd_report = wd_tags(image, args.wd_dir, args.threshold)
        tags = ', '.join(filter(None, [tags, extracted]))
    try:
        template = load_anima_template(args.template) if args.target == 'anima' else None
    except ValueError as error:
        parser.error(str(error))
    result = analyze(image,args.instruction,tags,args.ollama_url,args.model,args.target)
    seed = args.seed if args.seed is not None else secrets.randbelow(2**53)
    workflow = (patch_anima(template,result,args.width,args.height,seed) if args.target == 'anima'
                else animagine_workflow(result,args.width,args.height,seed,args.checkpoint))
    args.out.mkdir(parents=True, exist_ok=False)
    write_json(args.out/'workflow.json', workflow)
    write_json(args.out/'analysis.json', {'result':result,'wd_predictions':wd_report,
        'candidate_tags':tags,'instruction':args.instruction,'model':args.model,
        'target':args.target,'seed':seed,'width':args.width,'height':args.height})
    for key in ('positive','negative'):
        (args.out/(key+'.txt')).write_text(result[key],encoding='utf-8')
    print('保存しました:',args.out.resolve())


if __name__ == '__main__':
    main()
