# KTV 前端重構設計（AloeberryHome KTV System）

- **日期**：2026-06-22
- **作者**：Victor Liu（與 Claude 共同腦力激盪）
- **狀態**：設計已核准，待寫實作計畫
- **目標版本基準**：`pikaraoke-1.19.0`，git HEAD `c6c2c85`（branch `feature/round3-t1t2-evolution`）
- **後端契約測試基準**：750 pytest 全綠

---

## 1. 背景與鑑識基準

AloeberryHome KTV System 是 PiKaraoke 1.19.0 的重度客製分支。後端 AI 管線（Demucs 人聲分離、Whisper、線上歌詞對齊、ASS 雙行卡拉OK字幕、HLS 多音軌原唱/伴奏、SoundTouch 變調、YIN 麥克風評分、SQLite）功能完整、有 750 測試。**問題集中在前端呈現層**：

關鍵鑑識發現（前端視角）：
- **SPA loader 是病灶**：`spa-navigation.js` 的 `executeScripts()` 每次換頁重新執行模板內 inline `<script>`，逼著約 2,200 行 JS 卡在 Jinja 模板裡，無法 lint/測試/模組化。
- **`splash.js` 是 1045 行單體**，塞約 12 種職責、37 個全域、20 個 socket handler、跨 5 檔隱性全域。
- **約 1,880 行死碼**：`home.html`、`queue.html`、legacy `files.html`/`search.html` 仍隨版發佈但零路由渲染，且重複現役 `queueview.html` 邏輯。
- **三個招牌功能實質壞掉**：
  - 麥克風評分 → `get_now_playing` 未回傳 `now_playing_filename`，splash 取不到參考音高，**每次評分皆退回亂數**。
  - 場次總結畫面 → 唯一觸發點 `/reset_session` **無任何 UI 入口**。
  - 移調 → 歌曲內可變調但**換歌即歸零**，持久路徑 `/transpose` 的呼叫者在死掉的 `home.html`。
- **約一半 `scores.py` 路由是孤兒**（後端做好、前端沒接）：最愛、推薦、reprocess、最常播/歌手目錄。
- **i18n 半途而廢**：Babel 全套裝好，但約 121 句繁中硬寫、`queueview.html`/`splash.js` 零 `_()`。
- **離線風險**：`sortablejs@latest` CDN、YouTube 縮圖熱連結（此為 LAN/家用機）。
- **控制端點未授權**：`controller.py` 的 skip/pause/volume/audio_mode/transpose 等零 `is_admin()`。
- **可當地基的亮點**：乾淨且有測試的後端 socket/JSON 契約；`modern-theme.css` 506-token 設計系統。

使用情境（決定設計）：**大螢幕（電視/投影機）當播放畫面 splash + 每位客人用自己手機當遙控**。

---

## 2. 目標與非目標

### 目標
1. **視覺現代化**：建立 Neon Night 設計系統並統一套用。
2. **派對操作流程**：手機遙控「找歌優先」、大螢幕「全幅沉浸」。
3. **可維護性/模組化**：拆解 `splash.js`、消滅 inline JS/CSS、建立清楚模組邊界。
4. **多裝置/響應式**：電視固定大畫面與手機觸控遙控兩套前端 + RWD。

### 非目標（明確排除，記錄在案）
- 改用前端框架（React/Vue/Svelte）。
- 控制端點伺服器端授權 —— **接受的家用 LAN/信任環境風險**。
- 完整多語系（改為繁中單語）。
- 後端架構大改（僅做第 7–8 節列出的針對性、加欄位式修正）。
- 內容灌入為正式營運工作；本案僅 seed 少量測試歌曲以供驗證。

---

## 3. 關鍵決策與理由

| 決策點 | 選擇 | 理由 |
|---|---|---|
| 重構深度 | **結構性重構（不換框架）** | 留住有 750 測試的後端契約；救出卡在 Jinja 的前端；風險可控 |
| 導航架構 | **MPA + 原生 ES 模組 + import map（零建置）** | splash 本就單頁；手機整頁載入在 LAN 近乎無感；消除 SPA loader 病灶；零 build、可離線釘本地 |
| 視覺identity | **Neon Night**（暗色玻璃 + 霓虹青/洋紅） | 延續現有暗色玻璃、更現代；暗底適合電視暗房演唱 |
| 手機佈局 | **找歌優先（Spotify 式）** | 底部分頁 + 常駐迷你播放列，最熟悉、最好擴充 |
| 大螢幕佈局 | **全幅沉浸（經典 KTV）** | MV 滿版、歌詞最大最醒目、臨場感最強 |
| 語系 | **繁中單語 + 字串集中化** | 家用最低維護，符合 single-owner 原則 |
| 後端修正範圍 | 評分、重置/總結入口、移調跨歌持久化（**不含**控制端點授權） | 三招牌功能純前端救不動；授權為接受風險 |
| 孤兒功能 | **全部接上**（最愛、reprocess、推薦、最常播/歌手目錄） | 後端已完成，補前端 CP 值高；reprocess 對處理 staging 13 首尤其實用 |

