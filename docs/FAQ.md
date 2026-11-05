# トラブル対処

[索引](../README.md) · [導入](BASIC_SETUP.md) · [運用](MAINTENANCE.md) · [復旧](MAINTENANCE.md#backup)

Wrapper固有の制約・復旧方法をまとめています。

<a id="config-edit"></a>
## 設定・モデルが反映されない

| 症状 | 対処 |
|---|---|
| 同じ保存先の起動済みエラー | 保存先単位で多重起動を禁止。既存ComfyUI Wrapperを停止し、ロックファイルの削除では回避しない |
| 保存した設定が変わらない | 再起動し、[CLI優先順位](CONFIGURATION.md#precedence) と使用ファイルを確認 |
| 保存先変更後に履歴がない | `output_dir` の変更では移動されない。[停止後に移設](MAINTENANCE.md#restore) |
| モデル・LoRAがない | ComfyUIの認識名・接続先・[LoRA許可フォルダー](CONFIGURATION.md#lora-folders) を確認 |
| 書き込みが403 | `X-Requested-With: LLMPC` と、Originがある場合の同一ホスト確認が必要。[アクセス制御](CONFIGURATION.md#network) |

## 生成・保存に失敗する

| 症状 | 対処 |
|---|---|
| 参考画像なしで失敗 | 指示または追加PositiveとOllamaが必要。WD・人物維持は使わない |
| 実行前チェック後に失敗 | チェック対象は接続・必要モデル・ノードの存在。モデル読み込み・VRAM余裕・推論成功までは検証しない |
| 人物・服装が混ざる | 画像を1枚1人にし、人物LoRAの適用先を確認。接触・ポーズの完全再現は保証されない |
| 停止・再起動後もComfyUIが動く | 「中断した生成の確認・復旧」→ 状態確認 → 完成画像の取り込み |
| 生成受付がタイムアウト | 実行状態を確認。同じタブでの再操作は同じ受付IDを使い、受付済みなら既存実行を返す。入力を変更しても前の実行が返る場合あり |
| ZIPだけ失敗 | 個別画像を確保し、容量・権限を確認 →「ZIPを再作成」 |
| マトリクスを受け付けない | 最大2軸・各2点以上・計20枚以下。Steps重複、WD・LoRAの前提も確認 |

## 画像・設定が見つからない

| 症状 | 対処・仕様 |
|---|---|
| 連続生成がギャラリーにない | レビューで選別を確定。未選択分は削除される |
| 複数画像が削除対象になる | 実行単位の削除。お気に入り1枚で実行全体を保護 |
| メモ付き画像が消えた | メモ・ラベルは保護にならない。[保持期限](USER_GUIDE.md#gallery) を確認 |
| 推奨値が反映されない | 「推奨値を適用」を押す。モデル・LoRAの名前変更も確認 |
| 復元後に参考画像がない | 条件復元は元画像の復元ではない。元ファイルを再選択 |
| LoRAのタグ・推奨Promptが生成に入らない | 参照・分類用。推奨Promptはコピーして利用 |

## 更新後の不具合

| 症状 | 対処 |
|---|---|
| 古い画面・サンプルAPIの404・`LoraSamples is not defined` | [配置診断](MAINTENANCE.md#verification) でコミット・版・配置先を確認 → 更新・再起動 → 再読み込み |
| Git更新がローカル変更・履歴分岐で停止 | 自動上書きはしない。変更を保管・整理し、追跡先へfast-forwardできる状態にする |
| ZIP版で `Release cannot replace this path: docs/images/...` | [別ディレクトリへcloneして移行](MAINTENANCE.md#migration) |
| 旧版からの更新後に `bad unit file setting` | 旧生成処理の `WorkingDirectory=` の引用符不備が原因なら、修正版配置後に [サービス再登録](MAINTENANCE.md#service) |

<a id="backup"></a>
## データ復元

設定・DB・画像の復元、更新のロールバックは [バックアップ・復旧](MAINTENANCE.md#backup) を参照してください。
