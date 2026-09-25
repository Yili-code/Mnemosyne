# Mnemosyne

Mnemosyne 是一個為個人使用設計的 Telegram 英文記憶系統。傳送一個英文單字後，Bot 會透過
Gemini 產生 KK 音標、繁體中文解釋、例句、實際用法、常見搭配，以及語意或使用情境相關的獨立
單字。每天台北時間 08:00，再依 weighted review 從資料庫選出 20 個單字複習。

## 它解決什麼問題

一般字典解決「現在看不懂」，但沒有處理「幾天後還記不記得」。Mnemosyne 把查詢、保存與
再提取放在同一個 loop：

1. 你主動查一個單字。
2. Gemini 產生結構固定的學習卡。
3. 程式過濾普通時態、複數與常規衍生詞。
4. 主單字和相關單字都存進資料庫。
5. 每天優先抽出新字、較少出現的字、久未複習的字。

這個設計的實際價值是從 recognition 走向 recall。對工程學習而言，它也示範了 webhook、
structured output、資料持久化、排程、idempotency 和 serverless deployment 如何一起構成
一個可運作的 AI product。

## 相關單字的定義

「相關」不是 TOEIC／IELTS／Daily 標籤，而是經常出現在這些英文情境中的獨立詞彙，例如：

- synonym / antonym
- 同一工作、旅行、學術或日常情境常一起使用的字
- 容易混淆、值得比較的字
- 概念上直接相鄰的字

預設排除複數、過去式、`-ing`，以及普通的名詞／動詞／形容詞／副詞衍生。只有意義已
明顯獨立、且 Gemini 提供具體理由時，才允許例外。

## 系統結構

```text
Telegram message
      ↓ webhook + secret validation
Cloud Run / FastAPI
      ├── Gemini structured JSON → schema validation → derivation filter
      ├── Firestore → words, review state, processed updates
      └── Telegram Bot API → readable HTML reply

Cloud Scheduler (08:00 Asia/Taipei)
      ↓ authenticated-by-secret daily endpoint
weighted selection → Telegram daily review → update review state
```

Cloud Run 使用 Firestore；本機開發可使用 SQLite。這不是兩套產品，而是同一個 repository
interface 的兩個實作，讓測試不需要連線雲端，同時避免把 Cloud Run 的暫存磁碟誤當永久資料庫。

## Weighted review

每個單字的權重由兩部分構成：

- `novelty = 5 / (1 + review_count)`：出現越少次，優先度越高。
- `spacing = 1 + days_since_review / 7`：離上次複習越久，優先度越高，上限 30 天。

程式使用 weighted sampling without replacement，所以同一份日報不會重複抽到同一個字。
這比完全隨機更接近學習目標，也仍保留變化性。

## Telegram 指令

- 直接傳送一個英文單字：建立並保存學習卡
- `/help`：使用說明
- `/stats`：資料庫單字總數
- `/words`：列出資料庫內所有單字、詞性與中文意思
- `/review`：立即產生一輪額外複習，不占用當日 08:00 的排程紀錄

Bot 只處理 `TELEGRAM_OWNER_CHAT_ID` 對應的私人聊天室。

## 自動重試

Gemini 的 timeout、quota、服務暫時不可用或輸出未通過 schema／詞形規則時，系統不會丟失查詢。
失敗單字會保存到 repository 的 `pending_words` queue，依序在 15 分鐘、1 小時、6 小時後重試，
之後每天重試一次直到成功。成功後會寫入正式單字庫、移除 queue item，並主動把學習卡傳回
Telegram。

Cloud Run 不會在沒有 request 時自行執行背景 timer，因此 production 必須由 Cloud Scheduler 每
10 分鐘呼叫 `/tasks/retry-failed`。每次只處理一個到期項目，控制 Gemini 用量並避免 request timeout。

## 本機執行

需求：Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

填寫 `.env` 後啟動：

```powershell
.\.venv\Scripts\python.exe -m uvicorn vocab_bot.app:app --reload
```

本機模式預設使用 `data/vocabulary.sqlite3`。`.env` 和 SQLite 檔案都被 Git 忽略。

執行驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp
.\.venv\Scripts\python.exe -m ruff check .
```

## 雲端部署與費用

完整步驟見 [DEPLOYMENT.md](DEPLOYMENT.md)。推薦組合：

- Cloud Run：接收 Telegram webhook，需要時才啟動
- Firestore：永久保存單字和複習狀態
- Cloud Scheduler：每天 08:00 呼叫 daily endpoint
- Gemini API：產生結構化學習內容

以單人、每天少量查字的規模，預期會落在免費額度內，但「免費額度」不是絕對零費用保證。
Google Cloud 仍可能要求 billing account，錯誤設定或超額使用也可能計費。請建立 budget alert，
並維持 Cloud Run `min-instances=0`、`max-instances=1`。

截至 2026-09-24，官方頁面列出的主要免費額度包括：

- [Cloud Run pricing](https://cloud.google.com/run/pricing)：request-based services 每月
  200 萬次 requests，另有 CPU/RAM 額度。
- [Firestore pricing](https://cloud.google.com/firestore/pricing)：一個 free database，
  每日 50,000 reads、20,000 writes，並有 1 GiB storage。
- [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing)：每個 billing account
  前 3 個 jobs 免費。
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)：free tier 與價格依模型而異。

價格會變動，部署前應重新檢查官方頁面。

## 安全與可靠性

- Telegram webhook header 必須通過 shared secret。
- 排程 endpoint 使用另一組 secret，避免被公開觸發。
- API keys 只放在 `.env` 或 Secret Manager。
- Telegram `update_id` 會保存，避免 webhook retry 造成重複處理。
- Gemini 回傳必須通過 Pydantic schema 和額外詞形規則，失敗時不寫入資料庫。
- 每日正常排程有 date-level delivery record，Scheduler retry 不會重複傳送。

## 目前驗證邊界

自動測試涵蓋詞形過濾、SQLite 寫入、update idempotency、weighted selection 與 Telegram rendering。
沒有真正的 Token/API key 時，不應宣稱 Gemini、Telegram 或 GCP production deployment 已完成 live
驗證。
