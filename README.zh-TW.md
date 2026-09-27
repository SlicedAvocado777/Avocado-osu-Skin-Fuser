[English](README.md) | **繁體中文**

# Avocado-osu-Skin-Fuser

一個無需外部套件、在終端機裡運作的工具，用「別的 skin」來組出 osu! skin。

給它兩個 skin，它可以保留其中一個的**遊戲性**部分（打擊圈、滑條、游標、打擊火花…），而採用另一個的**美術**（選單、結算畫面、背景…）。或者使用 **All-in-One**，把 osu!standard / mania / taiko / catch 的 skin 縫合成一個，讓每個模式都像它自己的來源 skin。

整個程式都在終端機裡運作，外觀仿造經典的 **Windows 3.1 Setup**。

![歡迎畫面](Screenshots/Screenshot_20260927_205629.png)

## 功能

- **兩種融合模式**
  - *Gameplay + Art* — 手感來自一個 skin，外觀來自另一個。
  - *All-in-One* — 把 2 個以上的模式合併成一個 skin，可另外指定一個 Art skin 與獨立的介面音效來源。
- **逐項圖片微調** — 為每個精靈圖選擇來源 skin，清單可搜尋。
- **逐項音效微調** — 打擊音、模式音效、介面/UI 音效各自獨立處理。
- **skin.ini 控制** — 智慧合併、全部取自某個 skin，或逐一調整每個鍵值。
- **匯出資訊** — 設定 skin 的名稱 / 作者 / 版本（可繼承來源或自訂），並選擇要寫出什麼。
- **可搜尋的 skin 選擇器** — 掃描一次資料夾後，之後每個選擇器都會記住該目錄。
- **Windows Setup 風格的 TUI** — 方框清單、灰色對話框、紅色離開確認框、反色說明頁，以及複製檔案的進度條。
- **命令列模式** — 以上功能都能以非互動方式腳本化。

## 兩種建立 skin 的方式

在第二個頁面按 **ENTER** 選擇 *Gameplay + Art*，或按 **C** 選擇 *All-in-One*。

![Setup 方式](Screenshots/Screenshot_20260927_205703.png)

### Gameplay + Art

- **Gameplay（手感）** 提供打擊圈、滑條、轉盤、游標、打擊火花、打擊數字等。
- **Art（外觀）** 提供選單、結算畫面、背景、按鈕以及其他共用的美術。

之後你還可以覆寫任何單一元素或音效。

### All-in-One

把 osu!standard / mania / taiko / catch 中至少兩個合併。用 **SPACE** 切換模式，**ENTER** 確認。

![All-in-One 模式](Screenshots/Screenshot_20260927_205755.png)

接著為每個選定的模式挑一個來源 skin（也可以另外指定每個模式的音效來源）。模式專屬的資源來自該模式的 skin，共用的遊戲打擊音來自基準模式，而全域的選單 / UI 音效則跟隨你指定的一個介面來源 —— 若該來源沒有某個 UI 音效，就直接留空，讓 osu! 使用自己的預設，而不是從其他 skin 借過來。

## 選擇來源 skin

skin 選擇器會列出找到的每個 skin，並顯示各自的檔案數量。用 **/** 搜尋，或選 *「Enter your osu skin directory path…」* 掃描資料夾 —— 之後每個選擇器都會待在同一個目錄。

![skin 選擇器](Screenshots/Screenshot_20260927_205852.png)

## 微調

選好來源後，可以微調圖片、音效與 skin.ini：

- 每個清單會列出所有項目，以及目前來自哪個來源。
- 在某列按 **ENTER** 會開啟小對話框，選擇新的來源/值。
- 按 **/** 搜尋，**G** / **End** 跳到最後一列。
- 每個清單最後都有一列 **Done** 用來結束。

## 匯出資訊

最後一頁的排版仿造 Windows Setup 的 *System Information* 畫面。用 **UP/DOWN** 移動，按 **ENTER** 修改項目。

![匯出資訊](Screenshots/Screenshot_20260927_205912.png)

可設定：

