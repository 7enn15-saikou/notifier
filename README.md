# イープラス在庫復活 → LINE通知

指定した公演ページを10分おきに確認し、券種のステータスが「受付中」に変わったらLINEに通知します。
（GitHub Actionsで動くので、PCを付けっぱなしにする必要はありません）

## セットアップ

### 1. LINE公式アカウントとMessaging APIを用意する
LINE Notifyは2025年3月に終了したため、Messaging APIを使います。

1. [LINE Developers](https://developers.line.biz/) にLINEアカウントでログイン
2. プロバイダーを作成 → 「Messaging APIチャネル」を作成
3. チャネル基本設定の一番下にある **あなたのユーザーID**（`U` から始まる文字列）をメモ
4. Messaging API設定の **チャネルアクセストークン（長期）** を発行してメモ
5. Messaging API設定のQRコードから、作った公式アカウントを友だち追加（これを忘れると通知が届きません）

### 2. GitHubにアップロード
1. GitHubで新しいリポジトリを作る（Privateを推奨）
2. このフォルダの中身をすべてアップロード（`.github/workflows/monitor.yml` も忘れずに）

### 3. Secretsを登録
リポジトリの Settings → Secrets and variables → Actions → New repository secret

| 名前 | 値 |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | 手順1-4のトークン |
| `LINE_USER_ID` | 手順1-3のユーザーID |

### 4. 動作確認
- Actionsタブ → `eplus-monitor` → Run workflow で手動実行
- ログに各券種のステータスが表示されれば成功です
- LINEの疎通だけ確認したいときは、手元で `python monitor.py --test`
  （環境変数 `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` を設定してから実行）

## 仕様
- 通知は「受付中以外 → 受付中」に変わった瞬間の1回だけ（受付中が続いても連投しません）
- 前回の状態は `state.json` に保存され、自動でコミットされます
- 監視対象を変えるときは、`monitor.yml` の `env` に `EPLUS_URL` を追加するか、`monitor.py` の `DEFAULT_URL` を書き換えてください

## 注意
- 受付状況はイープラス側でリアルタイムに反映されないことがあります
- 間隔を短くしすぎないでください（アクセス制限の原因になります）
- GitHub Actionsのスケジュール実行は数分遅れることがあります
- GitHubのIPからのアクセスをイープラスが拒否する場合は、ログに「受付状況を取得できませんでした」と出ます
- 通知はあくまで目安です。復活したら、すぐ公演ページから申し込んでください
