"""WD Tagger inference."""
import csv
from pathlib import Path

def wd_tags(image, directory, threshold):
    import numpy as np
    import onnxruntime as ort
    from PIL import Image
    directory = Path(directory)
    session = ort.InferenceSession(str(directory / 'model.onnx'), providers=['CPUExecutionProvider'])
    spec = session.get_inputs()[0]
    size = spec.shape[1]
    if not isinstance(size, int) or spec.shape[-1] != 3:
        raise ValueError('WDモデルは固定解像度のNHWC入力が必要です')
    rgba = image.convert('RGBA')
    canvas = Image.new('RGBA', rgba.size, 'white')
    canvas.alpha_composite(rgba)
    side = max(canvas.size)
    square = Image.new('RGB', (side, side), 'white')
    square.paste(canvas.convert('RGB'), ((side - canvas.width)//2, (side - canvas.height)//2))
    square = square.resize((size, size), Image.Resampling.BICUBIC)
    array = np.asarray(square, dtype=np.float32)[None, :, :, ::-1].copy()
    scores = session.run(None, {spec.name: array})[0][0]
    with (directory / 'selected_tags.csv').open(encoding='utf-8-sig', newline='') as f:
        labels = list(csv.DictReader(f))
    if len(labels) != len(scores):
        raise ValueError('WDモデルとタグCSVの組み合わせが不一致です')
    # Character/rating predictions are retained in the report, not automatically prompted.
    result = [{'tag': row['name'], 'category': int(row['category']), 'score': float(score)}
              for row, score in zip(labels, scores)
              if int(row['category']) == 9 or score >= threshold]
    result.sort(key=lambda row: row['score'], reverse=True)
    tags = ', '.join(row['tag'] for row in result if row['category'] == 0)
    return tags, result


