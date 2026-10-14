# George-Bot-2026

DiscordでジョージにメンションするかDMを送ると、Gemini APIで会話できます。
既存の `/progress 名前` と `@ジョージ pro 名前` による検索も利用できます。

## 起動

Python 3.11以上を使用します。

```powershell
python -m pip install -r requirements.txt
$env:DISCORD_TOKEN = "Discord Botのトークン"
$env:GEMINI_API_KEY = "Google AI Studioで発行したAPIキー"
$env:GEMINI_MODEL = "gemini-flash-latest"
python main.py
```

APIキーは [Google AI Studio](https://aistudio.google.com/apikey) で発行してください。
ホスティング環境では同名の環境変数をSecretsなどに設定します。
`.env.example` は設定項目の見本です。`.env` の自動読み込みは行いません。
キーやトークンはコードやGitに保存しないでください。
`GEMINI_MODEL` は省略可能です。利用可能なモデルIDに変更できます。

Discord Developer PortalのBot設定で **Message Content Intent** を有効にし、
Botにチャンネルの閲覧・メッセージ送信権限を付与してください。
既存の検索には `applications.commands` スコープも必要です。
リアクション機能にはリアクション追加・メッセージ履歴閲覧権限が必要です。

## 会話

- サーバー: `@ジョージ こんにちは！`
- DM: `こんにちは！`
- 履歴の消去: `@ジョージ リセット` またはDMで `リセット`

履歴はチャンネルとユーザーの組み合わせごとに直近10往復を保持します。
最大256組で、上限に達すると使用中でない古い履歴から削除されます。
再起動すると履歴は消えます。同じ会話への同時リクエストは待つよう案内します。
会話として送った本文とその履歴はGoogleのGemini APIに送信されます。
APIの利用上限・料金はGoogle側の設定を確認してください。

ジョージの口調は `george_chat.py` の `SYSTEM_INSTRUCTION` で調整できます。
APIキー未設定・APIエラー時は案内を返し、検索機能は引き続き利用できます。

## 会話が失敗するとき

Discordの返答にHTTPコードまたはエラー分類を表示し、起動ログには
`Gemini request failed: type=... code=... reason=...` を出します。
APIキー・会話本文・Googleのエラー本文はログに出しません。

- HTTP 400: キー・リクエスト設定・利用地域などを確認。
- HTTP 401/403: キーとプロジェクトの権限・API制限を確認。
- HTTP 402: 支払い設定や残高を確認。
- HTTP 404: `GEMINI_MODEL` が利用可能なモデルか確認。
- HTTP 429: AI Studioの利用枠を確認。上限の種類によっては待つだけで解消しません。
- HTTP 5xx / timeout: 時間を置いて再試行。
- network: Botの起動環境からGoogleへの通信を確認。

環境変数やコードを変更したら、実際に動いているBotを再起動してください。

### RenderでShellが使えない場合

`main.py` と `check_gemini.py` をデプロイし、Environmentに
`GEMINI_DIAGNOSTICS=1` を設定すると、起動ごとに1回だけ固定の短い入力で
Geminiの文章生成を試します。Discordの会話履歴は送信しません。
API利用枠を消費し、有料プロジェクトには適用料金がかかります。
診断は別スレッドで実行し、Discordログインは待たせません。
Logsの `Configured model:`、`Diagnostic failed:`、`Provider message:` を確認してください。
APIキーとDiscordトークンは伏せ字にします。
確認後は `GEMINI_DIAGNOSTICS` を削除するか `0` に戻してください。
