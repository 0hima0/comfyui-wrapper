# 追加セットアップ

[索引](../README.md) · [導入](BASIC_SETUP.md) · [設定](CONFIGURATION.md) · [操作仕様](USER_GUIDE.md)

基本の生成経路が動く環境へ、必要な機能だけ追加します。`ComfyUI/models/...` はComfyUI側のパスであり、ComfyUI Wrapperの `output_dir` ではありません。

モデル・LoRA・外部ノード・取得するワークフローはアプリのMITとは別条件です。[第三者ライセンス](../THIRD_PARTY_NOTICES.md) を確認してください。Animaを使う場合は [ワークフローを取得・配置](../workflows/README.md) します。JSONは同梱していません。

| 機能 | 追加依存 | 実行側 |
|---|---|---|
| LoRA | ベースモデルと互換性のあるLoRAファイル | ComfyUI |
| WD Tagger | WD EVA02-Large Tagger v3のONNX・タグ一覧 | ComfyUI WrapperのCPU |
| 人物維持 | IP-Adapterノード・対応モデル・CLIP Vision | 解析はOllama、画像生成はComfyUI |

<a id="lora"></a>
## LoRA

1. 配布元のベースモデル、ライセンス、トリガーワード、推奨強度を確認する。
2. ComfyUIの `models/loras/` 以下に配置し、ComfyUIの一覧へ認識させる。
3. ComfyUI Wrapperのアプリ設定で [モデル別許可フォルダー](CONFIGURATION.md#lora-folders) を登録する。未登録なら従来の系列判定を使用する。
4. 一覧を更新し、「LoRA管理」で登録情報・サンプル・推奨強度を保存する。

従来の系列判定を使う配置例:

```text
ComfyUI/models/loras/
  sd15/
  sdxl/
  illustrious/
```

最大3個を使用でき、MODEL / CLIP強度を別々に指定します。Animaは対象外です。フォルダーの許可はファイルの実互換性を保証しません。モデル別対応と系列対応の優先順位は [設定リファレンス](CONFIGURATION.md#lora-folders)、保存単位は [LoRA管理](USER_GUIDE.md#lora-management) を参照してください。

<a id="wd-tagger"></a>
## WD Tagger

[`SmilingWolf/wd-eva02-large-tagger-v3`](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/tree/main) の `model.onnx` と `selected_tags.csv` を同じディレクトリに置き、設定 `wd_dir` に指定してComfyUI Wrapperを再起動します。ComfyUIのカスタムノードは不要です。Python依存はComfyUI Wrapperの `requirements.txt` に含まれます。

```text
<wd_dir>/
  model.onnx
  selected_tags.csv
```

参考画像を追加しWDを有効にして実行前チェックを行います。しきい値の初期値は0.35で、低くすると採用タグが増えます。採用候補と利用者Promptが競合した場合はPromptを優先します。参考画像なしではWDを使わず、自動レーティングも行いません。

<a id="people"></a>
## 人物維持

SD1.5 / SDXL / Illustriousを対象に、1枚1人の参考画像を2〜4枚使用します。共通場面と人物別の外見・服装を解析し、参照順に左から右へ割り当てます。

### ComfyUI側の依存

| 種類 | 必要なもの | 配置先 |
|---|---|---|
| カスタムノード | `cubiq/ComfyUI_IPAdapter_plus` の `IPAdapterAdvanced`・`IPAdapterModelLoader` | `custom_nodes/` |
| CLIP Vision | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `models/clip_vision/` |
| SDXL / Illustrious | `ip-adapter-plus_sdxl_vit-h.safetensors` | `models/ipadapter/` |
| SD1.5 | `ip-adapter-plus_sd15.safetensors` | `models/ipadapter/` |
| 人物別LoRA使用時 | `CreateHookLora`・`SetClipHooks` | 対応するComfyUI標準ノード |

IP-Adapter Plusを使用し、FaceIDやViT-bigGを前提としません。共通CLIP Visionと使用系列に対応したIP-Adapterだけを用意します。

未導入の場合、ComfyUI-Manager等または次の手動操作で取得します。コマンドはComfyUIの `custom_nodes` ディレクトリで実行してください。

```bash
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
```

依存インストールは [拡張の導入案内](https://github.com/cubiq/ComfyUI_IPAdapter_plus#installation) に従い、ComfyUI側のPython環境で行います。`requirements.txt` がない版に対して存在しないファイルを指定しないでください。

モデルの取得元:

- [CLIP Vision](https://huggingface.co/h94/IP-Adapter/tree/main/models/image_encoder)：`model.safetensors` を表のCLIP Vision名に変更して配置。
- [SDXLモデル](https://huggingface.co/h94/IP-Adapter/tree/main/sdxl_models) / [SD1.5モデル](https://huggingface.co/h94/IP-Adapter/tree/main/models)：表と同じ名前のモデルを配置。

### 有効化と確認

ComfyUIを再起動し、ComfyUI Wrapperで参考画像と「人物・服装を維持して組み合わせる」を選択して実行前チェックを行います。人物用LoRAは対応する画像、画風用LoRAは「全体」へ割り当てます。

背景・服だけの参考画像は人物維持をオフにして使用します。人物同士の接触・領域をまたぐ構図では特徴が混ざる場合があり、完全な外見保持を保証しません。通常生成より解析回数とVRAM使用量が増えます。モデル・ノードの検出だけでなく実生成を確認してください。
