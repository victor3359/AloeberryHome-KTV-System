# KTV 客廳可用性鑑識 + 完整計畫（AloeberryHome KTV System）

- **日期：** 2026-07-19
- **分支：** `refactor/ktv-frontend`（HEAD `dc1761f`，已推上 origin 備份）
- **方法：** 對 `origin/main...HEAD`（98 commits）做 max-effort code review — 11 個平行 finder（後端逐行、前端逐行、移除行為、跨檔追蹤、語言陷阱、包裝層、重用、簡化、效率、高度、CLAUDE.md 規範）+ 控制者親自逐檔驗證真實原始碼。
- **目標函數：** 不是「重構乾淨」，而是「**一群人在客廳，用一台電視 + 幾支手機，整晚順暢歡唱**」。以下所有分級與排序都以此為準。
- **鑑識基準：** 848 tests 全綠、pylint gate 綠。但測試全是 Python 字串斷言 + mock，**沒有任何 JS runtime 測試、從未在真實 TV + 多手機端到端驗證**。本次發現的多數 P0/P1 只要在真電視上按一次、用手機掃一次 QR 就會現形——這正是測試綠燈卻仍會毀掉客廳體驗的根因。

______________________________________________________________________

## 1. 分級發現（去重後 ~33 個獨立機制，附 file:line、觸發情境、修向）

嚴重度以「對客廳當晚歡樂的破壞力」排序，非以技術新奇度。

### P0 — 會當場毀掉整晚（BLOCKER，最高優先）

| # | 機制 | 位置 | 觸發 → 後果 | 修向 |
|---|---|---|---|---|
| P0-1 | **升降 Key 後全靜音** | `static/js/splash.js:811` vs `:150-153`/`:364-367` | `createMediaElementSource(#video)` 捕獲持久 video 元素；換歌/endSong 卻 `ctx.close()`。Web Audio 語意下元素一旦被捕獲永久路由該 graph、close 後不還原 → 任何人用一次升降 Key，song 2 起**全部歌靜音**；再按則二次 `createMediaElementSource` 拋 `InvalidStateError` → 顯示「此瀏覽器不支援」。諷刺的是 close 清理是六月「防記憶體洩漏」修正引入的。 | pitch-shift ctx **跨歌持久化**：建立一次、換歌只 reset `pitchSemitones` param（0 = 原音），永不 close（頁面關閉才釋放）。天然吸收原路線圖 slice 8。 |
| P0-2 | **手機遙控主入口硬載入整頁崩潰** | `templates/queueview.html:315`；`base.html:19-24` | `window.nowPlayingStore` 由 `<script type="module">`（隱含 deferred）賦值；queueview:315 的 `nowPlayingStore.subscribe` 在 **top-level classic script**，parse 時即執行 → 早於 module → `undefined.subscribe` **TypeError** → 中止整段腳本：socket listeners、state reset、`$(function)` 全區（初始 queue fetch、所有按鈕、mini player、control panel、鍵盤）全部不註冊。`/`→`/queue` 是手機 landing page，**掃 QR / F5 / 迷你strip 點擊都是硬載入 → 整頁死**；只有 SPA 軟導覽正常（開發時沒抓到、字串測試也測不到的原因）。 | 把 :314-317 的 top-level socket/store 綁定移進 `$(function(){})`（比照 songpicker.html），或在 module bootstrap 完成後才綁。 |
| P0-3 | **語言覆寫死碼 + 修好即 RCE** | `lib/vocal_separator.py:501`（clobber）+ `:394/:403/:414`（注入） | `process()` 開頭 `language = ""` 無條件蓋掉參數 → `/reprocess?language=en` 覆寫**完全失效**（「非中文歌誤判」唯一修復機制是死碼；路由 `scores.py:162/184` 傳遞正確，bug 100% 在 process 內部）。**更危險**：`detected_lang` 以 f-string 直接嵌入 `python -c` 原始碼、無 allowlist；今日靠 clobber 意外擋住，**天真修好 clobber 會立刻把字幕修復功能變成遠端代碼執行**。 | **同一 PR** 修：(a) 重命名 :501 本地累加器（如 `detected_language`）讓參數生效；(b) 對 language 加 2-letter ISO allowlist，非法值忽略。兩者不可分開。 |

