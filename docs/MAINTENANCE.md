# 運用・更新・復旧

[索引](../README.md) · [設定](CONFIGURATION.md) · [バックアップ](#backup) · [復旧](#update-rollback) · [旧版移行](#migration)

アプリルートから実行します。

<a id="service"></a>
## 自動起動・ログ

手動生成を確認後、通常の実行ユーザーで登録します。スクリプト全体をsudoで実行しないでください。

```bash
bash scripts/user/install-autostart.sh
sudo systemctl status comfyui-wrapper --no-pager -l
sudo journalctl -u comfyui-wrapper -b -n 100 --no-pager
```

| 操作 | コマンド |
|---|---|
| 再起動 | `sudo systemctl restart comfyui-wrapper` |
| 停止 | `sudo systemctl stop comfyui-wrapper` |
| 自動起動解除・停止 | `sudo systemctl disable --now comfyui-wrapper` |

サービスは `.venv/bin/python tools/user/webui.py --config config.json` を実行します。Ollama・ComfyUIの自動起動は別途設定します。登録後はOS再起動を挟み、稼働・生成を確認してください。

<a id="update"></a>
## 更新

生成を完了させ、追跡ファイルにローカル変更がない状態で実行します。ComfyUI Wrapperは起動したままで構いません。

```bash
bash scripts/user/update.sh
```

別設定・ポートを使う場合：

```bash
bash scripts/user/update.sh --config config.json --url http://127.0.0.1:7861
```

`--url` のポートは保存設定と一致させます。運用値は設定ファイルへ保存してください。再起動時にCLIの一時上書きは引き継ぎません。

| 処理 | 内容 |
|---|---|
| 取得 | 現在のブランチのorigin追跡先をfetch。fast-forwardのみ |
| 保全 | 生成状態を確認して停止。設定・出力先・更新前後のコミットを `update-backups/` へ保存 |
| 反映 | Git更新、依存導入、`pip check`、再起動、HTTP確認 |
| 失敗時 | 更新前コミット・データへの復元と旧版再起動を試行。依存パッケージの完全復元は保証しない |

- ローカル変更・履歴分岐・未追跡ファイルの衝突は上書きせず停止します。通常のcloneを使用し、detached HEAD・疎なチェックアウト・assume-unchanged・サブモジュール・シンボリックリンクは避けてください。
- Git・依存導入先への接続と、出力先全体をコピーできる空き容量が必要です。
- 更新がなければ停止せず終了。Ollama・ComfyUI・モデルは更新しません。
- 稼働中の `git pull` だけでは停止・バックアップ・依存更新を行わないため、付属スクリプトを使用します。

<a id="verification"></a>
## 更新・配置の確認

```bash
git rev-parse HEAD
.venv/bin/python tools/user/check_installation.py --url http://127.0.0.1:7860
```

コミット・ローカル変更・稼働版・配置先を確認します。診断はfetchしません。同じVERSIONでもコミットが変わるため、更新後の再起動が必要です。

ギャラリー・LoRA登録・プリセットを確認し、1枚生成してPNG / JSONを保存します。不具合時は [更新ロールバック](MAINTENANCE.md#update-rollback) を参照してください。

<a id="backup"></a>
## バックアップ・保持

| 対象 | 保管するもの |
|---|---|
| アプリ設定 | 実際に使用する設定ファイル |
| 永続データ | `output_dir` 全体。SQLite・画像・JSON・LoRAサンプル・DB付随ファイル |
| プログラム | `VERSION` とコミットID。Git履歴も別媒体へ保管 |
| 外部依存 | ComfyUIのモデル・LoRA・追加ノード、Ollamaモデルは別管理 |

1. 生成を完了してComfyUI Wrapperを停止する。
2. 設定と出力先全体を、アプリ・出力先の外の日時付きディレクトリへコピーする。
3. コピー結果・版・コミットを確認し、再起動する。

稼働中DBだけを通常コピーしません。停止後に残る `-wal` / `-shm` も一式で保管します。ブラウザーの一時入力・参考画像は対象外です。

通常画像は既定10日で自動削除します。[対象・お気に入り保護](USER_GUIDE.md#gallery) を確認してください。DB移行・更新バックアップは別管理で、容量監視が必要です。

<a id="restore"></a>
## データの復元・保存先移設

1. ComfyUI Wrapperを停止し、現在の設定・データを別途退避する。
2. バックアップの出力先をディレクトリ単位で復元する。現在のDB・WALとの混在や差分コピーは避ける。
3. 対応する設定を戻し、`output_dir`・権限を確認する。設定変更だけではデータは移動しない。
4. 同じ時点のプログラム・依存で起動し、画像・LoRA登録・サンプル・プリセットを確認する。別ホストへの移設はvenvを作り直す。

バックアップ後の追加・編集は復元結果に含まれません。

<a id="update-rollback"></a>
## 更新のロールバック

自動復元の成否とログを確認してから手動復旧します。`update-backups/<timestamp-id>/` の内容：

| 保存物 | 内容 |
|---|---|
| `restore.json` | `git_before`（更新前）・`git_after`（更新先）、設定パス・出力先 |
| `config.json` / `data/` | 設定 / 出力先全体のコピー |
| `program/` | 変更対象だった旧ファイルの補助退避。アプリ全体ではない |
| `startup.log` / `failed-data/` | 再起動ログ / 失敗した更新後データ（作成された場合） |

1. Wrapperを停止して現状を退避し、`git status --short` の変更を保管・解消する。
2. `git reset --keep <git_beforeのコミットID>` で戻す。失敗時は強制せず原因を確認する。
3. 同じバックアップの設定・`data/` 全体を復元する。
4. 旧版の依存をvenvへ導入し、起動・データ・生成を確認する。

新規・削除された追跡ファイルもGitで戻ります。依存要件は範囲指定のため、元の全パッケージ版の厳密な再現は保証しません。次回更新は同じ追跡先へ進むため、不具合の解消を確認してから実行します。

<a id="database"></a>
### DB移行・DB単位の復元

| 条件 | 起動時の処理 |
|---|---|
| 既存DBの版を上げる | SQLite Backup APIで確定済みWALを含むコピーを作成後、トランザクションで移行 |
| 新規 / 現行DB | 新規作成 / 再移行・追加バックアップなし |
| バックアップ失敗 / SQL失敗 | 移行を開始しない / スキーマ・版をロールバック |
| アプリより新しいDB | ダウングレードせず起動を拒否 |

バックアップ名は `<DBのstem>.pre-v<移行先DB版>.<UTC日時>.<識別子>.sqlite3`。DB版とアプリ版は別です。

DBだけを戻す場合も停止し、現在のDB・同名の `-wal` / `-shm` をまとめて退避してから元のDB名へ復元します。現在のWALを戻したDBへ組み合わせず、画像等との時点整合も確認してください。旧版へ戻す場合は対応するプログラム・設定・データをセットで使います。

<a id="migration"></a>
## 旧ZIP版からの移行

**別ディレクトリへcloneし、既存配置へ上書きしません。** 現行の更新・配置診断はGit専用です。

1. 旧ComfyUI Wrapperを停止し、設定・出力先をバックアップする。
2. [導入手順](BASIC_SETUP.md) に従って別ディレクトリへcloneし、venvを作る。
3. 使用中の設定と出力先全体を新配置へコピーし、相対パス・権限を確認する。`.git`・venv・旧プログラム・配布manifestはコピーしない。
4. 新ComfyUI Wrapperだけを起動してデータ・生成を確認する。共有する絶対パスの出力先はコピー不要だが、旧版・新版を同時起動しない。
5. systemd利用時は手動確認を終了し、新アプリルートで `bash scripts/user/install-autostart.sh` を実行する。

旧 `llmpc-image-webui.service` は登録処理で停止・無効化します。独自サービスは手動で停止・配置先を変更してください。再起動後も `/api/version` の配置先を確認します。

旧配置と移行前データは確認完了まで保管します。新版で移行したDBを旧版へ直接渡さないでください。旧更新の `Release cannot replace this path` もこの移行で対処します。実機の更新・復旧は利用環境で別途検証してください。
