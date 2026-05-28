# licmgr — 離線授權管理工具

> **套件名稱**：`licmgr`　**GitHub**：[HANK572718/simple_license_manager](https://github.com/HANK572718/simple_license_manager)  
> **授權**：Apache 2.0　**平台**：Windows · Linux · macOS

私鑰永不離開開發機的軟體授權系統。透過互動式 TUI 或 Poetry plugin 命令管理專案、金鑰與客戶授權。

---

## 前置需求

使用 licmgr 前，必須先安裝 **Poetry 1.8 以上**：

```bash
# 尚未安裝 Poetry 時執行
curl -sSL https://install.python-poetry.org | python3 -
```

確認安裝：

```bash
poetry --version   # 應顯示 Poetry (version 1.8.x) 以上
```

---

## 安裝（二擇一）

### 方式 A — 直接從 Git URL 安裝（推薦，無需 clone）

```bash
poetry self add git+https://github.com/HANK572718/simple_license_manager.git
```

### 方式 B — Clone 後安裝本機路徑

```bash
git clone https://github.com/HANK572718/simple_license_manager.git
poetry self add ./simple_license_manager
```

> ⚠️ **Windows 跨磁碟注意**：若 Poetry 安裝在 C: 而專案在 D:，`poetry self add ./local_path` 可能無法正確登錄套件，請改用方式 A（Git URL）。

### 安裝疑難排解 — Debian/Ubuntu：`poetry self add` 卡 greenlet 標頭檔權限

在 **Debian/Ubuntu 系列**（含 NVIDIA Jetson / JetPack）以官方安裝器裝 Poetry 後，`poetry self add`（方式 A 與 B 皆會）可能失敗：

```
PermissionError: [Errno 13] Permission denied: '/usr/include/python3.10/greenlet'
  ...poetry/installation/wheel_installer.py ... parent_folder.mkdir(...)
Cannot install greenlet.
```

**這不是 licmgr 的 bug，也與 aarch64 相容性／編譯無關**（同一顆 greenlet wheel 在一般專案 venv `poetry install` 裝得起來）。根因是 **Debian/Ubuntu 的 sysconfig 回歸 bug**：Poetry 官方安裝器的 self-venv（`~/.local/share/pypoetry/venv`）裡 `sysconfig.get_path('include')` 仍回報 root 擁有的 `/usr/include/python3.10`，而 licmgr 依賴 SQLAlchemy → 連帶拉入 greenlet，其 wheel 要把 C 標頭檔 `greenlet.h` 寫進那個 root 目錄 → 權限被拒。

**解法（推薦，範圍最小、可還原、不污染 Poetry 環境）**：先把標頭檔目標目錄建好並改為自己擁有，再用**不加 sudo** 的 `poetry self add`：

```bash
sudo mkdir -p /usr/include/python3.10/greenlet
sudo chown "$(id -un)":"$(id -gn)" /usr/include/python3.10/greenlet
poetry self add git+https://github.com/HANK572718/simple_license_manager.git   # 注意：不加 sudo
```

如此 `greenlet.h` 寫進這個「現在可寫」的目錄，其餘套件全部以使用者身分裝進 user-owned 的 self-venv。還原：`sudo rm -rf /usr/include/python3.10/greenlet`。

> ⚠️ **不要用 `sudo poetry self add`**：sudo 以 `HOME=/root`、root 身分執行，會在你的 Poetry self-venv 留下 **root 擁有的檔案**並使 self 狀態分裂，導致日後（非 sudo 的）`poetry self update / remove` 權限錯誤。社群（poetry#612、#3596）亦明確勸退以 root 安裝。

> 💡 此為「本機」workaround；換一台 Debian/Ubuntu 機器需重做相同步驟。若需「推一次、到處都能乾淨安裝」，可考慮在 licmgr 端改用標準庫 `sqlite3` 取代 SQLAlchemy 以移除 greenlet 依賴。
>
> 參考：[poetry#7454](https://github.com/python-poetry/poetry/issues/7454)、[Debian #1007966](https://www.mail-archive.com/debian-bugs-dist@lists.debian.org/msg1847578.html)、[bugs.python.org #36383](https://bugs.python.org/issue36383)、[Ubuntu #1940705](https://bugs.launchpad.net/ubuntu/+source/python3.10/+bug/1940705)

---

## 核心概念：金鑰與授權的關係

```
專案  (1)
 └── 金鑰對 (1)          ← 一個專案持有一把 RSA-2048 金鑰對
      ├── 私鑰            → 存於 ~/.licmgr/，只在你的開發機，用來「簽發」授權
      └── 公鑰            → 嵌入 SDK，交給所有客戶，用來「驗證」授權真偽
           │
           ├── 授權 #1    → 客戶 A 的機器（指紋 aaaa...）
           ├── 授權 #2    → 客戶 B 的機器（指紋 bbbb...）
           └── 授權 #3    → 客戶 A 的第二台機器（指紋 cccc...）
```

- **金鑰對只需產生一次**，之後可以一直用它為新客戶簽發授權
- **每張授權綁定一個機器指紋**，搬到其他機器即自動失效
- **公鑰可以安全公開**，無法用來偽造授權（只有私鑰能簽章）

---

## 快速開始：互動式 TUI

安裝完成後，在任意專案目錄執行：

```bash
licmgr
```

啟動後會**先顯示一張即時總覽表**（見下），然後出現帶箭頭選擇的互動式主選單：

```
╭─ licmgr — 離線授權管理工具 ──────╮
│  RSA-2048 + SQLite  |  Apache 2.0  │
╰────────────────────────────────────╯

╭─ licmgr 總覽 ────────────────────────────────────────────────────╮
│ 專案數: 2   金鑰數: 2 (可用 2 / 退役 0)   授權數: 5 (有效 5 / 撤銷 0) │
╰────────────────────────────────────────────────────────────────╯

┌──────────────────────┬──────────────────────┬───────┬──────┬────────┬────────────────┬───────┬────────────┐
│ 專案                 │ 名稱                 │ 版本  │ 金鑰 │ 私鑰檔 │ 公鑰指紋(前16) │ 授權  │ 建立日     │
├──────────────────────┼──────────────────────┼───────┼──────┼────────┼────────────────┼───────┼────────────┤
│ GIT_SmartSOPGuardian │ GIT_SmartSOPGuardian │ 1.0.0 │ v1   │ ✓ 存在 │ a1b2c3d4...    │ 4 (4/0)│ 2026-05-20 │
│ TEST_CLI             │ CLI Test Project     │ 1.0.0 │ v1   │ ✗ 遺失 │ 9f8e7d6c...    │ 1 (1/0)│ 2026-05-25 │
└──────────────────────┴──────────────────────┴───────┴──────┴────────┴────────────────┴───────┴────────────┘

? 主選單
  > 📁  專案管理      — 建立 / 列出專案
    🔑  金鑰管理      — 產生 RSA 金鑰對（一個專案一把）
    📄  授權管理      — 簽發 / 撤銷 / 匯出授權（一台機器一份）
    📦  SDK 匯出      — 匯出含公鑰的驗證整合包
    📥  匯入舊資料庫  — 從舊 licmgr DB 匯入紀錄
    🔁  DB 維運        — 檢查 / 修復金鑰路徑、選擇性匯出、🗑 刪除（專案 / 金鑰 / 授權）
    ⚙   設定          — 修改路徑設定
    ❓  說明          — 功能介紹與概念說明
    🚪  離開
```

用 **↑↓ 方向鍵** 選擇，**Enter** 確認，所有操作均有引導提示。

### 🔎 進入即顯示的總覽

每次啟動 `licmgr`（或 `poetry licmgr`）都會自動印出上面那張總覽表，從子選單返回主選單時也會重畫。內容刻意精簡（**不顯示金鑰內容**），重點包含：

| 欄位 | 來源 | 用途 |
|------|------|------|
| 專案 / 名稱 / 版本 / 建立日 | `projects` 表 | 識別專案 |
| 金鑰 | active key 版本 + 總筆數 | 一眼掌握目前用哪把金鑰 |
| **私鑰檔** ✓ 存在 / ✗ 遺失 | 對 `keys.private_key_path` 做 `Path.is_file()` 檢查 | **DB 紀錄路徑與磁碟實際狀況不一致時立即發現**（最常見：路徑被搬走、檔案被刪、誤連到別台機器的舊路徑） |
| 公鑰指紋(前16) | `keys.public_key_fp[:16]` | 比對你手上的 `.lic` / `verify_license.py` 是否來自同一把 |
| 授權 | `len(licenses) (有效/撤銷)` | 看出哪些專案還活著 |

`✗ 遺失` 出現時，可進「🔁 DB 維運 → 修復金鑰路徑」用 auto-relink 自動修。

### 初次使用流程（約 2 分鐘）

```
1. licmgr → 📁 專案管理 → 新增專案
   輸入：專案 ID、名稱、環境前綴

2. licmgr → 🔑 金鑰管理 → 選擇專案 → 產生新金鑰對
   RSA-2048 金鑰對自動存入 ~/.licmgr/

3. licmgr → 📄 授權管理 → 選擇專案 → 簽發新授權
   貼上客戶指紋 → .lic 檔自動存入 ./projects/<id>/licenses/
```

### 設定儲存路徑

```
licmgr → ⚙ 設定
```

可在 TUI 內直接修改並儲存 DB 路徑、金鑰目錄、授權檔目錄，設定寫入當前目錄的 `licmgr.toml`。

### 🗑 DB 維運 → 刪除維運（分層刪除 + 回收區）

在「🔁 DB 維運」底下提供分層刪除：

| 動作 | DB 行為 | 檔案處置 | 確認機制 | 可逆? |
|------|---------|----------|----------|-------|
| **刪除授權紀錄**（License） | 硬刪 row（不同於 revoke 軟標記） | `.lic` 搬到回收區 | 一次 y/n | 從回收區手動還原檔；DB row 不可還原 |
| **退役金鑰版本**（Key） | `retired_at` 設為 now | **不動檔案** | 一次 y/n | ✓ 直接把 `retired_at` 改回 None |
| **刪除金鑰版本**（Key） | 硬刪 Key + cascade 硬刪所有引用該版本的 License（含已撤銷者） | `.pem` / `.lic` 搬到回收區 | 一次 y/n（會顯示連動影響數量） | 同上 |
| **刪除專案**（Project） | 硬刪 Project + ORM cascade 連帶刪除所有 Keys / Licenses | 整個專案的 `.pem` / `.lic` 搬到回收區 | **必須完整鍵入 project_id** | 同上 |

**回收區**：所有刪除的檔案會搬到 `~/.licmgr/.trash/YYYYMMDD-HHMMSS-<label>-<rand>/`，保留原來最後三層的目錄結構，方便 `mv` 還原。`~/.licmgr/` 本來就不在任何 git repo 內，所以回收區絕不會被 commit。

> ⚠️ 「刪除金鑰」是 **cascade 硬刪**：會把該 key 簽過的所有 license 一併硬刪，包含已撤銷的。若只是想換金鑰但保留歷史紀錄，請改用「**退役金鑰版本**」(可逆、不刪檔)。

非互動 CLI 用同樣的 CRUD（見下節「Poetry Plugin 非互動命令」）。

---

## 預設儲存路徑

| 資料類型 | 預設路徑 | 說明 |
|---------|---------|------|
| 資料庫（DB） | `~/.licmgr/registry.db` | SQLite，記錄所有專案／金鑰／授權 |
| 私鑰 | `~/.licmgr/projects/<id>/keys/private_key_vN.pem` | 僅擁有者可讀（chmod 600） |
| 公鑰 | `~/.licmgr/projects/<id>/keys/public_key_vN.pem` | 可安全公開 |
| `.lic` 授權檔 | `<CWD>/projects/<id>/licenses/<client>.lic` | 交付給客戶，不含私密資訊 |

```
~/.licmgr/                        ← 安全資料根目錄（不在 git repo 內）
├── registry.db                   ← 授權登錄資料庫
└── projects/
    └── MY_PROJ/
        └── keys/
            ├── private_key_v1.pem   # 私鑰（絕對不要 commit）
            └── public_key_v1.pem    # 公鑰（可公開）

<CWD>/projects/                   ← 授權檔輸出目錄（與工作目錄綁定）
└── MY_PROJ/
    └── licenses/
        └── Acme_Corp.lic          # 交付給客戶的授權檔
```

`~/.licmgr/` 特性：
- 不在任何 git repo 內 — 永遠不會被 commit
- 移除 plugin（`poetry self remove licmgr`）不影響此目錄
- 跨專案共用，專案目錄搬移不影響資料

---

## 設定檔（licmgr.toml）

在工作目錄建立 `licmgr.toml` 可覆蓋所有預設路徑（也可透過 TUI ⚙ 設定自動寫入）：

```toml
[database]
# SQLite 相對路徑（相對於 licmgr.toml 所在目錄）
url = "sqlite:///db/registry.db"
# 或絕對路徑：
# url = "sqlite:////home/user/.licmgr/registry.db"

[storage]
# 金鑰根目錄（留空 = ~/.licmgr/projects/）
keys_dir = ""
# 授權檔輸出根目錄（留空 = <CWD>/projects/）
licenses_dir = ""
```

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `database.url` | SQLAlchemy DB URL | `sqlite:///<~/.licmgr/registry.db>` |
| `storage.keys_dir` | 金鑰根目錄（絕對路徑） | `~/.licmgr/projects/` |
| `storage.licenses_dir` | 授權檔輸出根目錄 | `<CWD>/projects/` |

---

## Poetry Plugin 非互動命令（CI/CD 用）

安裝後也可用 `poetry licmgr` 執行非互動命令，適合 CI/CD 腳本：

```bash
# 建立與簽發
poetry licmgr project create MY_PROJ "My Project" MYPROJ
poetry licmgr key generate MY_PROJ
poetry licmgr license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
poetry licmgr license list MY_PROJ
poetry licmgr sdk export MY_PROJ --output ./dist/MY_PROJ

# 撤銷與刪除（檔案均搬到 ~/.licmgr/.trash/；--yes 跳過互動確認，給 CI/CD 用）
poetry licmgr license revoke <license_id>           # 軟刪（保留 row，標記 revoked）
poetry licmgr license delete <license_id> --yes     # 硬刪 row + 搬 .lic 到回收區
poetry licmgr key retire MY_PROJ 1                  # 軟退役金鑰 v1（可逆，不刪檔）
poetry licmgr key delete  MY_PROJ 1 --yes           # cascade 硬刪 key v1 + 其下所有 license
poetry licmgr project delete MY_PROJ --yes          # 核彈級：cascade 刪整個專案 + 所有檔案搬回收區
```

典型 GitHub Actions 用法：

```yaml
- name: Issue license
  run: |
    poetry licmgr license issue $PROJECT_ID $FINGERPRINT \
      --client "$CLIENT_NAME" \
      --expires "$EXPIRY_DATE" \
      --output artifacts/license.lic
```

---

## 每次發授權的流程

### 每次發授權的流程

**① 甲方機器：取得指紋**

在甲方機器上執行（只需要 Python，無需安裝任何套件）：

```bash
python client_sdk/get_fingerprint.py
```

複製印出的 64 字元指紋，透過訊息或 email 傳給你自己。

---

**② 你的開發機：簽發授權**

**TUI 方式（推薦）：**
```bash
licmgr
# → 📄 授權管理 → 選擇專案 → 簽發新授權 → 貼上指紋
```

**.lic 檔自動儲存到** `./projects/<id>/licenses/<客戶名>.lic`

**指令方式（CI/CD）：**
```bash
poetry licmgr license issue MY_PROJ <指紋> --client "Acme Corp" --expires 2027-12-31
```

將 `.lic` 檔傳給甲方。

---

**③ 甲方機器：存檔並啟動**

將收到的 JSON 存成 `license.lic`，設定環境變數後啟動程式：

```bash
# Linux / macOS
export NHAD_LICENSE_FILE=/path/to/license.lic

# Windows PowerShell
$env:NHAD_LICENSE_FILE = "C:\path\to\license.lic"
```

---

### 工具一覽

| 腳本 | 在哪執行 | 用途 |
|------|---------|------|
| `tools/main.py` | **開發機**（每次使用） | Master CLI：專案 / 金鑰 / 授權管理 |
| `tools/generate_keys.py` | 開發機（只做一次） | 直接產生單組 RSA 金鑰對 |
| `client_sdk/get_fingerprint.py` | **甲方機器** | 採集硬體指紋，無需任何套件 |
| `client_sdk/verify_license.py` | 甲方機器（整合進程式） | 三道關卡驗證授權 |
| `client_sdk/bootstrap.py` | 開發機模擬 / 客戶部署精靈 | 雙模式：測試管線或引導客戶安裝 |
| `tools/sign_license.py` | **開發機** | CLI 直接簽章（不用 DB） |

---

## 目錄

1. [核心設計理念](#1-核心設計理念)
2. [密碼學原理](#2-密碼學原理)
3. [機器指紋：產生方式與依賴來源](#3-機器指紋產生方式與依賴來源)
4. [跨平台支援分析](#4-跨平台支援分析)
5. [虛擬機與容器環境的適用性](#5-虛擬機與容器環境的適用性)
6. [專案結構](#6-專案結構)
7. [環境需求與安裝](#7-環境需求與安裝)
8. [操作流程](#8-操作流程)
9. [授權驗證實作範例](#9-授權驗證實作範例)
10. [安全性總覽](#10-安全性總覽)
11. [常見問題](#11-常見問題)
12. [本機模擬練習](#12-本機模擬練習)

---

## 1. 核心設計理念

### 傳統做法的問題

傳統「帶私鑰到甲方」的做法有以下風險：

```
傳統做法（有問題）
─────────────────────────────────────────
開發機                      甲方機器
  │                            │
  ├─ private_key.pem ────────→ ├─ private_key.pem  ← 私鑰洩漏風險
  │                            ├─ get_fingerprint()
  │                            ├─ sign_license()
  │                            └─ license.lic
```

私鑰一旦傳出，就失去控制：甲方可以用它為任意機器偽造授權。

### 本工具的解法：職責分離

將「採集指紋」和「產生授權」拆成兩支獨立腳本，私鑰的計算全程留在開發機：

```
本工具做法（安全）
──────────────────────────────────────────────────────────────
甲方機器（無私鑰）                  你的開發機（私鑰永遠在這）
─────────────────────               ─────────────────────────
① 執行 get_fingerprint.py
  → 印出機器指紋字串

② 複製指紋
  傳給你（訊息/email）  ──────────→ ③ 執行 sign_license.py <指紋>
                                       → 印出 license.lic 的內容

                        ←────────── ④ 你複製 license.lic 內容
                                       傳回給甲方

⑤ 甲方存成 license.lic
   設定環境變數，啟動程式 ✓
```

傳輸過程中流動的只有**指紋**（公開安全）和 **JSON 授權檔**（偽造需要私鑰），兩者都不是秘密本身。

---

## 2. 密碼學原理

### 使用的算法

```
RSA-2048  +  PKCS#1 v1.5 padding  +  SHA-256 hash
```

| 元件 | 用途 |
|------|------|
| RSA-2048 | 非對稱加密，公鑰可驗證、私鑰才能簽章 |
| PKCS#1 v1.5 | 簽章填充方案，為 RSA 簽章的標準格式 |
| SHA-256 | 對簽章資料做雜湊，確保完整性 |

### 簽章流程（開發機端）

```
                    ┌─────────────────────────────────┐
                    │  payload = fingerprint           │
                    │  （若有到期日：                  │
                    │    payload = fp|expires:date）   │
                    └────────────┬────────────────────┘
                                 │
                          SHA-256 雜湊
                                 │
                          RSA 私鑰簽章
                                 │
                         Base64 編碼輸出
                                 │
                    ┌────────────▼────────────────────┐
                    │  license.lic（JSON）             │
                    │  {                               │
                    │    "fingerprint": "cd668...",    │
                    │    "signature":   "RcJz7...",    │
                    │    "expires":     "2027-12-31"   │
                    │  }                               │
                    └─────────────────────────────────┘
```

### 驗證流程（甲方機器端）

```
  讀取 license.lic
         │
         ├─→ 重新計算本機指紋 ──→ 比對 fingerprint 欄位是否吻合
         │
         └─→ Base64 解碼 signature
                   │
             RSA 公鑰驗簽（verify）
                   │
             ✓ 通過：fingerprint 確實由私鑰簽章，授權合法
             ✗ 失敗：簽章不符，授權無效或被竄改
```

### 為什麼指紋用明文存放？

`fingerprint` 欄位是明文，這是刻意的設計：

- 指紋本身是 SHA-256 雜湊，無法反推原始硬體資訊
- 驗證時需要比對「現場計算的指紋」與「授權檔的指紋」是否相同
- 真正的保護來自**簽章**，沒有私鑰就無法偽造一份通過驗證的授權

---

## 3. 機器指紋：產生方式與依賴來源

### 指紋產生流程

```python
# 虛擬碼，完整實作見 client_sdk/get_fingerprint.py

parts = []
parts.append(f"wguid:{MachineGuid}")      # 僅 Windows
parts.append(f"mid:{machine-id}")         # 僅 Linux
parts.append(f"ioplatform:{PlatformUUID}")# 僅 macOS
parts.append(f"biosuuid:{BIOS_UUID}")     # 所有平台（需 root/Admin）

raw = "|".join(sorted(parts))             # 排序後拼接，確保順序一致
fingerprint = sha256(raw).hexdigest()     # 64 個 hex 字元
```

MAC 位址**刻意排除**在指紋之外（只作為審計紀錄），
避免 NIC 更換或 VM 重建後授權失效。

### 各識別碼詳細說明

#### Windows MachineGuid（`winreg`）

- **來源**：`HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography\MachineGuid`
- **穩定性**：★★★★☆
- **何時改變**：重新安裝 Windows、sysprep

#### Linux machine-id（`/etc/machine-id`）

- **穩定性**：★★★★☆
- **何時改變**：重新安裝 Linux、clone VM 後手動重置

#### macOS IOPlatformUUID（`ioreg`）

- **穩定性**：★★★★★
- **何時改變**：更換主機板、全新安裝 macOS

### 指紋穩定性總結

| 操作 | MachineGuid（Win） | machine-id（Linux） | IOPlatformUUID（macOS） |
|------|--------------------|--------------------|------------------------|
| 一般 OS 更新 | 不變 | 不變 | 不變 |
| 重裝作業系統 | **改變** | **改變** | **改變** |
| 更換網卡 | 不變 | 不變 | 不變 |
| BIOS / 韌體更新 | 不變 | 不變 | 不變 |

---

## 4. 跨平台支援分析

### 支援矩陣

| 平台 | 可取得指紋 | 穩定性評估 |
|------|-----------|-----------|
| Windows 10/11 | ✅ | 高 |
| Ubuntu / Debian | ✅ | 高 |
| CentOS / RHEL | ✅ | 高 |
| macOS 12 Monterey+ | ✅ | 高 |
| WSL2 (Windows 內) | ⚠️ 部分 | 低 |

### Python 版本相容性

| Python 版本 | 支援 |
|-------------|------|
| 3.10 | ✅ |
| 3.11 | ✅ |
| 3.12 | ✅ |
| 3.13 | ✅ |
| 3.9 以下 | ❌ |

`get_fingerprint.py`（給甲方的版本）**只使用標準函式庫**，不需要安裝任何第三方套件。

---

## 5. 虛擬機與容器環境的適用性

### VMware / VirtualBox / Hyper-V 虛擬機

```
適用程度：⚠️ 有條件適用
```

| 情境 | 指紋是否穩定 |
|------|-------------|
| 正常開關機 | **穩定** |
| 快照還原 | **改變** |
| 複製 VM | **改變** |

### Docker 容器

```
適用程度：❌ 不建議用於容器本身
```

建議授權綁定**宿主機**，授權檔以 volume mount 掛入容器。

### Kubernetes Pod

```
適用程度：❌ 不適用（Pod 是無狀態的）
```

---

## 6. 專案結構

```
rich_deploy/
│
├── client_sdk/                ← 給甲方的工具（零依賴）
│   ├── get_fingerprint.py
│   ├── verify_license.py
│   └── bootstrap.py
│
├── tools/                     ← 開發機工具（互動式 TUI）
│   ├── db/
│   │   ├── models.py
│   │   ├── engine.py
│   │   └── crud.py
│   ├── main.py
│   ├── cmd_*.py
│   ├── sign_license.py
│   └── generate_keys.py
│
├── rich_deploy/               ← Poetry plugin / 獨立 CLI 套件
│   ├── __init__.py
│   ├── plugin.py              ← ApplicationPlugin（poetry rd ...）
│   ├── cli.py                 ← 獨立 CLI 入口（rich-deploy ...）
│   ├── commands/              ← Cleo 命令（project / key / license / sdk）
│   │   ├── project.py
│   │   ├── key.py
│   │   ├── license.py
│   │   └── sdk.py
│   ├── core/                  ← 核心邏輯（DB、簽章、金鑰生成）
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   ├── engine.py
│   │   │   └── crud.py
│   │   ├── sign_license.py
│   │   └── generate_keys.py
│   └── data/
│       └── client_sdk/        ← SDK 匯出模板
│
├── db/
│   └── registry.db            ← SQLite 主檔（.gitignore 忽略）
│
├── projects/                  ← 各專案私鑰（.gitignore 忽略私鑰）
│
├── docs/
├── rich_deploy.toml           ← 全域設定（DB URL）
├── pyproject.toml
├── LICENSE                    ← Apache 2.0
└── README.md
```

---

## 7. 環境需求與安裝

| 項目 | 版本 |
|------|------|
| Python | 3.10 以上 |
| Poetry | 1.8 以上（plugin 模式需要） |

### 安裝 Poetry（若尚未安裝）

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### 安裝專案依賴（本地開發）

```bash
poetry config virtualenvs.in-project true
poetry install
```

---

## 8. 操作流程

### 第零步：初始化金鑰（只做一次）

```bash
# 互動式
poetry run python tools/main.py
# 選 [p] 新增專案，[k] 產生金鑰

# 或直接 CLI
rich-deploy project create MY_PROJ "My Project" MYPROJ
rich-deploy key generate MY_PROJ
```

---

### 第一步：在甲方機器取得指紋

在**甲方機器**上執行（只需要 Python，無需 Poetry）：

```bash
python get_fingerprint.py
```

複製印出的 64 字元指紋。

---

### 第二步：在開發機簽章，產生授權檔

```bash
# 互動式 TUI
poetry run python tools/main.py  # [l] 簽發授權

# CLI（適合 CI/CD）
rich-deploy license issue MY_PROJ <指紋> --client "Acme Corp" --expires 2027-12-31
# 或 poetry plugin：
poetry rd license issue MY_PROJ <指紋> --client "Acme Corp" --expires 2027-12-31
```

---

### 第三步：甲方存檔並啟動

將收到的 JSON 存成 `license.lic`，設定環境變數後啟動程式：

```bash
export MYPROJ_LICENSE_FILE=/path/to/license.lic
```

---

## 9. 授權驗證實作範例

```python
# 整合進你的應用程式（使用 sdk export 匯出的 verify_license.py）
from verify_license import verify_license

if not verify_license():
    print("授權無效，請聯繫授權方")
    sys.exit(1)
```

驗證三道關卡：

```
關卡一：指紋比對  — 此授權是否屬於這台機器？
關卡二：到期日    — 授權是否仍在有效期內？
關卡三：RSA 簽章  — 授權是否由合法私鑰簽發？
```

三關全過才算授權合法。

---

## 10. 安全性總覽

| 資產 | 位置 | 保護方式 |
|------|------|----------|
| `private_key.pem` | 開發機 `projects/` | `.gitignore` 排除，永不傳輸 |
| `public_key.pem` | 可公開散布 | 只能驗證，無法偽造簽章 |
| `license.lic` | 甲方機器 | 綁定硬體指紋，換機即失效 |
| 指紋字串 | 傳輸過程 | 單向雜湊，無法還原原始硬體資訊 |

### 攻擊向量分析

| 攻擊方式 | 是否有效 | 原因 |
|---------|---------|------|
| 複製 license.lic 到其他機器 | ❌ | 指紋不符，關卡一失敗 |
| 修改 license.lic 的 fingerprint | ❌ | 簽章驗證失敗，關卡三失敗 |
| 修改 license.lic 的 expires | ❌ | expires 包含在簽章 payload 中 |
| 偽造 license.lic（無私鑰） | ❌ | RSA-2048 無法在沒有私鑰的情況下偽造 |
| 從 .lic 反推私鑰 | ❌ | RSA 單向性，數學上不可行 |
| 取得私鑰後偽造 | ✅ | 私鑰安全是整個系統的根本 |

---

## 11. 常見問題

### Q：指紋腳本在甲方機器上需要安裝什麼？

只需要 Python 3.10 以上，不需要安裝任何第三方套件。

### Q：私鑰不小心提交了怎麼辦？

立刻視為洩漏：
1. 執行 `rich-deploy key generate MY_PROJ` 重新生成金鑰
2. 以 `git filter-repo` 移除含私鑰的 commit
3. 通知所有持有舊授權的甲方重新走授權流程

### Q：可以同時授權多台機器嗎？

每台機器分別走一次完整流程，各自產生一份 `license.lic`。

### Q：`--expires` 日期格式？

ISO 8601 格式：`YYYY-MM-DD`，例如 `2027-12-31`。

---

## 12. 本機模擬練習

```bash
# 自動模擬（30 秒，四個驗證情境）
poetry run python client_sdk/bootstrap.py

# 手動逐步
rich-deploy project create DEMO "Demo" DEMO
rich-deploy key generate DEMO
python client_sdk/get_fingerprint.py          # 取得指紋
rich-deploy license issue DEMO <指紋> --client "Test" --expires 2027-12-31
rich-deploy sdk export DEMO                   # 匯出 SDK 給甲方
```

---

## 🚚 進階：金鑰搬遷、跨機集中管理與 DB 維運

> 處理「把簽發能力搬到另一台機器」「集中管理多把金鑰」以及「直接操作 `registry.db`」的實務問題。
> （本節指令一律用現行的 `poetry licmgr ...`／TUI；上方參考手冊第 6/8/12 節中的 `rich-deploy`／`tools/` 為舊版結構，待更新。）

### 要把「簽發能力」搬到另一台機器，需要帶什麼？

關鍵事實：**`registry.db` 本身不含私鑰**——`keys` 表只存「公鑰 PEM ＋ 公鑰指紋 ＋ 私鑰的*路徑字串*」。私鑰是另外的 `.pem` 檔（預設在 `~/.licmgr/projects/<id>/keys/`）。

| 帶過去的東西 | 能簽授權？ | 得到什麼 |
|---|---|---|
| 只有 `registry.db` | ❌ | 專案設定、已簽授權紀錄、公鑰、私鑰「路徑」——沒有任何秘密 |
| 只有私鑰 `.pem` | ✅ | 私鑰是唯一秘密；公鑰／指紋都能由它導出。簽新授權，這把就夠 |
| `registry.db` ＋ 私鑰 | ✅ ＋ 可管理 | 上面全部 ＋ 專案清單／已簽歷史／重新匯出舊 `.lic`（不必重簽） |

- **只是要能簽** → **私鑰就夠**（甚至可不透過 licmgr，直接用 `sign_license` 的演算法簽）。
- **要 licmgr 完整管理**（專案、歷史、重匯出）→ 才需要 `db ＋ 私鑰`，且**必須修好 db 內的私鑰路徑**（見下）。
- 已簽好的 `.lic` 存在 `licenses.license_json`，**重新匯出不需要私鑰**；只有「簽新的」才需要私鑰。

### 為什麼 `registry.db` 不直接存私鑰？（設計理由）

這是刻意的「**秘密與登錄分離**」設計——db 只放「非秘密的登錄資料」，唯一的秘密（私鑰）留在受權限保護的獨立檔案：

1. **用最適合的層級保護秘密**：私鑰是整個系統唯一的秘密，獨立 `.pem` 檔可套用檔案系統權限（`chmod 600`，只有擁有者可讀）；SQLite 欄位沒有同等存取控制——任何能讀到 db 檔的人／程序就讀到欄位內容。把私鑰留在受權限保護的檔案、db 只存「指向它的路徑」，保護就落在對的層級。
2. **db 不含秘密 → 可安全備份／檢視／分享／匯入**：`registry.db` 可以複製給同事查「發過哪些授權」、匯入另一台稽核、甚至放進（非敏感）版控，而**完全不會連帶外洩私鑰**。反過來說，若把私鑰塞進 db，**任何拿到 db 的人就等同拿到「簽發任意授權」的能力**——db 的流通性會直接變成秘密外洩面。
3. **公鑰／指紋本來就不是秘密**：db 存的 `public_key_pem`／`public_key_fp` 都是公開資訊，可由私鑰導出；真正要保護的只有那一把 `.pem`。這也呼應核心設計「私鑰永不離開開發機」（見上方「核心概念」）。

> 💡 **代價（即下一節的限制）**：因為 db 只記「路徑」而非金鑰內容，把 db 搬到另一台機器時，那個絕對路徑就會失效。換句話說，下面的 relink 問題是這個「安全分離」設計的**副作用、不是 bug**——正確做法是搬機時把私鑰檔一起搬、再修好路徑。

### ⚠️ 已知限制：`private_key_path` 存的是絕對路徑（搬機／匯入後會失效）

產生金鑰時，licmgr 把私鑰路徑以**當下解析的絕對路徑**寫進 `keys.private_key_path`（`licmgr/commands/key.py`、`licmgr/tui.py` 的金鑰產生流程）。而**簽發時直接信任這個字串**去讀檔（`licmgr/core/sign_license.py`；`license issue` 會先檢查檔案是否存在），程式**不會**用「金鑰根目錄 ＋ 專案 ID」重新推算。

因此：
- **「📥 匯入舊資料庫」只搬 DB 列、不搬私鑰檔**，且 `private_key_path` 原樣照抄（`licmgr/tui.py` 的 `_import_db`，並會印出「私鑰路徑仍指向原始位置」警告）。
- 換機／匯入後，`private_key_path` 仍指向**來源機**位置（可能是別台的 `D:\...` 或已搬走的 `~/.licmgr`）→ 簽發時報「找不到私鑰」。

**立即解法**：把私鑰檔放到本機，再改 db 的路徑（見下「操作 `registry.db`」的 `UPDATE`）。

### 從既有私鑰導入（導出公鑰、重建 DB 列）

當你**手上只有一把舊私鑰 `.pem`**（例如從別台機器或備份找回的 `private_key_v1.pem`），但本機 `registry.db` 缺對應的列、或列壞了，可以直接「導入」：licmgr 會從私鑰**推導出公鑰**並重建 `keys`（必要時連 `projects`）列，**不需要重新產生金鑰**。

- **TUI**：`licmgr → 🔑 金鑰管理 →（選任一專案）→ 📥 導入既有私鑰`。先輸入私鑰路徑，再選「既有專案」或輸入「新專案 ID」。
- **CLI**：

  ```bash
  poetry licmgr key import <PROJECT_ID> /path/to/private_key_v1.pem \
      [--version 1] [--env-prefix MY_PREFIX] [--no-create-project]
  ```

**導出的公鑰與原始公鑰位元組完全相同**（同一組金鑰對），所以：先前用這把私鑰簽發的 `.lic` **仍然有效、整合端的 `verify_license.py` 也不必動**，不需要重簽。推導方式與 `key generate` 完全一致（`load_pem_private_key` → `public_bytes(SubjectPublicKeyInfo)` → `sha256` 指紋），確保位元組層級相符。

會**自動填好**（可從私鑰推導的欄位）：

- `public_key_pem`（推導的公鑰）、`public_key_fp`（上述 sha256 指紋）、`private_key_path`（傳入 `.pem` 的絕對路徑）。
- 並會在私鑰旁順手寫一份 `public_key_v{version}.pem` 方便取用。

會**提示輸入**：

- `env_prefix`（建新專案時，**預設 = 專案 ID**）。**不會留空**，因為它驅動整合端的 `<PREFIX>_LICENSE_FILE` 環境變數來定位授權檔；導入到既有專案時沿用該專案原值。

會**留空（None）**：`git_remote`／`project_root`／`git_user_name`／`git_user_email` 等非衍生的 git 來源欄位（無法從私鑰得知）。

**冪等／修復語義**：`(project_id, version)` 已存在 → 更新該列的 `public_key_pem`／`public_key_fp`／`private_key_path`；專案在但金鑰版本不在 → 新增金鑰列；專案不存在 → 以上述預設新建（除非 `--no-create-project`）。導入到**既有專案**且其已存公鑰時，若推導出的公鑰與既存不同會**警告**（代表很可能拿錯私鑰）。

> ⚠️ **不會重建已簽授權歷史**：`licenses` 列（已發出的 `.lic`、機器指紋）無法從私鑰反推，導入時**完全不動 `licenses`**。若也要找回舊的已簽授權，請另外把舊 `.lic` 重新匯入（見「📥 匯入舊資料庫」）。

### 開啟與操作 `registry.db`（SQLite）

**先確認你動的是哪個 db**：預設 `~/.licmgr/registry.db`；但若**當前目錄有 `licmgr.toml`** 且設了 `[database].url`，會以它為準（本 repo 自帶的 `licmgr.toml` 指向相對路徑 `sqlite:///db/registry.db`）。用 `licmgr → ⚙ 設定` 可看到目前生效的 DB 路徑。

```bash
sqlite3 ~/.licmgr/registry.db        # CLI；GUI 可用「DB Browser for SQLite」
```

```sql
.mode box
.headers on
.tables
.schema keys

-- 每把金鑰的私鑰路徑（relink 前先看哪些指向不存在的檔）
SELECT id, project_id, version, private_key_path FROM keys;

-- 已簽授權（license_json 內含完整 .lic，可重匯出）
SELECT id, project_id, client_name, substr(machine_fp,1,16) AS fp, expires_at, revoked FROM licenses;
```

**修復私鑰路徑（搬機／匯入後最常用）**：

```sql
UPDATE keys
   SET private_key_path = '/home/you/.licmgr/projects/GIT_SmartSOPGuardian/keys/private_key_v1.pem'
 WHERE project_id = 'GIT_SmartSOPGuardian' AND version = 1;
```

三張表用途：`projects`（專案設定）、`keys`（每把金鑰：`public_key_pem`／`public_key_fp`／`private_key_path`）、`licenses`（已簽授權；`license_json` 即完整簽好的 `.lic`）。

> ⚠️ 直接改 db 前**先備份**（`cp registry.db registry.db.bak`），並確認 licmgr **沒有同時開著**，避免寫入衝突。

### 跨機集中管理的建議做法

1. 指定統一的金鑰根目錄（`licmgr.toml` 的 `[storage].keys_dir`），把所有 `<id>/keys/` 收在一起。
2. 搬機時**連同 `registry.db` ＋ 整個 keys 目錄一起搬**。
3. 到新機後，用上面的 `UPDATE` 把每把 `private_key_path` 改成新機實際位置（或見下方 Roadmap 的 relink）。
4. 不建議「在新機重新 `key generate`」繞過：那會產生**另一把**金鑰（公鑰不同），不符合「沿用既有金鑰、整合端 `verify_license.py` 不動」的情境。

---

## 🧭 規劃中功能（Roadmap）

> 以下兩項源自實際痛點，目前**尚未實作**；每項都附「現在可用的手動替代法」。

### 1. 公私鑰配對確認（verify keypair match）

**動機**：有了 `db ＋ 私鑰`，卻不確定這把私鑰是否對應到「整合端 `verify_license.py` 內嵌的公鑰」。配對不上 → 簽出的 `.lic` 永遠卡在驗證「關卡三（簽章）」。

**預期行為**：選一個專案／一把私鑰，與「比對來源」做配對檢查：
- 來源 A：db 的 `keys.public_key_pem` / `public_key_fp`（已存，最容易）
- 來源 B：指定一個整合專案的 `verify_license.py`，解析其 `PUBLIC_KEY_PEM` 後比對

**介面構想**：TUI 在 `🔑 金鑰管理` 增一項「驗證金鑰配對」；非互動 `poetry licmgr key verify <project> [--key <priv.pem>] [--verify-license <path>]`。

**實作要點**：`load_pem_private_key` → `.public_key().public_bytes(...)` → 比 modulus／指紋，或做一次 sign→verify 往返。（現況：`licmgr/core/generate_keys.py` 只在「產生」時導公鑰；尚無比對函式，也尚無 `verify_license.py` 的 `PUBLIC_KEY_PEM` 解析器。）

**現在可用的手動法**：

```bash
# A) openssl：modulus 相等即配對
diff <(openssl rsa -in private_key_v1.pem -noout -modulus) \
     <(openssl rsa -pubin -in public_key_v1.pem -noout -modulus) && echo MATCH || echo NO

# B) 與「整合端 verify_license.py 內嵌公鑰」比對（Python）
python - <<'PY'
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
priv = load_pem_private_key(open("private_key_v1.pem","rb").read(), None)
pub  = load_pem_public_key(open("pub.pem","rb").read())   # 把 verify_license.py 的 PUBLIC_KEY_PEM 內容存成 pub.pem
a, b = priv.public_key().public_numbers(), pub.public_numbers()
print("MATCH" if (a.n == b.n and a.e == b.e) else "NO")
PY
```

### 2. DB 移植 / 選擇性匯出 / 修復金鑰路徑

**動機**：兩個實際痛點——(i) 匯入舊 db 後私鑰路徑失效；(ii) 只想挑幾筆（專案／授權）搬，而非整包。

**預期子功能**：
- **修復金鑰路徑（relink）**：掃描 `keys.private_key_path`，標出檔案不存在者，提供「指向新位置」或「自動在 `keys_dir` 找同名檔」批次修復。直接解 (i)。
- **匯入時一併搬私鑰檔**：`_import_db` 增加選項，把來源 keys `.pem` 複製進本機 `keys_dir` 並改寫 `private_key_path`（目前只搬 DB 列、不搬檔）。
- **選擇性匯出**：挑選專案／授權子集，匯出成可攜 bundle（mini-db ＋ 對應 keys 檔，路徑相對化）。解 (ii)。

**介面構想**：TUI 於 `⚙ 設定` 內或新增「🔁 DB 維運」選單；非互動 `poetry licmgr db relink-keys`、`poetry licmgr db export --project X [--license <id>]`。

**實作要點**：menu 在 `licmgr/tui.py` 的 `menu_items` 加 `"label": handler`；非互動則加 `licmgr/commands/` 的 Command 子類並於 `licmgr/plugin.py` 註冊。relink 本質是掃描 ＋ `UPDATE keys SET private_key_path=...`。

**現在可用的手動法**：用上方「操作 `registry.db`」的 `UPDATE` 改路徑；選擇性匯出可暫時用 `sqlite3 .dump` 搭配手動挑表，或用 `poetry licmgr license export` 匯出個別 `.lic`。