### P1 — 高頻惹惱 / 累積劣化 / 資料污染

| # | 機制 | 位置 | 觸發 → 後果 | 修向 |
|---|---|---|---|---|
| P1-1 | **切歌洩漏 mic + 孤兒 YIN 迴圈** | `static/js/splash.js:742`/`:632`；`pitch-analyzer.js:31-34` | `PitchAnalyzer.stop()` 只 disconnect source，**從不** stop mic tracks / close ctx；socket `skip`（最常見操作）只 pause、不呼叫 endSong → 舊 rAF（`running` 仍 true）續跑、下一首 :429 又建新 analyzer。3 小時累積 N 組熱麥克風 + 60fps YIN 迴圈 → CPU 飽和、影格掉、麥克風燈不熄。 | `stop()` 加 `tracks.forEach(t=>t.stop())` + `ctx.close()`；skip handler 呼叫清理；換歌前先停舊 analyzer。可併入原路線圖 slice 4（scoring 模組化正好碰這些檔）。 |
| P1-2 | **上一位歌手的分數記到下一位** | `static/js/splash.js:162` | endSong 只在 `totalFrames>10` 分支 reset meter；`window._pitchMeter` 只在下一首 mic init 成功時才替換。若下一首 getUserMedia 失敗（裝置忙/權限），沿用前一首帶累積 frames 的 meter → 這首 `$.post('/record_score')` 記上前一位的分數 → **排行榜污染**。 | endSong 無條件 reset/清空 meter；或 init 失敗時明確清空 `_pitchMeter`。 |
| P1-3 | **TV 背景切換回來後佇列停止前進** | `static/js/splash.js:900` | `handleSocketRecovery` 在 visibilitychange 時 `socket = io()` + `setupSocketEvents()`；socket.io v4 multiplexing 回傳同一實例、`setupSocketEvents` 無 `.off()` → **重複註冊**。'connect' 雙發 → `register_splash` 雙發 → 唯一的 TV 被伺服器判為 slave → endSong 的 `if(isMaster)` 為 false 不 emit end_song → **歌播完佇列不再自動前進**，直到重整。 | `setupSocketEvents` 綁定前先 `.off()`（幂等）；recovery 不重建 socket、依賴 socket.io 自動重連。呼應原路線圖 slice 9（sync）。**provenance 待確認**：部分邏輯可能 pre-existing on main，但客廳照樣會踩。 |
| P1-4 | **字幕整首逐行漂移（重新引入「對不上」）** | `lib/lyrics_corrector.py:25` | `_parse_lrc_line` 不論小數位數一律 `/100`：`[01:23.456]`(毫秒) 解成 87.56s 而非 83.456s（誤差 0–9.9s、逐行不同）。syncedlyrics 落到 NetEase（zh-TW 常見）回傳 3 位毫秒 LRC → 每行位移不同、median 全域校正救不回 → 六月花大力氣修的 opcode 對齊被 parse 階段的錯誤時間戳廢掉。 | 依小數位數換算：1 位×100ms、2 位×10ms、3 位×1ms；並處理無小數的 `[mm:ss]`。 |
| P1-5 | **TV 上顯示錯字/髒字** | `lib/karaoke_subtitle.py:231` | 主唱行 OpenCC s2twp **逐字**轉換（無法解上下文相依映射）：`头发→頭發`（應頭髮）、`干杯→幹杯`（髒字讀音）、`一只鸟→一只鳥`；而灰色預覽行（:317 整行轉換）顯示正確字 → 同一句彩色行與預覽行**當場不一致**。任何缺線上歌詞、走 raw 簡體 Whisper 的歌每段副歌都現形。 | 整行轉換後再切字（與預覽行同源）；並快取 converter（見 P1-6）。 |
| P1-6 | **生字幕時 TV 卡頓、遙控斷線** | `lib/lyrics_corrector.py:271`、`karaoke_subtitle.py:132/231` | 背景字幕「執行緒」實為 gevent greenlet（monkey.patch_all）；OpenCC **每字/每呼叫重建** converter（載入字典），且在 `_estimate_global_offset` 的 O(online×whisper) 巢狀迴圈內 → 數千次字典載入霸佔單一事件迴圈數秒~數分鐘 → HLS 分段請求、`/now_playing`、socket ping 全部卡住 → **正在播的那首歌畫面凍結、遙控斷線**，時間點正好對上「歌詞校對中／產生字幕」進度。 | 模組級 `functools.lru_cache` 快取 OpenCC 實例；巢狀迴圈前把 whisper 文字正規化一次；重活考慮讓出 greenlet 或移到真 thread/subprocess。 |
| P1-7 | **重跑後計分基準永遠陳舊** | `routes/scores.py:169`；`pitch_extractor.py:39` | reprocess 刪除清單只有 `_vocals/_instrumental/_karaoke.ass`，**漏 `_pitch.json`**；extract_pitch `exists→return` 短路 → 因分離爛/錯歌而重跑後，新人聲不會重新提取音高，麥克風永遠拿舊（錯的）參考旋律評分。 | reprocess 刪除清單加 `_pitch.json`（一行）。 |
| P1-8 | **失敗歌每播重跑整條管線 + 0-byte ASS 永久擋補產** | `lib/vocal_separator.py:183`/`:220`/`:195-207` | `ensure_subtitles_async` 用 `has_karaoke_ass`=`os.path.exists`（非 `_is_nonempty_file`）→ 0-byte ASS 讓背景補產永不觸發、卻永遠服務空字幕；`_subtitle_worker` finally 只 discard pending 不記失敗、`is_available` 只看 DEMUCS 不看 WHISPER → 伴奏曲/Whisper 失敗曲**每播必重跑整條 Whisper**（含 `背景產生字幕中` toast），與現場播放搶 CPU、持鎖擋新下載後製。 | `has_karaoke_ass` 改 `_is_nonempty_file`；失敗記在 `has_lyrics` 欄位或 `.failed` marker，非明確 reprocess 不再重試。 |
| P1-9 | **手機鎖屏醒來顯示早已唱完的歌** | `static/core/nowPlayingStore.js:28-36`/`:53-65` | `_wireSocket` 只綁 `now_playing`、**無 `connect` handler**；subscribe 僅在 `_state` 為 null 時 refresh。手機 socket 斷線→自動重連後不重抓 → mini player 顯示過期歌（標題/歌手/暫停態）直到下次狀態變化 broadcast（可能一整首歌之久）。splash.js:704 有正確的 connect 重抓，store 卻沒有。 | store 的 `_wireSocket` 加 `socket.on('connect', refresh)`。 |

