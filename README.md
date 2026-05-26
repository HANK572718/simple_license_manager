# licmgr — 離線授權管理工具

> **套件名稱**：`licmgr`　**GitHub**：[HANK572718/simple_license_manager](https://github.com/HANK572718/simple_license_manager)  
> **授權**：Apache 2.0　**平台**：Windows · Linux · macOS

私鑰永不離開開發機的軟體授權系統。透過互動式 TUI 或 Poetry plugin 命令管理專案、金鑰與客戶授權。

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

> 本機修改後重新執行 `poetry self add ./simple_license_manager` 即可更新。

---

## 快速開始：互動式 TUI

安裝完成後，在任意專案目錄執行：

```bash
licmgr
```

將出現帶箭頭選擇的互動式主選單：

```
╭─ licmgr — 離線授權管理工具 ──────╮
│  RSA-2048 + SQLite  |  Apache 2.0  │
╰────────────────────────────────────╯

? 主選單
  > 📁  專案管理
    🔑  金鑰管理
    📄  授權管理
    📦  SDK 匯出
    ⚙   設定
    🚪  離開
```

用 **↑↓ 方向鍵** 選擇，**Enter** 確認，所有操作均有引導提示。

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
poetry licmgr project create MY_PROJ "My Project" MYPROJ
poetry licmgr key generate MY_PROJ
poetry licmgr license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
poetry licmgr license list MY_PROJ
poetry licmgr sdk export MY_PROJ --output ./dist/MY_PROJ
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
