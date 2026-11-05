<a id="multi-gpu"></a>
# 解析先の分散とGPU割り当て（Ubuntu）

[概要](../README.md) · [ドキュメント一覧](../README.md) · [基本セットアップ](BASIC_SETUP.md)

Ubuntu / NVIDIA / systemd向けの構成例です。先に [基本セットアップ](BASIC_SETUP.md) で1枚生成してください。

## 構成と前提

| プロセス | GPU | 待受例 |
|---|---|---|
| 既存Ollama | 0 | `127.0.0.1:11434` |
| 追加Ollama | 1 | `127.0.0.1:11435` |
| ComfyUI | 2 | `127.0.0.1:8188` |

- **分散対象：** 人物維持の共通場面1件＋人物N件の解析。最大4接続先、各同時1要求。
- **効果がない条件：** 参考画像なし・1枚・人物維持オフは解析1件。
- **必要な資源：** 各解析GPUにモデル分のVRAM。消費電力・メモリー使用量も増加。
- **対象外：** VRAMの合算、1枚の画像生成のGPU分割。短縮率は未測定。

コマンド実行前に `APP_DIR`（ComfyUI Wrapper）と `COMFYUI_DIR` の絶対パスをシェル変数へ設定します。既存サービスをバックアップし、同名設定があれば上書きせず `sudo vi` 等で統合してください。