### P1.5 — 效能（直接影響客廳流暢度）

| # | 機制 | 位置 | 後果 | 修向 |
|---|---|---|---|---|
| P1.5-1 | 純 Python YIN 音高提取每首燒數分鐘 CPU、恐撞 timeout | `lib/pitch_extractor.py:64-89` | 640×640 巢狀迴圈/frame + per-sample `struct.unpack`：4 分鐘歌數十億次解釋運算，一核心滿載數分鐘；5-6 分鐘歌可能撞 subprocess timeout → 白跑、丟失計分曲線。 | 改 numpy 向量化差分（demucs/whisper 已帶 numpy），或 `librosa.yin`；~1-2 秒完成。 |
| P1.5-2 | 客戶端 YIN 每 rAF O(n²) 燒半核 | `static/js/pitch-analyzer.js:36-63` | fftSize 4096 → 2048×2048 ≈ 420 萬乘加/frame、60fps 整首歌在 TV 主執行緒跑，與 HLS 解碼 + libass WASM 60fps 搶核。 | 降到 ~50ms timer；tau 限 80-1100Hz band；`video.paused` 早退。 |
| P1.5-3 | NaN 音高凍結音準表 | `static/js/pitch-analyzer.js:95/102` | 平坦區三點相等 → parabolic 分母 0 → `NaN`；`NaN<80||NaN>1100` 皆 false → 穿過過濾器 → meter dot 設成 `"NaN%"` 凍結、該 frame 誤判 miss。 | 分母近 0 時退回 `tauEstimate`；filter 前 `Number.isFinite` 檢查。 |