---

## 4. 架構總覽

1. **後端不動原則**：保留 Flask/Jinja + socket/JSON 契約為穩定 API 邊界；只做第 7–8 節的加欄位式小修正，**不破壞既有 750 測試**。
2. **MPA 取代 SPA loader**：刪除 `spa-navigation.js` 的 `executeScripts` 模型。手機遙控每頁正常整頁載入；splash 為單一長期頁、不導航。
3. **原生 ES 模組 + import map**：以 `<script type="module">` 載入；用 import map 將 vendored 函式庫（hls、subtitles-octopus、soundtouch、sortable 等）釘成本地路徑 → 離線安全、零 build、可 lint/快取。
4. **單一 CSS 契約**：以 `modern-theme.css`（506 token）為地基擴充成 Neon Night 設計系統；將 708 行 inline `<style>` 與 182 個 inline `style=` 全數遷移上 token，消除 `!important` 特異性戰爭。

---

## 5. 模組拆解

### 5.1 前置清理（最先做，降風險）
- 刪 `home.html`(313)、`queue.html`(598)、legacy `files.html`/`search.html`(~970)，合計約 1,880 行死碼。
- 在刪除前，先把它們**唯一還活著的功能**搬進現役頁：持久化移調 UI、排行榜開關、合唱第二歌手欄位。
- 合併 `queue.html`/`queueview.html` 的重複佇列邏輯至單一來源。

### 5.2 `splash.js`（1045 行）→ 拆成 ES 模組（行為不變，只換結構）
- `player-core`（HLS 建立/生命週期）
- `audio-pipeline`（原唱/伴奏多音軌切換）
- `subtitles`（SubtitlesOctopus ASS 渲染）
- `pitch-shift`（SoundTouch AudioWorklet）
- `scoring`（pitch-analyzer + pitch-meter + 送分）
- `session-ui`（計時、排行榜、場次總結、轉場）
- `bg-media` + `screensaver`
- `sync`（主從多螢幕）
- `config`/`prefs`（偏好即時套用）
- 已乾淨的 `score.js`/`fireworks.js`/`pitch-analyzer.js`/`pitch-meter.js` 保留，僅把隱性跨檔全域改為明確 `import`。

### 5.3 `queueview` inline（約 401 行）→ 遙控模組
- `now-playing-bar`（迷你播放列，可展開完整控制）
- `controls`（transport / 原唱伴奏 / 移調 / 投票跳過〔選配，非核心〕）
- `queue-view`（拖曳重排、公平排隊）
- `browse`（songpicker 清單 + 搜尋 + 語言/歌手篩選）
- `favorites`
- `scores-view`（排行榜 + 歷史）

### 5.4 共用核心 `core/`
- `socketClient`（單例，取代目前 6 種各自 `io()` 初始化）
- `nowPlayingStore`（單一真相來源，消滅三份重複的 now-playing 解析）
- `api`（fetch 包裝）
- `ui`（通知、escape 等工具，去除 `showNotification` 重複定義）
- `strings`（繁中 UI 字串集中）
- `song-row`（共用歌列元件，去除跨頁重複渲染）

---

## 6. 螢幕與資訊架構

### 6.1 大螢幕 splash（全幅沉浸，全部 Neon Night）
- 狀態機：`playing`、`idle/screensaver`(+QR)、`transition`(接下來倒數)、`score`(分數揭曉 + 煙火)、`leaderboard`、`session-summary`。
- `playing` 角標：正在播放（左上）、已唱計時 + 接下來（右上）、音準條（右側，演唱中才出現）、QR 掃碼點歌（右下）、今晚最高分（左下）；歌詞壓下三分之一、最大字、青色逐字填色。

### 6.2 手機遙控（找歌優先）
- 底部分頁：**點歌 / 排隊 / 計分 / 更多**；常駐迷你播放列（點開 → transport、原唱/伴奏、Key 移調；投票跳過為選配、非核心）。
- **點歌**：搜尋 + 語言/歌手篩選 + 歌列（＋排隊、♥最愛）；本地 + YouTube 結果與下載進度。修正目前 O(n) 的 Jinja 搜尋反模式；超大歌庫的虛擬捲動列為選配。
- **排隊**：佇列（拖曳重排、公平排隊橫幅、清空確認）。
- **計分**：今晚排行榜 + 播放歷史。
- **更多**：設定/管理（手風琴）、歌庫管理、批次改名、reprocess（單曲 + 批次處理 staging）、開新一夜 + 場次總結入口、推薦「猜你想唱」。
- admin 區塊維持前端隱藏（伺服器授權不納入）。

