# Google Cloud 部署指南

這份指南把「程式已完成」和「外部服務已接通」分開。前者可由測試證明；後者必須使用你的
Google Cloud project、Telegram token 與 Gemini key 實際驗證。

## 先理解整個部署模型

把系統拆成四個角色，就不容易被 Google Cloud 的介面名稱淹沒：

1. **Cloud Run 是執行環境**：收到 HTTP request 時啟動 FastAPI container。
2. **Firestore 是永久記憶**：Cloud Run instance 可以消失，但單字、去重紀錄和複習狀態不能消失。
3. **Secret Manager 是保險箱**：Telegram token、Gemini key 與 shared secrets 不放進 image 或 Git。
4. **Webhook／Scheduler 是觸發器**：Telegram 觸發單字查詢，Scheduler 每天觸發複習。

本專案不是在部署時「搬移 SQLite 資料庫」。切換方式是把 `STORAGE_BACKEND` 從 `sqlite` 改成
`firestore`。`src/vocab_bot/app.py` 會依該值建立 `FirestoreRepository`，Google client library 再以
Cloud Run service account 的 Application Default Credentials 存取 Firestore。因此 production 不需要
下載 service-account JSON key；正確做法是賦予執行身分最小必要 IAM 權限。

教別人時先要求對方畫出這條資料流：

```text
Telegram → HTTPS webhook → Cloud Run → Gemini
                              ↓
                          Firestore

Cloud Scheduler → protected endpoint → Cloud Run → Telegram
```

如果他能解釋每一條箭頭的「誰呼叫誰、用什麼 credential、狀態存在哪裡」，才算真正理解部署，
而不是只會複製 `gcloud` 指令。

## 1. 準備帳號與秘密資料

你需要：

1. 從 Telegram `@BotFather` 取得 Bot Token。
2. 先私訊 Bot，再取得自己的 numeric chat ID。
3. 從 Google AI Studio 建立 Gemini API key。
4. 建立 Google Cloud project，啟用 billing，並在 Billing → Budgets & alerts 建立低額警示。
5. 產生兩個不同的長隨機字串，分別作為 webhook secret 與 cron secret。

不要把任何真實值貼進 README、私人筆記、Git commit 或公開 issue。

## 2. 啟用服務

安裝並登入 Google Cloud CLI 後：

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com firestore.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

在 Google Cloud Console 建立 Firestore **default database**，選 Native mode。建議 location 使用
`asia-east1`，並讓 Cloud Run 也在同一區域，減少 latency 與跨區傳輸。

Firestore database 建立後，仍需完成兩件不同的事：

- **runtime selection**：Cloud Run 環境變數設為 `STORAGE_BACKEND=firestore`。
- **authorization**：Cloud Run service account 取得 `roles/datastore.user`。

少了前者，程式仍會使用 SQLite；少了後者，程式會選到 Firestore，但 request 會因權限不足失敗。

## 3. 使用 Secret Manager

在 Secret Manager 建立以下 secrets，並貼入各自的值：

- `telegram-bot-token`
- `telegram-webhook-secret`
- `gemini-api-key`
- `cron-secret`

部署時建議引用明確的 secret version，而不是長期依賴 `latest`。這讓每個 Cloud Run revision
使用哪一版 credential 都可追溯；輪替時先新增版本、部署並驗證，再停用舊版本。下方第一次
部署使用 `latest` 是為了降低入門步驟，正式環境完成後應改成實際 version number。

Cloud Run 使用的 service account 必須具備：

- Secret Manager Secret Accessor
- Cloud Datastore User

這些權限分別允許它讀取秘密資料與操作 Firestore；不要直接給 Owner。

## 4. 部署 Cloud Run

將 `YOUR_CHAT_ID` 與 `YOUR_PROJECT_ID` 換成真實值：

```powershell
gcloud run deploy mnemosyne --source . --region asia-east1 --allow-unauthenticated --min-instances 0 --max-instances 1 --memory 512Mi --timeout 60 --set-env-vars "STORAGE_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,TELEGRAM_OWNER_CHAT_ID=YOUR_CHAT_ID,GEMINI_MODEL=gemini-3.5-flash-lite,REVIEW_SIZE=20,TIMEZONE=Asia/Taipei" --set-secrets "TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,TELEGRAM_WEBHOOK_SECRET=telegram-webhook-secret:latest,GEMINI_API_KEY=gemini-api-key:latest,CRON_SECRET=cron-secret:latest"
```

`--allow-unauthenticated` 是因為 Telegram 必須能呼叫 webhook。這不等於沒有保護：應用程式仍會
驗證 Telegram 提供的 secret header，而 daily endpoint 使用另一個 secret。

