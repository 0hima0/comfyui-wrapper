# 利用者が取得するワークフロー

ワークフローJSON・モデル重みはリポジトリに含めません。通常のSD1.5 / SDXL系はアプリがワークフローを構成するため、この準備は不要です。

## Anima

1. [Anima配布元](https://huggingface.co/circlestone-labs/Anima) の利用条件を確認し、モデルカードで案内されるワークフロー入り `example.png` を取得する。
2. ComfyUIへ画像を読み込み、使用するモデルを配置して単体生成を確認する。
3. **UI形式のJSON**としてエクスポートし、アプリルートの `workflows/anima_template.json` に配置する。API形式JSONは使用しない。
4. WrapperでAnimaモデルを選び、「システム管理 → 実行前チェック」を行う。

CLI生成では `--template /path/to/workflow.json` で別の配置先も指定できます。自動ダウンロードは行いません。JSON・モデル・ライセンス等は利用者が管理・バックアップしてください。

## 対応する形式

JSONのルートに `nodes` と `links` が必要です。現在のAnima対応は次のノードIDを前提とします。

| ID | 種類 | 更新する値 |
|---|---|---|
| 11 / 12 | `CLIPTextEncode` | Positive / Negative |
| 19 | `KSampler` | Seed・生成パラメーター |
| 28 | `EmptyLatentImage` | 幅・高さ・batch_size |
| 44 | `UNETLoader` | 生成モデル名（WebUIで指定） |

CLIP・VAE等は取得したワークフローの値を使います。通常のエクスポートにある `widgets_values` から入力名を補うため、`widgets_values_named` の追加編集は不要です。

配布元の改版・追加ノード・サブグラフ等で構成が変わると、そのままでは対応しません。上表の形式に対応するワークフローを用意してください。未配置・不正なJSONは実行前チェックと生成時に案内を表示します。任意ワークフローを実行する汎用UIではありません。

## ライセンスと更新

アプリのMITは、取得するJSON・モデルへの許諾ではありません。現在のAnima配布元は非商用ライセンス等を案内しています。取得版のLICENSE・モデルカード・別許諾を確認してください。[第三者ライセンス](../THIRD_PARTY_NOTICES.md)

`workflows/README.md` 以外はGitとDockerビルドの対象外です。旧版の同梱JSONを使っていた場合は、更新前に手元へバックアップし、更新後に利用者管理ファイルとして再配置してください。
