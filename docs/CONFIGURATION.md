# 設定リファレンス

[索引](../README.md) · [導入](BASIC_SETUP.md) · [システム構成](SYSTEM_OVERVIEW.md)

設定例：[`config/config.example.json`](../config/config.example.json)。Ollama・ComfyUI自身の設定は別管理です。

<a id="precedence"></a>
## 読み込みと優先順位

**CLI引数 > 設定ファイル > 既定値**。変更後はComfyUI Wrapperを再起動します。

| 項目 | ルール |
|---|---|
| 標準ファイル | アプリルートの `config.json`。なければ既定値 |
| 別ファイル | `--config` で指定。存在しなければ起動エラー |
| 形式 | JSONオブジェクト。未知のキーは拒否、省略キーは既定値 |
| 相対パス | ファイル内の `output_dir` / `wd_dir` は設定ファイル基準。CLIは作業ディレクトリ基準。`~`を展開 |
| 画面から保存 | 差分確認・バックアップ・競合検出あり。生成中は不可 |
| 保存先の変更 | 既存データは移動しない。[停止後に移設](MAINTENANCE.md#restore) |

## キー一覧

表の既定値はキー省略時の値です。`lora_folders` は配布設定例に標準フォルダーの対応が記載されており、省略時の `{}` とは異なります。

| キー | 型・既定値 | 意味 |
|---|---|---|
| `host` | 文字列、`127.0.0.1` | ComfyUI Wrapperの待受アドレス |
| `trusted_hosts` | 配列、`["localhost","127.0.0.1","[::1]"]` | ブラウザーから接続するホスト名・IPの完全一致リスト。最大32件、URL・ポート・ワイルドカード不可。再起動後に反映 |
| `port` | 整数、`7860` | ComfyUI Wrapperの待受ポート。1〜65535 |
| `ollama_url` | 文字列、`http://127.0.0.1:11434` | 単一解析先。`ollama_urls` が空の場合に使用 |
| `comfy_url` | 文字列、`http://127.0.0.1:8188` | 生成・モデル列挙・画像取得に使うComfyUI |
| `model` | 文字列、`qwen3-vl:8b-instruct` | Ollama解析モデルの正確な名前・タグ。最大300文字 |
| `wd_dir` | 文字列または `null`、`null` | `model.onnx` と `selected_tags.csv` を含むWDモデルディレクトリ |
| `output_dir` | 文字列、`web-results` | SQLite・成果物・LoRAサンプルの保存ルート |
| `gallery_retention_days` | 整数、`10` | 通常ギャラリーの自動削除までの日数。0〜36500、`0` は自動削除を無効化 |
| `ollama_urls` | 文字列配列、`[]` | 解析先を最大4件指定。重複不可。非空ならこのリストを使用 |
| `ollama_keep_alive` | 整数または期間文字列、`0` | Ollamaへ要求するモデル保持時間。`0` は解放、`-1` は保持、`10m` 等も指定可能 |
| `checkpoint_families` | オブジェクト、`{}` | チェックポイント名 → `sd15` / `sdxl` / `illustrious` の明示対応 |
| `lora_folders` | オブジェクト、`{}` | LoRAの相対フォルダーパス → モデル系列の対応。モデル別対応がない場合に使用 |
| `checkpoint_lora_folders` | オブジェクト、`{}` | チェックポイント名 → 許可するLoRA相対フォルダーの配列 |

`ollama_keep_alive` の整数は `-1` 以上、期間文字列は `0`、`-1`、正整数と `s` / `m` / `h` の組み合わせです。実際のモデル配置・メモリ保持はOllama側の状態に依存します。

### ギャラリーの保持期間

設定の抜粋です。既存の他項目を残して追加・変更し、ComfyUI Wrapperを再起動します。

```json
{
  "gallery_retention_days": 30
}
```

| 値・操作 | 結果 |
|---|---|
| 省略 / `10` | 終了から10日で対象実行を削除 |
| `30` | 30日に変更 |
| `0` | 自動削除を無効化 |
| 入力範囲 | 整数0〜36500。アプリ設定でも変更可能。CLI指定なし |
| 確認時期 | 起動時と1時間ごと。短縮すると再起動直後から適用 |

対象・お気に入り等の保護条件は [保持仕様](USER_GUIDE.md#gallery) を参照してください。

## CLI

`bash scripts/user/start-webui.sh` は引数を `tools/user/webui.py` へそのまま渡します。

| CLI引数 | 設定キー |
|---|---|
| `--config` | 設定ファイルの選択 |
| `--host`, `--port` | `host`, `port` |
| `--ollama-url`, `--comfy-url` | `ollama_url`, `comfy_url` |
| `--model` | `model` |
| `--wd-dir`, `--output-dir` | `wd_dir`, `output_dir` |
| `--ollama-urls URL [URL ...]` | `ollama_urls` |
| `--ollama-keep-alive` | `ollama_keep_alive` |

系列・フォルダー対応は設定ファイルまたはアプリ設定画面で指定します。

```bash
bash scripts/user/start-webui.sh --config config.json --port 7861
```

上の例では待受ポートだけがCLI値になります。画面で `port` を保存しても、この引数が残る限り起動時は7861が優先されます。更新プログラムは保存済み設定から再起動するため、運用値はファイルへ集約してください。

<a id="models"></a>
## 解析モデルと生成モデル

| モデル | 選択場所・注意 |
|---|---|
| 解析モデル | 設定の `model`。Ollamaの名前・タグを指定。履歴復元では変更しない |
| 生成モデル | 画面でComfyUIの候補から選択 |
| 別の解析モデルを導入 | 画像入力・JSON応答を検証。複数解析先には同じ名前で用意 |

<a id="lora-folders"></a>
## モデル系列とLoRAの許可ルール

次は設定の一部だけを示した例です。

```json
{
  "checkpoint_families": {
    "custom-model.safetensors": "sdxl"
  },
  "lora_folders": {
    "legacy/styles": "sdxl"
  },
  "checkpoint_lora_folders": {
    "custom-model.safetensors": ["characters", "shared/styles"],
    "without-lora.safetensors": []
  }
}
```

| 指定 | 挙動 |
|---|---|
| モデル名に対応配列がある | 指定フォルダーとその配下だけを許可。系列判定より優先 |
| 配列に `.` がある | `models/loras/` 直下だけを許可 |
| 配列が空 `[]` | そのモデルのLoRAを禁止 |
| モデル名のキーがない | 従来のモデル系列・LoRA系列の一致判定を使用 |
| Anima | 上記対応に関係なくLoRAは対象外 |

- モデル名：ComfyUIの相対パス込みの名前。最大1000モデル。
- LoRAフォルダー：`models/loras/` 基準、各モデル最大100件。絶対パス・`..` は不可。
- 大小文字を区別せず照合。`characters` はその配下を含み、`characters2` は含まない。
- 系列未指定時は既知の名前から判定し、不明なら未判定。
- フォルダー対応は実互換性の保証ではありません。変更により履歴・プリセットのLoRAが解除・拒否される場合があります。

<a id="network"></a>
## ネットワークとアクセス制御

| 項目 | 設定・制約 |
|---|---|
| LAN待受 | `host: "0.0.0.0"` に加え、`trusted_hosts` に接続するサーバーのホスト名・IPを追加。待受だけではLAN利用不可 |
| 上流接続 | `ollama_url` / `comfy_url` はComfyUI Wrapperから接続するURL |
| 認証 | ユーザー認証・ユーザー別データ分離なし。接続できる人は生成・設定変更・削除が可能 |
| 書き込みガード | `X-Requested-With: LLMPC`、Originがある場合はscheme・ホスト・ポートを確認。認証の代わりではない |
| 外部公開 | 前段に認証・TLS・アクセス制御が必要 |
| プロキシ | Host / Originを整合させ、Wrapperへの直接接続をFW等で禁止。400/403回避のためガードを無効化しない |

接続は信頼できる利用者に制限してください。画面で編集する接続URLには認証情報・クエリ・フラグメントを含めません。

複数端末で共有する場合は、認証・TLSを備えたリバースプロキシを前段に置きます。Wrapperはループバック待受を維持し、プロキシは上流のHostを `127.0.0.1:7860`、Originを `http://127.0.0.1:7860` に揃えてください。Originを書き換える場合は、前段で外部Originが公開URLと一致することを検証してから転送します。転送ヘッダーを無条件に信頼する設定は追加しません。

確認時は、未認証のAPI・画像要求が拒否されること、バックエンドへ直接接続できないこと、認証後の生成・設定変更が動作することを確認してください。未知のHostで400になるのは正常です。単一利用ならSSHトンネルで `localhost:7860` へ接続する方法も使えます。