取得部署後的 service URL：

```powershell
gcloud run services describe mnemosyne --region asia-east1 --format="value(status.url)"
```

先打開 `<SERVICE_URL>/health`，應回傳 `{"status":"ok"}`。

## 5. 設定 Telegram webhook

在本機 `.env` 加入部署 URL：

```text
CLOUD_RUN_SERVICE_URL=https://your-service-url
```

然後執行：

```powershell
.\.venv\Scripts\python.exe scripts\setup_webhook.py
```

這個 script 不會輸出 token。設定完成後，私訊 Bot `/help`，再傳一個測試單字。

## 6. 建立每日 08:00 排程

Cloud Scheduler 的 timezone 直接設成 `Asia/Taipei`，schedule 使用 `0 8 * * *`。在 Google Cloud
Console 建立 HTTP job：

- Method：`POST`
- URL：`<SERVICE_URL>/tasks/daily-review`
- Header：`X-Cron-Secret: <你的 cron secret>`
- Timezone：`Asia/Taipei`
- Schedule：`0 8 * * *`

建立後按 **Force run**。第一次 live test 應確認 Telegram 收到訊息，以及 Firestore 出現
`daily_deliveries` 文件。只看到 Scheduler 顯示 success，不能單獨證明 Telegram 收到訊息。

## 7. 建立失敗單字自動重試排程

Cloud Run scale-to-zero 後沒有常駐 process，因此不能靠 Python `sleep` 或背景 thread 準時重試。
建立第二個 Cloud Scheduler HTTP job，每 10 分鐘喚醒一次 retry endpoint：

- Name：`mnemosyne-retry-failed`
- Method：`POST`
- URL：`<SERVICE_URL>/tasks/retry-failed`
- Header：`X-Cron-Secret: <你的 cron secret>`
- Timezone：`Asia/Taipei`
- Schedule：`*/10 * * * *`

每次 invocation 最多處理一個到期單字。退避順序是 15 分鐘、1 小時、6 小時，之後每天一次；
成功後 queue item 會刪除並透過 Telegram 傳回卡片。

## 8. 成本保護

- Cloud Run 保持 `min-instances=0`、`max-instances=1`。
- 建立 billing budget alert。注意：budget alert 是通知，不是自動停機上限。
- 若使用 Gemini Prepay，先小額儲值並關閉 auto-reload，再設定 project spend cap；Gemini 餘額
  與一般 Google Cloud 帳單是不同的控制面。
- 在 Gemini API project 設定 quota；個人 bot 不需要高 RPM。
- 定期查看 Cloud Run requests、Firestore reads/writes 與 Gemini usage。

Cloud Run、Firestore、Cloud Scheduler 與 Gemini 各自有不同的免費額度、計費週期與停止條件。
價格會變動，部署前應重新檢查
[Gemini billing](https://ai.google.dev/gemini-api/docs/billing) 與各服務官方 pricing 頁面。

## 9. Production checklist

- `/health` 成功
- `/help` 只在你的 private chat 回覆
- 傳送單字後收到完整卡片
- Firestore 同時保存主單字與相關獨立單字
- 同一 Telegram update retry 不會重複處理
- Force run 收到 daily review
- 同一天正常 scheduler retry 不會重複發送
- Gemini 失敗時 Firestore 出現 `pending_words`，retry job 成功後該文件消失
- Cloud Run logs 沒有出現 token 或 API key

## 10. 如何教會另一個人，而不是替他部署

用「Explain → Demonstrate → Teach back」三輪：

1. **Explain**：先讓他說出 Cloud Run 無狀態、Firestore 有狀態，以及為何不能把 SQLite 放在
   Cloud Run 暫存磁碟。
2. **Demonstrate**：一起部署一次，每一步只回答一個問題：程式在哪裡跑、秘密在哪裡、身分是誰、
   request 從哪裡來。
3. **Teach back**：讓他不看文件重新畫資料流，並指出 `STORAGE_BACKEND=firestore`、service account
   IAM、webhook URL 和 cron secret 各自負責什麼。

最後用故障題驗收理解：

- `/health` 正常，但傳單字沒反應：查 webhook 狀態、secret header 與 Cloud Run logs。
- Cloud Run 出現 permission denied：查 service account 的 Firestore／Secret Manager IAM。
- redeploy 後單字消失：確認 production 是否誤用 SQLite。
- Scheduler 顯示 success，但 Telegram 沒收到：success 只證明 endpoint 回應，仍要查 Telegram
  delivery 與 `daily_deliveries`。
