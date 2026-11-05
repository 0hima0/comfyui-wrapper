# ComfyUI Wrapper

**ドキュメントはAIで生成しています。記述の誤りがある可能性があります。**

Ollamaで指示・参考画像を解析し、ComfyUIで画像を生成するローカルWebアプリです。Ubuntu上でのGit・Python venv・HTTP・systemdの基本操作を前提とします。

**導入：** [基本セットアップ](docs/BASIC_SETUP.md) → **使用：** [操作ガイド](docs/USER_GUIDE.md)

| 機能 | 対応範囲 |
|---|---|
| 生成 | 指示・参考画像から生成、Prompt・ワークフローのみの出力 |
| モデル | SD1.5 / SDXL系、Anima。LoRAは最大3個（Anima対象外） |
| 人物維持 | IP-Adapterと人物画像2〜4枚を使用 |
| 条件比較 | 最大2軸・20枚の連続生成と選別、保存画像2〜5枚の設定比較 |
| 結果管理 | 検索・お気に入り・メモ・設定復元・中断結果の取り込み |

Ollama・ComfyUIは別途稼働させます。Wrapperは同梱テンプレートからワークフローを構成します。独自のノード構成は、出力したワークフローをComfyUIで編集してください。

## ドキュメント

コマンドは指定がなければアプリルートで実行します。

| 資料 | 内容 |
|---|---|
| [導入と初回生成](docs/BASIC_SETUP.md) | 前提・疎通・公開状況・clone・設定・起動 |
| [操作ガイド](docs/USER_GUIDE.md) | 生成・選別・ギャラリー・設定再利用・LoRA管理 |
| [設定リファレンス](docs/CONFIGURATION.md) | 全設定・CLI・LoRA許可ルール |
| [運用・復旧](docs/MAINTENANCE.md) | systemd・Git更新・バックアップ・復元・旧版移行 |
| [FAQ](docs/FAQ.md) | Wrapper固有の制約と障害対応 |
| [追加セットアップ](docs/ADDITIONAL_SETUP.md) | LoRA・WD Tagger・IP-Adapter |
| [マルチGPU](docs/MULTI_GPU_UBUNTU.md) | 解析分散とGPU割り当て |
| [システム構成](docs/SYSTEM_OVERVIEW.md) | 処理・状態・API・用語 |

## 検証範囲

既存の動作確認記録：Ubuntu Server 24.04 LTS / Python 3.13 / Ollama v0.40.9 / ComfyUI v0.42.1。全モデルの互換性を保証するものではありません。自動テストと実GPU・systemd・更新復旧の確認は別です。

リポジトリURL・公開状況は [導入ガイド](docs/BASIC_SETUP.md#source) を参照してください。本資料はAIを用いて作成・更新しています。