### P2 — 正確性中低 / 安全 / 收尾

- **P2-1 rename 後 DB 記錄未消毒路徑 → 幽靈列 + 播放失敗**（`lib/download_manager.py:355`）：`song_path` 用未消毒的 `corrected`，但 `rename()` 已把 `?<>:"/\|*` 換成 `-` → DB 記錯路徑、enqueue 不存在的檔 → 「Stream not playable」。
- **P2-2 /reprocess 無庫內驗證 + 無 admin gate → 任意路徑刪除**（`routes/scores.py:153`）：任何 LAN 手機可 POST 任意絕對路徑，刪其 `_vocals/_instrumental/_karaoke.ass` 並觸發 force pipeline。設計§13 接受「控制端點 LAN 未授權」，但**任意檔案刪除超出該範圍**。→ 驗證 song 在庫內。
- **P2-3 XSS / 未跳脫**（`static/js/splash.js:268` 歌名、`:789` 歌手名）：`.html()` 插入手機自由輸入的 singer name 與 YouTube 歌名；含 `<`/`&` 的中文歌名渲染破損。→ 改 `.text()` 或跳脫。
- **P2-4 stream_manager `has_multi_audio` 用 0-byte 不一致 → 歌永久無法播**（`lib/stream_manager.py:134`）：`os.path.exists` vs `has_stems` 的 `_is_nonempty_file` 分歧 → 0-byte instrumental 讓 UI 隱藏音軌鈕、stream 卻選 multi-audio 餵空檔給 ffmpeg → 永久「Skipping track」、錯誤訊息誤導。
- **P2-5 SPA 重進佇列 mini player 保持隱藏**（`templates/queueview.html:352-353`）：reset 在 subscribe 之後，replay 舊 `_state` 時 dedupe 掉 → 有歌在播卻無 mini player 可控。
- **P2-6 pitch_shift init race**（`static/js/splash.js:832`）：ctx 在 `await addModule` 前同步賦值，第二個事件穿過 guard、deref 尚為 null 的 node → 拖 slider 一次只套第一格。
- **P2-7 SPA 每次切換丟 SyntaxError**（`static/spa-navigation.js:564`）：`executeScripts` 不複製 `type=module`，importmap/module bootstrap 被當 classic 重跑 → 兩個 uncaught SyntaxError（目前 masked）。

### P3 — 架構收斂 / 清理 / 規範（不阻擋歡樂，但屬「完整計畫」的地基）

- **雙真相來源**：favorites（`song_database.py:208` SQLite 死表 vs 現役 JSON `k.favorites`）、play count（`karaoke.py:665` JSON + `:666` SQLite 雙記帳，將漂移）→ 各收斂為單一來源。
- **投機 REST 面無消費者**（`routes/scores.py:115` `/library/artists|top|recommend` + 相關查詢方法，含 `song_database.py:261` **recommendations SQL 綁定數不符、呼叫即 500 + 連線洩漏**）→ 砍到只留有 UI 消費的端點；未來接 UI 前先修 SQL。
- **入庫邏輯重複已漂移**（`download_manager.py:360` vs `song_database.py:301` 兩套 artist/title 拆分 + 縮圖 URL + stem 探測 + upsert；YouTube ID regex 只認三破折號 → **方括號 `Title [id].mp4` 檔名靜默失去縮圖**）→ 抽 `upsert_from_file` 一份，用既有兩格式解析器。
- **重複程式碼**（diff 新增）：pitch teardown ×2、off/on 幂等綁定 ×8、CJK 範圍兩處已分歧、逐字均攤計時核心 ×4、`_detect_language` 三處分歧（lib→routes 反向依賴，`download_manager` import `routes.files`）→ 各抽一份共用。
- **CLAUDE.md 規範**：9 檔新增 `from __future__ import annotations`（明文禁止）；`_song_db`/`get_pitch_data` 缺型別 + 函式內 `import os`；OpenCC `ImportError` 靜默吞掉 s2twp（「Log errors, never swallow silently」）→ 補 log。
- **文件說謊**（`karaoke_subtitle.py:186`）：credit-line 過濾只剩上游 `_search_online_lyrics` 一處，但 aligned 路徑的 docstring/註解宣稱會過濾 → 未來加第二歌詞源會讓「作詞/作曲」被當歌詞唱出。
- **legacy 路由無 redirect**（`routes/files.py`）：`/browse_legacy`/`/search_legacy` 刪除無 stub → 舊書籤 404（單戶低影響）。

