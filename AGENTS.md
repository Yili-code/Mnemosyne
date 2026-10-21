<!-- BEGIN CODEX CROSS-SESSION SYNC -->
## 多對話與跨電腦交接（2026-10-21）

這一節是目前的交接規則；下方有日期的舊摘要保留作歷史導覽，不能當成目前進度。使用者最新明確指示優先。

### 每次開始或恢復工作
- 先確認本次 SessionStart / UserPromptSubmit hook 的同步結果。若未執行，從專案根目錄執行 `python .codex/session_sync.py --manual`（macOS/Linux 可用 python3）。
- hook 只 fetch 並在工作目錄乾淨且歷史可快轉時更新追蹤分支。不會 commit、push、stash、reset 或覆蓋衝突。
- 同步失敗、遠端領先且本機有修改、歷史分歧時，先處理同步問題；可做唯讀診斷，不可把狀態說成已同步。離線工作需明確標記。
- 同步後重新讀取本檔、PROJECT_STATUS.md、相關 docs/handoffs/ 紀錄，再核對實際檔案、近期提交與未提交修改。不要單憑聊天記憶重做已完成的功能。
- 實作以檔案與驗證為準；需求以最新明確指示為準；記錄衝突要指出，不臆測完成。歷史摘要中的測試與部署結果不適用於新版本。

### 每個任務自動留下紀錄
- 開始實作時建立獨立 `docs/handoffs/<日期>-<任務>-<唯一識別>.md`，記錄工作範圍、分支與涉及檔案；先查看其他 active 任務，避免重疊編輯。
- 在重要決策、可驗證階段完成，以及每次有實質進展的最終回覆前更新自己的紀錄，不需使用者另貼同步指令。
- 記錄含時區的更新時間、基準提交、目標、已實作/已驗證/未完成、取消的方案、驗證結果、下一步、commit/push 狀態。不可把中斷工作標成完成。
- PROJECT_STATUS.md 只放共同目標、穩定決策與交接目錄入口；詳細進度分散於各任務檔。修改共用文件前重讀，保留他人更新。
- 完成可交接工作時，檢查並只提交本任務相關且可分享的檔案，連同交接紀錄；沿用既有分支/PR 流程並推送已設定的遠端。若含其他任務未發布提交、未解決衝突或無法驗證內容，先回報，不能盲目全部加入。
- 不提交秘密、私人資料、原始聊天或無關修改；不 force push、不自動丟棄修改。雲端程式部署與 Git 同步不同，未另獲授權不執行部署。

### 自動化限制
- `.codex/hooks.json` 設定新建、恢復、分叉、壓縮後及每次新提示的同步檢查；需要本機 Codex 支援、Python 3、Git、遠端存取及專案/hook 信任。
- 新或變更的 hook 需要使用者在 Codex 的 hook 審查介面信任；CLI 可使用 `/hooks`。不得自行修改信任紀錄或繞過審查。
- 其他電腦必須先取得這些檔案並信任 hook。已開啟的聊天應重新讀取指引，不能假設即時載入。
- 檔案規則與同步鎖不是跨對話編輯鎖。多任務重疊時使用獨立分支/worktree，並明確整合。
<!-- END CODEX CROSS-SESSION SYNC -->


## 歷史專案導覽（使用前核對目前程式）

# Repo 工作摘要

核對日期：2026-10-14。依目前工作目錄的文件、程式碼與測試整理；不是正式環境驗證報告。

## 先讀與專案範圍

- 本專案是 Python 3.11+、單一擁有者私聊使用的 Telegram 英文字卡 bot（alpha 0.1.0），內容面向繁體中文使用者；沒有前端或多租戶帳號層。
- 先讀 `README.md`（含 AI agent 指引）、`CONTRIBUTING.md`；部署讀 `DEPLOYMENT.md`，秘密資訊與通報讀 `SECURITY.md`，版本紀錄見 `CHANGELOG.md`。
- 修改行為前依序讀 `src/vocab_bot/app.py` → `service.py` → `models.py` / `repository.py` → 對應模組及 `tests/test_*.py`。
- 保持 owner-only 範圍；多使用者或新增基礎設施供應商等擴張，依貢獻指南先提出需求討論。

