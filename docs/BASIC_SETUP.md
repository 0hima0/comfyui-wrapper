# 導入と初回生成

[索引](../README.md) · [詳細設定](CONFIGURATION.md) · [操作](USER_GUIDE.md) · [障害対応](FAQ.md)

<a id="prerequisites"></a>
## 前提

| 項目 | 要件 |
|---|---|
| 実行環境 | Ubuntu・Bash、Git、Python 3.10以降（venv利用可） |
| Ollama | 稼働済み。解析モデル `qwen3-vl:8b-instruct` を導入済み |
| ComfyUI | 稼働済み。対応する生成モデルで単体生成できること |
| リソース | Ollama・ComfyUIの併用に必要なGPU / RAM、書き込み可能な出力先 |

外部サービスの導入は [Ollama](https://docs.ollama.com/quickstart)・[ComfyUI](https://docs.comfy.org/ja/installation/manual_install) の公式案内を使用します。WrapperのvenvはComfyUIと分離します。解析モデルを変える場合は画像入力・JSON応答に対応するものを指定してください。

各種アプリがインストールされているホストのAPIを確認します。URLは実環境へ置き換え、解析モデル・生成モデル・サンプラーが応答に含まれることを確認してください。

```bash
curl -fsS http://127.0.0.1:11434/api/tags
curl -fsS http://127.0.0.1:8188/object_info/CheckpointLoaderSimple
curl -fsS http://127.0.0.1:8188/object_info/KSampler
```

<a id="first-install"></a>
<a id="terminal"></a>
<a id="venv"></a>
<a id="source"></a>
## 1. 取得・依存導入

**GitHubのリポジトリURL・公開日は未確定です。** 下記 `OWNER/REPOSITORY` は例示のため、案内されたURLに置き換えてください。配置する親ディレクトリで実行し、ComfyUIとは異なるディレクトリに配置します。

```bash
REPOSITORY_URL='https://github.com/0hima0/comfyui-wrapper.git'
git clone "$REPOSITORY_URL" comfyui-wrapper
cd comfyui-wrapper
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

以降はアプリルートで実行します。各コマンドの正常終了を確認してください。更新は現在のブランチのorigin追跡先から行います。

<a id="config"></a>
<a id="connection"></a>
## 2. 設定

```bash
cp -n config/config.example.json config.json
vi config.json
```

| 確認するキー | 設定例の値・用途 |
|---|---|
| `ollama_url` / `comfy_url` | `http://127.0.0.1:11434` / `http://127.0.0.1:8188` |
| `model` | Ollama解析モデル名。生成チェックポイントとは別 |
| `host` / `port` | Wrapperの待受。`127.0.0.1` / `7860` |
| `trusted_hosts` | 接続を許可するホスト名・IP。既定はlocalhost・ループバックのみ。LAN共有は[アクセス制御](CONFIGURATION.md#network)も設定 |
| `output_dir` | 履歴・画像の保存先。既定 `web-results` |
| `gallery_retention_days` | 通常画像の保持日数。既定10日、`0`で自動削除無効 |

`config.json`・`.venv/`・出力先・`update-backups/` はGit対象外です。独自の設定名・出力先も追跡ファイルと分離します。設定内の相対パスは設定ファイルの配置先基準です。**設定変更後はComfyUI Wrapperの再起動が必要です。** ローカルネットワークで別PCから使う場合は [待受・アクセス制御](CONFIGURATION.md#network) を確認してください。

<a id="start"></a>
## 3. 起動

```bash
bash scripts/user/start-webui.sh
```

別端末で `curl -fsS http://127.0.0.1:7860/api/version` を実行し、`release`・`app_directory` が想定どおりか確認します。ブラウザーで `http://127.0.0.1:7860` を開きます。

<a id="first-image"></a>
## 4. 初回生成

Animaを使う場合だけ、先に [ワークフローを取得・配置](../workflows/README.md) します。SD1.5 / SDXL系では不要です。

1. 「画像生成」で動作確認済みの生成モデルを選択する。
2. 指示を入力し、参考画像・LoRA・連続生成なしで「システム管理 → 実行前チェック」を行う。「Prompt・ワークフローのみ作成」はオフにする。
3. 「指示から生成」を実行し、結果画像・PNG / JSONのダウンロード・ギャラリーへの保存を確認する。

実行前チェックは接続・必要モデル・ノードの確認です。推論成功は実生成で確認します。失敗時は [FAQ](FAQ.md)、追加機能は [追加セットアップ](ADDITIONAL_SETUP.md) を参照してください。

<a id="stop"></a>
## 停止・次回起動

手動停止は処理完了後に起動端末でCtrl+C。次回はOllama・ComfyUIを稼働させて起動スクリプトを実行します。ブラウザーを閉じてもサーバーは停止しません。

<a id="first-update"></a>
自動起動・更新は [運用](MAINTENANCE.md)、既存ZIP版からは [移行手順](MAINTENANCE.md#migration) を使用します。