仕様：[設定](CONFIGURATION.md)・[処理構成](SYSTEM_OVERVIEW.md)。外部資料：[Ollama GPU](https://docs.ollama.com/gpu)・[FAQ](https://docs.ollama.com/faq)・[ComfyUI起動引数](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/cli_args.py)。

<a id="gpu-step-1"></a>

## 1. 現在のGPU番号・Ollamaを確認

実行中の解析・生成を完了させてから設定してください。

```bash
nvidia-smi --query-gpu=index,name,memory.total --format=csv
command -v ollama
systemctl show ollama.service -p User -p ExecStart
```

GPU 0・1を解析、GPU 2を画像生成に割り当てます。Ollamaの既存サービス名は `ollama.service` とします。
Dockerや手動起動で運用している場合は、以下の環境変数と接続ポートの設定を、それぞれの起動方法に合わせて適用してください。

<a id="gpu-step-2"></a>

## 2. 既存のOllamaをGPU 0に固定

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/llmpc-gpu.conf >/dev/null <<'EOF'
[Service]
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
EOF
```

上のブロックは `llmpc-gpu.conf` を新規作成する場合の例です。

<a id="gpu-step-3"></a>

## 3. GPU 1用のOllamaを追加

- 既存のOllamaと同じユーザーで起動し、モデルの保存先を共有します。
- 既存サービスで `OLLAMA_MODELS` や `HOME` を独自に設定している場合は、同じ設定を下の新サービスにも追加してください。
- 保存先が異なると、GPU 1用のOllamaでダウンロード済みのモデルを認識できない場合があります。

```bash
OLLAMA_BIN="$(command -v ollama)"
OLLAMA_USER="$(systemctl show ollama.service -p User --value)"
if [ -z "$OLLAMA_USER" ]; then OLLAMA_USER=root; fi
test -n "$OLLAMA_BIN" || { echo "ollamaが見つかりません"; exit 1; }

sudo tee /etc/systemd/system/ollama-gpu1.service >/dev/null <<EOF
[Unit]
Description=Ollama analysis worker on GPU 1
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$OLLAMA_USER
ExecStart=$OLLAMA_BIN serve
Environment="CUDA_VISIBLE_DEVICES=1"
Environment="OLLAMA_HOST=127.0.0.1:11435"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl restart ollama.service
sudo systemctl enable --now ollama-gpu1.service
```

両方のOllamaで、使用する解析モデルが一覧に表示されることを確認します。

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama list
OLLAMA_HOST=127.0.0.1:11435 ollama list
```

両方に、アプリ設定の `model` で指定した同じ解析モデルが必要です（既定値は `qwen3-vl:8b-instruct`）。[解析モデルの変更](USER_GUIDE.md#analysis-model) も参照してください。
片方の一覧に表示されない場合は、実行ユーザーと `OLLAMA_MODELS` の設定を確認してください。

<a id="gpu-step-4"></a>

## 4. ComfyUIをGPU 2で起動

普段のComfyUIの起動コマンドに **--cuda-device 2** を追加します。
実行中のComfyUIを通常の手順で停止してから、同じPython環境で起動してください。

ComfyUIのPython環境を有効化してから実行する例：

```bash
cd "$COMFYUI_DIR"
python main.py --cuda-device 2 --listen 127.0.0.1 --port 8188
```

- systemdの場合は、実際のComfyUIサービスのExecStartへ引数を追加して再起動します。
- 既存のGPU指定やCUDA_VISIBLE_DEVICESがある場合は、GPU 2指定と矛盾しないように変更してください。
- `CUDA_VISIBLE_DEVICES` で使用するGPUを1台に限定すると、プロセス内ではそのGPUが `cuda:0` と表示されることがあります。
- 実際の割り当てはnvidia-smiのGPU番号・実行プロセスで確認してください。

<a id="gpu-step-5"></a>

## 5. ComfyUI Wrapperに解析先を登録

ComfyUI Wrapperを停止してから、次のコマンドを実行します。設定スクリプトは既存の `config.json` をバックアップしたうえで、2つの解析先とモデルの保持時間を設定します。

```bash
cd "$APP_DIR"
.venv/bin/python tools/user/configure_multi_gpu.py --config config.json
bash scripts/user/start-webui.sh
```

自動起動サービスを登録済みの場合は、上の手動起動の代わりに `sudo systemctl restart comfyui-wrapper` を実行してください。

設定される項目：

```json
{
  "ollama_urls": ["http://127.0.0.1:11434", "http://127.0.0.1:11435"],
  "ollama_keep_alive": "10m"
}
```

| 設定 | 意味 |
|---|---|
| `comfy_url` | GPU 2のComfyUI（例 `http://127.0.0.1:8188`） |
| `ollama_urls: []` | `ollama_url` の1接続先で順番に解析 |
| `ollama_keep_alive: "10m"` | 次の解析に備え10分保持。既定`0`は解析後に解放を要求 |

URL登録だけではGPUは切り替わりません。各サービスのGPU指定が必要です。

<a id="gpu-step-6"></a>

## 6. 動作確認

参考画像を2〜4枚追加し、人物維持モードをオンにして「画像を解析して生成」を実行します。
画面には「解析先1」「解析先2」と完了件数を表示します。

```bash
watch -n 1 nvidia-smi
```

- 解析中はGPU 0・1でOllamaが動作し、生成中はGPU 2でComfyUIが動作することを確認します。
- モデル保持中は処理終了後もGPU 0・1のVRAMが使用されます。
- 次のコマンドで、モデルの読み込み先がGPUかCPUかを確認できます。

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama ps
OLLAMA_HOST=127.0.0.1:11435 ollama ps
```

| 確認結果 | 判断・対処 |
|---|---|
| `PROCESSOR` にCPUを含む | VRAM不足の可能性。量子化・他プロセスの使用量を確認 |
| 時間を比較したい | 同じモデル・入力で比較。読み込み時間と推論時間を分ける |
| 実行記録を見たい | JSON／PNGの `analysis_execution` に解析先・タスク別時間を記録 |
| 停止・片方の失敗 | 他の解析にも停止要求。前処理・通信の終了待ちあり。失敗時は生成しない |

**OS再起動後も接続・GPU割り当て・実生成を確認**してください。サービス登録成功だけでは確認完了になりません。

<a id="gpu-step-7"></a>

## 解析先を1つに戻す

ComfyUI Wrapperの `config.json` で `ollama_urls` を空配列、`ollama_keep_alive` を `0` に戻し、Wrapperを再起動します。
GPU 1用のサービスも使わなくなる場合は、次のコマンドで停止し、自動起動を解除します。

```bash
sudo systemctl disable --now ollama-gpu1.service
```

GPU 0への固定やComfyUIのGPU 2指定を戻す場合は、今回追加した設定箇所を編集してください。

この手順は設定例です。VRAMの合算やComfyUI生成処理の分割は行いません。利用環境の性能・再起動後の永続性は実機で確認してください。