## 已確認架構與依賴

| 位置 | 責任 |
| --- | --- |
| `src/vocab_bot/app.py` | FastAPI 路由、secret 驗證、快取且延遲建立 Settings / service、選擇儲存與傳送模式 |
| `service.py` | 指令、owner 檢查、訊息去重、生成、重試、複習與 callback 流程 |
| `models.py` / `repository.py` | Pydantic 資料契約；Repository Protocol 的 SQLite / Firestore 實作 |
| `gemini.py` / `word_rules.py` | HTTP 結構化生成、schema 驗證、輸入正規化、相關詞彙過濾 |
| `spaced_repetition.py` / `review_tasks.py` | 到期排序、評分排程；Cloud Tasks 工作建立與名稱去重 |
| `telegram.py` / `traditional_chinese.py` | Telegram API、HTML escaping 與排版；發送時以 OpenCC `s2twp` 轉臺灣繁體 |
| `tests/` / `scripts/setup_webhook.py` | 離線測試；註冊 Telegram webhook（外部寫入操作） |
| `.github/workflows/ci.yml` / `Dockerfile` | CI Python 3.11、3.14；容器 Python 3.12-slim、Uvicorn、預設 PORT=8080 |

- `pyproject.toml` 以 Hatchling 建置 `src/vocab_bot`；執行依賴為 FastAPI、Uvicorn、Pydantic 2、HTTPX、Firestore / Cloud Tasks clients、python-dotenv、OpenCC、tzdata。Gemini 使用 HTTPX 直接呼叫 REST API，沒有 Gemini SDK。
- 開發依賴：pytest、pytest-cov、Ruff。Ruff 行長 100、target py311，啟用 E/F/I/UP/B/SIM；pytest 設定 `pythonpath=src`、`testpaths=tests`。未見依賴 lockfile，版本範圍以 `pyproject.toml` 為準。
- SQLite：WAL，`words` / `updates` / `deliveries` / `pending_words`，多數資料存 JSON payload。Firestore：`words` / `telegram_updates` / `daily_deliveries` / `pending_words`。

## 已確認主要流程

- **生成**：`POST /telegram/webhook` 驗證 `X-Telegram-Bot-Api-Secret-Token` → owner 私聊與 update ID 檢查 → 正規化單一英文詞或片語（最多 50 字元，可含連字號、撇號）→ Gemini `responseJsonSchema` → Pydantic、headword / 學習欄位檢查及相關詞過濾 → 保存主詞與相關 seed → 傳回字卡。
- **保存慣例**：重新生成保留原有建立時間與學習進度；相關 seed 不覆蓋既有完整字卡。舊資料缺 `due_at` 時回填 `created_at`。新詞預設立即到期。
- **指令**：`/start`、`/help`、`/ask`、`/search`、`/words`、`/review`、`/clear`。`/ask` 不存字卡；`/search` 精確查詢已正規化詞彙，不呼叫 Gemini、不修改學習資料（訊息本身仍有 update 去重寫入）。
- **複習**：`/review` 或 `/tasks/daily-review` 只挑到期詞，依 due_at、review_count、word 排序。兩個儲存後端目前均讀取全部詞彙再由 Python 篩選。`/review` 跳過每日一次限制，不跳過到期條件。
- **評分**：送出卡片不增加 review_count。Hard 首次 1 天、Good 首次 3 天，後續依既有間隔 / ease 計算，上限 365 天；Easy 永久刪除。程式仍支援 Again（10 分鐘），目前鍵盤只顯示 Hard / Good / Easy。
- **傳送**：direct 直接送出；cloud_tasks 每卡一工作，名稱由 delivery key + word 的雜湊決定，AlreadyExists 視為成功。worker 重新讀取目前字卡，已刪除則跳過。排程日期按 `TIMEZONE` 計算；daily delivery 紀錄表示已完成送出或入列流程，不是 Telegram 收件證明。
- **失敗重試**：GeminiError 存入 pending_words，退避 15 分鐘 → 1 小時 → 6 小時 → 每天。`/tasks/retry-failed` 每次最多領取一筆，lease 5 分鐘；成功保存、刪除 retry，再通知 Telegram。這不是通用的 Telegram 發送重試佇列。
- **清空**：`/clear` 需按確認，刪除詞彙、pending 與 delivery 紀錄，保留 update 去重紀錄。