______________________________________________________________________

## 2. 完整計畫 — 以「客廳歡樂」重新定序（全程系統可跑）

**核心判斷：** 原 ledger 路線圖主線是「splash.js 結構模組化 slice 4-9」（工程整潔目標）。但真正毀掉歡樂的是上面的 P0/P1 runtime bug，它們**優先於**繼續重構。因此重新定序如下——重構不取消，而是讓地基先穩、並把相關修復併入對應 slice。

### 階段 0 — 真實客廳端到端煙霧測試（½ 天，先做）

在真 TV 開 splash + 2-3 支手機，走完整一輪：掃 QR 進遙控 → 點歌 → 播放 → 原唱/伴奏切換 → **升降 Key** → **切歌** → 計分 → 開新場次。目的：親眼確認 P0-1/P0-2 會現形，並抓任何 review 沒涵蓋的真實問題。這一步補上 ledger 一直缺的「USER eyeball on real TV」gate，把整個計畫錨定在真實觀察上。**產出：** 一份現場問題清單，校準以下階段。

### 階段 1 — P0 止血（1-2 天）

修 P0-1（pitch-shift 持久 ctx）、P0-2（queueview 綁定移進 ready）、P0-3（language 生效 + allowlist 同 PR）。每項 TDD + **真 TV 複驗**。此後「升降 Key / 掃 QR / 語言修復」三個核心互動不再毀整晚。

### 階段 2 — P1 穩定與品質（2-4 天）

P1-1~P1-9：mic 洩漏、meter carryover、socket 幂等、LRC 毫秒、OpenCC 整行+快取、reprocess 刪 pitch、0-byte/失敗記憶、store reconnect。字幕對得上、分數記得準、整晚穩定。

### 階段 3 — P1.5 效能（2-3 天）

pitch_extractor 改 numpy、客戶端 YIN 降頻 + NaN 防護、背景字幕不霸佔事件迴圈。機器不再被自己拖垮。

### 階段 4 — P2 正確性 + 安全收尾（1-2 天）

rename 消毒、/reprocess 庫內驗證、XSS escape、stream_manager 一致、SPA mini player、init race、spa-navigation type。

### 階段 5 — 回歸原路線圖：splash slice 4-9 + 架構收斂（既有計畫，重估邊界）

此時多數 slice 目標檔已在階段 1-4 被碰過修好（slice 4 scoring↔P1-1、slice 8 pitch-shift↔P0-1、slice 9 sync↔P1-3），**slice 邊界需重新評估、可合併**。同步做 P3 收斂：favorites/play-count 單一真相、砍投機 REST、入庫抽一份、language 偵測收斂、CLAUDE.md 合規。

**貫穿全程：** 每階段結束都在真 TV + 手機複驗；維持 848+ 測試全綠 + pylint gate；每個修復 TDD、獨立 commit、可個別 review。

______________________________________________________________________

## 3. 風險與取捨

- **接受**：控制端點 LAN 未授權（設計§13，家用信任環境）——但 P2-2 任意檔案刪除超出此範圍，須修。
- **P0-3 的耦合是本次最重要的單點洞察**：修語言覆寫與堵 RCE 必須同一 PR，否則「修好功能」= 開後門。
- 階段 0 若在真 TV 發現 review 未涵蓋的問題，插入對應階段，不硬跑既定順序。
- provenance 待確認項（P1-3 部分）：即使 pre-existing on main，客廳照樣會踩，仍納入修復範圍。