| 項目 | 說明 |
| --- | --- |
| Skin name | 匯出 skin 的名稱（可繼承來源名稱或自行輸入） |
| Author | 寫入 `skin.ini` 的作者 |
| skin.ini Version | 寫入 `skin.ini` 的版本字串 |
| Output folder | 輸出位置 |
| Export as | `.osk only`（預設）、`Folder only` 或 `.osk + Folder` |

確認無誤後，移到 **No Changes: The above list matches my choice.** 按 **ENTER**，Setup 就會立刻開始複製。

## 匯出

匯出會在 TUI 內以 Windows Setup 的 *「Setup is copying files…」* 畫面進行，附進度條，右下角顯示目前正在複製的檔案。按 **F3** 可中止。

![匯出進度](Screenshots/Screenshot_20260927_205936.png)

完成後會顯示摘要頁；按 **ENTER** 離開，或按 **R** 直接再建立另一個 skin（不必重新啟動）。

## 需求

- **Python 3.8+**
- **僅使用標準函式庫** —— 不需要 `pip install`。
- 需要支援 `curses` 的終端機：
  - **Linux / macOS**：直接可用。
  - **Windows**：內建沒有 `curses`，請先執行 `pip install windows-curses`（建議搭配 Windows Terminal 等支援 256 色的終端機）。

## 執行

```bash
# 在此資料夾
python3 osu_skin_fuser_3.20c.py

# （可選）改成慣用檔名
mv osu_skin_fuser_3.20c.py osu_skin_fuser.py
python3 osu_skin_fuser.py
```

## 按鍵

| 按鍵 | 動作 |
| --- | --- |
| `UP` / `DOWN`（或 `K` / `J`） | 移動選取 |
| `HOME` / `END`（或 `G`） | 跳到第一 / 最後一項 |
| `PAGE UP` / `PAGE DOWN` | 移動十項 |
| `ENTER` | 啟用反白項目 |
| `SPACE` | 設定清單中等同 ENTER；多選時切換項目 |
| `/` | 在清單中搜尋 |
| `ESC` 或 `q` | 回到上一步 |
| `F1` | 開啟（反色的）Setup 說明頁 |
| `F3` | 離開 Setup —— 在確認框中再按一次 `F3` 才會真正離開 |
| `F5` | 切換彩色 / 單色 |

## 命令列

若未提供 `--gameplay`/`--art`/`--mode-skin`，會啟動互動式 TUI。也可以非互動方式使用：

```bash
# 雙 skin 融合
python3 osu_skin_fuser.py --gameplay SkinA --art SkinB --name "My Mix" \
    --output ./FusedSkins

# All-in-One 模式融合
python3 osu_skin_fuser.py --all-in-one \
    --mode-skin standard=StdSkin --mode-skin mania=ManiaSkin \
    --mode-skin taiko=TaikoSkin --name "All-in-One"
```

常用參數：

| 參數 | 說明 |
| --- | --- |
| `--list` | 列出找到的 skin 後結束 |
| `--dry-run` | 只印出計畫，不寫入任何檔案 |
| `--output DIR` | 輸出資料夾（預設 `FusedSkins`） |
| `--export-mode {osk,folder,both}` | 要寫出什麼（預設 `osk`） |
| `--image-source {mixed,gameplay,art}` | 圖片來源 |
| `--sounds {…}` | 音效預設 |
| `--ini {smart,gameplay,art}` | skin.ini 基準 |
| `--name` / `--author` / `--skin-version` | 覆寫匯出資訊 |

完整清單請執行 `python3 osu_skin_fuser.py --help`。

## 大致運作方式

- 圖片會依檔名分類為 *遊戲性* 素材（`hitcircle*`、`slider*`、`cursor*`…）與 *美術*（`menu-*`、`ranking-*`、背景…）。
- 音效會分類為打擊音、模式專屬音效與介面/UI 音效。
- `skin.ini` 會以所有來源的區段與鍵值聯集合併（`[General]`、`[Colours]`、`[Fonts]`、`[Mania]`、`[CatchTheBeat]`），並可逐鍵選擇來源。若選定的來源沒有某個鍵值，就省略它，讓 osu! 使用自己的預設。

## 備註

這是一個非官方的個人粉絲工具，與 osu! 或 ppy 無關。請務必備份你的 skin —— 本工具只會寫出新的 skin，不會就地修改你的來源。
