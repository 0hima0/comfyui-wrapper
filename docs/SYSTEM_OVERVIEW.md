# システム構成

[索引](../README.md) · [設定](CONFIGURATION.md) · [操作ガイド](USER_GUIDE.md)

構成・障害対応を確認するための技術資料です。日常操作には [操作ガイド](USER_GUIDE.md) を使用してください。

## 構成と処理の流れ

```text
ブラウザー → Wrapper :7860 → Ollama :11434（指示・画像の解析）
                         → ComfyUI :8188（画像生成）
                         → output_dir（履歴・画像・設定）
```

| 担当 | 役割 |
|---|---|
| ブラウザー | 入力・結果・進捗表示、一時状態保持 |
| ComfyUI Wrapper（Flask / Waitress） | 入力検証、Prompt統合、ワークフロー作成、実行追跡、SQLite・成果物保存 |
| Ollama | 指示・参考画像を構造化して解析 |
| ComfyUI | モデル列挙、ワークフロー実行、画像出力 |
| WD Tagger（任意） | WrapperのCPUで参考画像・生成画像のタグ抽出 |

1. 受付・ジョブID返却後、バックグラウンドで解析。
2. UI入力を優先してPromptを統合し、解析JSON・ワークフローを保存。
3. ComfyUIへ投入して `prompt_id` を記録、進捗を追跡。
4. 画像取得・PNG情報埋め込み・検証済みZIP公開・終了状態保存。

| 方式 | 処理の違い |
|---|---|
| Promptのみ | ComfyUIへの生成投入を省略 |
| 解析再利用 | 保存結果と入力が適合する場合だけ解析を省略 |
| 人物維持 | 共通場面・各人物を分けて解析し、領域・IP-Adapterを構成 |
| 複数解析先 | `ollama_urls` に分配、1接続先につき同時1要求。生成先は1つのComfyUI |

## 実行・停止・復旧

| 状況 | 挙動 |
|---|---|
| 通常ジョブ | `running` → `done` / `error` / `cancelled` |
| 生成セット | `running` → `review` / `error` / `cancelled`。選別して確定 |
| 同時実行 | 通常生成か連続生成の1件。追加受付は409 |
| 同じ保存先の多重起動 | 標準起動ではOSファイルロックで拒否。複数Webワーカーでの共有は非対応 |
| ブラウザーを閉じる | サーバー処理は継続 |
| Wrapper再起動 | 実行中ジョブを中断エラー化。自動再投入せず、保存IDで手動照合・取り込み |
| LoRA取得失敗 | 選択・未保存入力を保持。上流障害と正常な空一覧を区別 |
| 画像の途中取得失敗 | 保存済み成果物が残る場合あり。エラーだけで消失と判断しない |
| ZIP失敗 | 個別成果物と既存の完成ZIPを保持。ZIPのみ再作成可能 |
| 中断画像の回収 | 実行ID・グラフを照合し、未取得画像だけ保存。生成を再投入しない |

ZIPは一時ファイルをCRC検証して置換します。再作成・取り込みと削除の競合を防止します。

### 通信期限と受付ID

| 通信 | 待機期限 |
|---|---|
| ブラウザーの共通JSON取得 | 15秒 |
| 通常の書き込み | 30秒 |
| 生成受付・結果取り込み | 120秒 |
| ComfyUIの生成追跡 | 1800秒 |

- 通信中断はサーバー処理の取り消しではありません。停止も通信・前処理終了を待つ場合があります。
- 書き込みを自動再送しません。状態・一覧を確認して再操作します。
- 生成受付IDを同じタブで保持し、応答喪失後の再操作には同じIDを使用。受付済みなら既存ジョブ／セットを返します。
- 入力を変更していても前の受付が成立済みなら前の実行を返します。照合できる期間は元の履歴・セットの保持期間です。

## WebUIが使う主なAPI

書き込みには [アクセス制御](CONFIGURATION.md#network) が適用されます。

| メソッド・パス | 用途 |
|---|---|
| `GET /api/version` | 版・配置先・PID・対応機能 |
| `GET /api/generation-state` | 実行中ジョブ・セット |
| `GET /api/jobs/<job_id>` | 状態・結果・実在するダウンロードURL |
| `POST /api/jobs/<job_id>/cancel` | 停止要求。受理と停止完了は別 |
| `POST /api/jobs/<job_id>/archive` | 完了済み通常実行のZIP再作成。`zip_error`・`downloads`を確認 |
| `POST /api/jobs/<job_id>/reconcile` | 状態照合。JSON `import_images: true` で取り込み |
| `GET /api/history?recoverable=1` | 通常・連続生成の回収可能な中断実行、直近20件 |
| `GET /api/generation-options` | LoRA等の候補。`loras_available=false`は取得失敗 |

LoRA登録API `/api/lora-triggers`：

| クエリ | 応答 |
|---|---|
| `?summary=1` | 名前・タグの軽量一覧 |
| `?name=<相対名>` | 選択したLoRAの詳細 |
| なし | 全登録情報（従来互換） |

詳細キャッシュは最大4件。古い応答で新しい入力を上書きしません。ComfyUIから消えたLoRAも登録情報は残します。

## 保存と保持

- ComfyUI Wrapperの保存先とComfyUIのoutputは別管理。ギャラリー削除はComfyUI出力・ダウンロード済みコピーに影響しません。
- 既定10日で対象実行を自動削除。設定・保護条件は [保持期限](USER_GUIDE.md#gallery) を参照。
- PNG内の情報だけでは全体を復元できません。[保存データ](USER_GUIDE.md#saved-data) と [バックアップ](MAINTENANCE.md#backup) を確認してください。

<a id="terms"></a>
## 用語・識別子

| 用語 | 意味 |
|---|---|
| 解析モデル / 生成モデル | OllamaでPromptを構成するモデル / ComfyUIで画像を生成するチェックポイント |
| モデル系列 / プロファイル | ワークフロー・LoRA候補の分類 / Steps・CFG等の既定値。ユーザー推奨設定とは別 |
| 実行（ジョブ）/ 生成セット（バッチ） | 1回の生成処理 / 連続生成のまとまり。通常ギャラリーは実行単位で削除 |
| `job_id` / `prompt_id` | Wrapperの実行ID / ComfyUIの投入ID |
| 追加Prompt / 最終Prompt | 利用者の入力 / 解析・LoRAトリガー等を統合した出力 |
| トリガー / 推奨プロンプト / 管理用タグ | 生成へ反映する語句 / コピー利用する参照文 / LoRA分類。保存・適用は独立 |
| DB版 / アプリ版 | SQLiteの `user_version` / `VERSION`。別の数値体系 |
| WAL | SQLiteの付随ジャーナル。復元DBと現在のWALを混在させない |

設定プリセット・推奨値・画像注釈の保存単位は [操作ガイド](USER_GUIDE.md)、DBとファイルの保全は [運用](MAINTENANCE.md#backup) を参照してください。
