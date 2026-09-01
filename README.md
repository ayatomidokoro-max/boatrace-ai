# boatrace-ai

全国24場の当日全レースを収集し、各艇を説明可能なルールで採点して、本命・穴・3連単候補を抽出するPython 3.11+の第1版です。**自動投票・舟券購入機能はありません。** 基準不足なら無理に候補を出さず「見送り」にします。

## 重要な注意

- 予測は娯楽・分析用であり、的中や利益を保証しません。購入判断は利用者自身の責任です。
- 第1版の取得元は非公式の [Boatrace Open API](https://boatraceopenapi.github.io/api/) です。BOAT RACE公式および関連団体とは無関係で、約3分の遅延、欠損、誤りの可能性があります。最終判断は必ず [BOAT RACE公式](https://www.boatrace.jp/) で確認してください。
- 取得は公開JSONへの通常のHTTP GETのみです。アクセス制限の回避や認証回避は行いません。
- 公式の番組表・競走成績ダウンロードはLZH形式であり、第1版のリアルタイムcollectorには採用していません。collector境界を分けてあるため、将来追加できます。

## セットアップと実行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"

# JSTの当日全場・全レース
boatrace-ai --db data/boatrace.sqlite3 --json artifacts/latest.json

# 日付指定
python -m boatrace_ai --date 2026-09-01 --db data/boatrace.sqlite3
```

### 個人LINEへ通知

LINE Notifyは終了しているため、LINE公式アカウントのMessaging APIを使用します。個人LINEでその公式アカウントを友だち追加し、次の2つを環境変数またはGitHub Secretsへ登録します。

- `LINE_CHANNEL_ACCESS_TOKEN`: Messaging APIのチャネルアクセストークン
- `LINE_USER_ID`: 通知先となる自分のユーザーID（`U`から始まる値）

秘密情報はコード、設定JSON、コマンド引数へ保存しないでください。

```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN = "LINE Developersで取得した値"
$env:LINE_USER_ID = "Uから始まる自分のID"
.\.venv\Scripts\python.exe -m boatrace_ai --notify-line
```

GitHubではSettings → Secrets and variables → Actionsに同名のSecretを2件登録します。「LINE notification」は毎日10:00 JST（01:00 UTC）に自動実行され、手動実行も可能です。GitHub側の混雑により開始が数分以上遅れる場合があります。通知失敗時は自動投票などの代替動作を行わず、終了コード1で安全に終了します。

重みは `config/scoring.json` で変更でき、`--config` で別設定も指定できます。8項目不足または合計が1.0でない設定は安全に拒否します。

終了コードは成功 `0`、取得失敗 `1`、引数不正 `2` です。取得失敗はSQLiteの `runs` に失敗理由を保存し、未確認データを生成せず安全に終了します。

## スコアと判定

各艇を次の重みで0〜100点に正規化します。

|要素|重み|
|---|---:|
|枠番|22%|
|全国勝率|20%|
|全国2連率|12%|
|当地勝率|14%|
|平均ST|14%|
|モーター2連率|10%|
|ボート2連率|6%|
|F回数|2%|

欠損項目は0として加点しません。**存在する項目の重みだけで再正規化**し、別途 `data_completeness` を低下させます。`confidence` はデータ充足率、6艇の揃い具合、上位艇のスコア差から算出します。既定では `confidence >= 0.62` かつ上位差 `>= 4.0` のレースだけを「買い候補」と表示します。

- 本命候補: 基準通過レースの最高スコア艇
- 穴候補: 4〜6号艇のうち最高スコア艇
- 3連単候補: 本命艇を1着固定し、スコア上位4艇から最大6点
- 見送り: confidenceまたは上位差が基準未達

これは統計学習済みモデルではなく、検証可能なベースラインです。重みは仮説であり、履歴データによるバックテスト・校正が次段階です。

## 保存内容

SQLiteには `runs`（実行・取得元・日時・失敗理由）、`analyses`（レース判定・confidence・充足率・3連単）、`entrant_scores`（各艇スコア・理由）を保存します。取得URLとUTC取得日時も保持します。JSON出力にはレースメタデータと全理由が含まれます。

## 開発・テスト

```bash
python -m compileall -q src tests
pytest
```

GitHub ActionsはpushとPull RequestでPython 3.11の構文チェックとpytestを実行します。ネットワークに依存しないfixtureでcollector、欠損処理、採点、3連単、SQLite、失敗記録を検証します。

## 構成

```text
src/boatrace_ai/
  collectors/       # 差し替え可能な収集層
  models.py          # 型付きデータモデル
  scoring.py         # 採点・候補・3連単
  storage.py         # SQLite
  service.py         # 一連の処理と失敗記録
  cli.py             # CLI
tests/               # オフラインpytest
.github/workflows/   # CI
```

## 次の展示監視（第2版）

1. 締切時刻の20〜30分前に対象レースだけ再取得するJSTスケジューラを追加。
2. `preview` の展示タイム、進入コース、展示ST、体重、チルト、風速、波高を別テーブルに時系列保存。
3. 展示前スコアを固定保存し、展示後は新規特徴だけを加えた再評価として差分理由を表示。
4. 欠場・進入変更・強風・展示異常を安全側の見送りルールにする。
5. オッズは取得できた場合だけ期待値表示に使い、ない場合は購入点数や期待値を推測しない。
6. 通知は「買い・見送り・変更」と根拠を送り、自動購入には接続しない。

展示監視版の通知方針は、各レースの展示終了後に再評価し、展示前から重要な変更があった場合だけ送信します。重要変更は、本命艇または穴候補の変更、買い候補から見送り（またはその逆）への変更、confidenceの大幅変動、欠場・進入変更・強風・展示異常とします。同一レース・同一判定の重複通知は状態DBで抑止します。この機能は展示データの時系列収集と差分判定が完成するまで有効化しません。

展示監視エンジンは `--monitor-exhibition` で試験実行できます。同じSQLiteを朝分析と展示監視で共有する必要があります。展示タイムが6艇分揃い、重要変更があった場合だけLINEを送信し、同じ変更は再送しません。

```bash
python -m boatrace_ai --db data/boatrace.sqlite3 --monitor-exhibition --notify-line
```

GitHub上の展示定期監視は、実行間でSQLite状態を安全に永続化する仕組みを追加してから有効化します。それまでは毎朝10時通知のみが自動実行されます。