### 6.3 RWD 策略
- splash 為固定大畫面（電視），以 `?scale=` 或視窗縮放適配解析度。
- 手機遙控以 mobile-first 設計，沿用 `modern-theme.css` 的 `--tap-target` 與 `@media` 斷點；桌面瀏覽器自動加寬欄位。

---

## 7. 資料流與狀態

- **單一 socket 單例** → `nowPlayingStore`（唯一真相來源）→ 各 view 訂閱渲染，消除三份重複的 now-playing 解析/輪詢。
- MPA：每頁載入自己的模組 → 先以 JSON 取得初始狀態 → 訂閱 socket 即時更新。**無 client router**。
- **移調半音寫進佇列項目**，跟著每首歌走（換歌不再歸零）。

---

## 8. 折進來的功能修正

- **評分修好**：`get_now_playing`（`playback_controller.py`）補 `now_playing_filename` → splash `_initMicScoring` 取得正確檔名 → 真正讀取 `_pitch.json` 參考音高（不再亂數）。
- **開新一夜 / 場次總結**：在「更多」加入按鈕，接上 `/reset_session` 與場次總結畫面觸發。
- **移調跨歌持久化**：見第 7 節。
- **接上孤兒功能**：最愛 ♥（songpicker 已備 `user_favorites`）、推薦「猜你想唱」、reprocess（單曲 + 批次處理 staging 13 首）、最常播/歌手目錄。
- **順手修小瑕疵**：splash 主題初次載入即套用（並修正 `themes.css` 指向不存在的元素 ID）、`hide_notifications` 真正生效、轉場倒數讀真正的 `splashDelay`、迷你播放列原唱/伴奏初始狀態對齊後端 default（original）、找回清空佇列確認與音量 debounce、移除死碼（`isScoreShown`、fireworks `getRandomNumber`、`#score-drums`、「guide」音軌註解等）。

---

## 9. 離線韌性
- vendored 函式庫全部本地，透過 import map 解析；移除 `sortablejs@latest` CDN 與 YouTube 縮圖熱連結（改本地快取或後端代理）→ LAN/離線可正常運作。

---

## 10. 視覺設計系統：Neon Night（token 草案）
- 背景：`--bg: #0a0a12`、徑向暈光 `radial-gradient(... #1b1140 ... #0a0a12)`
- 玻璃面板：`--panel: rgba(255,255,255,.06)`、`--panel-border: rgba(255,255,255,.12)`、`backdrop-filter: blur(6–8px)`
- 主強調（青）：`--accent: #22d3ee`／hover `#67e8f9`
- 次強調（洋紅）：`--accent-2: #e879f9`；輔助紫 `#a78bfa`
- 文字：主 `#ffffff`、次 `#9aa3b5`、弱 `#7c8499`
- 狀態：成功 `#34d399`、提醒 `#facc15`
- 歌詞逐字填色：青 `#22d3ee` →（未填）`#586074`
- 既有 ASS 字幕的奶油→琥珀填色保留為「歌詞」既有風格，不與 UI 衝突。

> 註：以上為設計 token 草案，實作時併入 `modern-theme.css` 的 `:root` 變數層。

---

## 11. 測試策略
- **後端 750 pytest 維持全綠**：契約變更皆為加欄位、不破壞既有測試；針對第 8 節後端修正補對應單元測試（如 `now_playing_filename` 出現於 payload、移調持久化）。
- **前端**：目前 0 JS 測試、零 build。務實做法：
  - 保留 pytest 為安全網。
  - 每個 PR 附**手動測試清單**（符合 CLAUDE.md 既有要求）。
  - **Playwright 煙霧測試**（排歌 → 播放 → 原唱/伴奏切換 → 評分非亂數 → 開新一夜）列為**選配後續**，需先 seed 歌庫方可驗。

---

## 12. 上線策略（漸進、全程可跑）
1. 前置清理（刪死碼、合併重複、把死碼裡的活功能搬進現役頁）。
2. 共用核心 `core/`（socket / store / strings / song-row）就位。
3. 一次重構一個面：先 splash 模組化（高風險，配手動清單細測），再遙控各頁。
4. 每步 pytest + 手動驗證。
5. **先處理 staging 數首歌 seed 出測試庫**，讓評分/推薦/大歌庫清單表現有資料可驗。

---

## 13. 風險與接受的取捨
- **接受**：控制端點未授權（家用 LAN/信任環境）。
- 歌庫近空（1 首完整、13 首待處理）→ 評分/推薦/規模化必須 seed 後才能驗。
- `splash.js` 拆解為最高風險項 → 配手動測試清單謹慎進行，行為保持不變。
- `pyproject.toml` 作者/版本仍為上游殘留（非本案範圍，僅記錄）。

---

## 14. 後續（本設計核准後）
- 進入 writing-plans，產出分階段實作計畫（對應第 12 節順序）。
- 第一階段建議：前置清理 + `core/` 就位（低風險、立即降低後續所有工作的耦合）。