## 開發與部署指令

在 repo 根目錄的 PowerShell 執行（首次建立環境；已有 `.env` 時不要覆蓋）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn vocab_bot.app:app --host 127.0.0.1 --port 8000 --reload
# 另一個終端
Invoke-RestMethod http://127.0.0.1:8000/health
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git diff --check
```

- 預設設定：sqlite、`data/vocabulary.sqlite3`、direct、REVIEW_SIZE=20（1–50）、Asia/Taipei、`gemini-3.5-flash-lite`。值核對 `config.py` 與 `.env.example`；上述是 repo 設定，不保證遠端模型可用。
- `/health` 不載入完整設定，也不驗證任何外部服務。其餘流程會載入必要憑證；全部 `/tasks/*` 使用 `X-Cron-Secret`，與 webhook secret 分開。
- 正式環境按 `DEPLOYMENT.md` 設定 Cloud Run + Firestore + Secret Manager + Cloud Tasks + Scheduler；不可依賴 Cloud Run 本機 SQLite。沒有內建 SQLite→Firestore 搬移工具。
- `scripts/setup_webhook.py` 會註冊 `message`、`callback_query`，且設 `drop_pending_updates=True`；執行會丟棄 Telegram 尚未處理的 updates，不是唯讀檢查。

## 慣例、限制與待確認

- 保持測試離線、可重現；服務測試用 fakes，HTTP 呼叫用 monkeypatch；不要把單元測試通過說成雲端整合成功。秘密、真實 chat ID、使用者資料或完整 provider 回應不可加入日誌、fixture 或提交。
- 訊息先 claim update 再做外部副作用；callback 依目前詞彙到期狀態拒絕重複評分，並非永久 callback ID 去重。Firestore 評分 / retry claim 使用 transaction；現有 SQLite 評分測試驗證連續重複呼叫，不能據此宣稱並行安全。
- Cloud Tasks / Telegram 最終傳送仍是 at-least-once；不能承諾 exactly-once。daily direct 發送與完成紀錄之間也非單一交易。
- `SECURITY.md` 的 IAM 簡述未列 Cloud Tasks Enqueuer，部署指南有列；使用 queue 時核對完整部署指南。setup_webhook 的 HTTPError 處理直接輸出例外，分享錯誤前須檢查是否含 token URL，不能一概假設所有例外均已去敏。
- **尚未確認**：實際部署 revision、IAM / secrets、遠端模型可用性、webhook / Scheduler / Cloud Tasks 端到端傳送、Firestore 真實交易與並行行為、資料量增長時的效能。本次未連線驗證外部服務。
- **本次檢查範圍**：閱讀主文件、所有核心模組與測試案例；測試 / lint 執行結果另於下方紀錄。開始時已有 `.env.example`、`DEPLOYMENT.md`、`README.md`、`config.py`、`test_config.py` 的未提交修改，本摘要依其目前內容整理，未變更這些檔案。
- **本次執行結果**：本機 `python` 為 3.13.5，未見 repo `.venv`。`python -m pytest --basetemp=.pytest-tmp-familiarization` 因缺少 `httpx`、`google.cloud` / `google.api_core`，在收集階段產生 5 個錯誤，未完成測試。`python -m ruff check .` 與 `python -m ruff format --check .` 因未安裝 Ruff 無法執行；未安裝或改動環境依賴。`git diff --check` 無錯誤；外部服務與本機 HTTP 健康檢查未執行。
