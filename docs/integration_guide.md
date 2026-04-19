# 專案整合指南：如何將授權驗證加入目標專案

本文件以 `GIT_SmartSOPGuardian` 為例，說明如何將 `rich_deploy` 匯出的客戶端 SDK
整合進目標專案的主程式。

---

## 一、整合前的準備（在 rich_deploy 完成）

在目標專案整合前，需先在 `rich_deploy` 完成以下步驟：

```
① [k] 為 GIT_SmartSOPGuardian 產生金鑰對
② [l] 對目標機器的指紋簽發授權，產生 local_test.lic
③ [e] 匯出客戶端 SDK → dist/GIT_SmartSOPGuardian/
```

匯出後確認 `dist/GIT_SmartSOPGuardian/` 包含：

```
dist/GIT_SmartSOPGuardian/
  verify_license.py   ← 公鑰已嵌入，ENV_PREFIX 已設為 "SSOPG"
  get_fingerprint.py  ← 採集指紋用
  bootstrap.py        ← 客戶一鍵部署精靈
```

---

## 二、目標專案的推薦目錄結構

將 SDK 放在專案根目錄的 `license/` 子資料夾，與業務程式碼分開：

```
GIT_SmartSOPGuardian/          ← 你的目標專案根目錄
│
├── src/
│   ├── __init__.py
│   └── main.py                ← 主程式，在此呼叫授權驗證
│
├── license/                   ← 從 dist/GIT_SmartSOPGuardian/ 複製過來
│   ├── __init__.py            ← 空檔，讓 Python 認識這個 package
│   ├── verify_license.py      ← 含嵌入公鑰，不要手動修改
│   ├── get_fingerprint.py     ← 交給客戶用，採集指紋
│   └── bootstrap.py           ← 客戶一鍵部署精靈
│
├── license.lic                ← 授權檔（由 rich_deploy 簽發，客戶自行放置）
├── pyproject.toml
└── README.md
```

**建立 `license/__init__.py`：**

```bash
touch license/__init__.py
# 或 Windows：
type nul > license\__init__.py
```

---

## 三、安裝依賴

目標專案需要安裝 `cryptography` 套件（verify_license.py 的依賴）：

```bash
# Poetry 專案
poetry add cryptography

# 或 pip
pip install cryptography
```

`get_fingerprint.py` 和 `bootstrap.py` 不需要額外依賴（純標準函式庫，bootstrap 需要 `rich`）。

---

## 四、主程式呼叫授權驗證

### 4-1 最簡單的做法：啟動時擋住

```python
# src/main.py
import sys
from pathlib import Path

# 把 license/ 加入路徑（若使用 package 匯入則不需要）
sys.path.insert(0, str(Path(__file__).parent.parent))

from license.verify_license import verify_license


def main():
    # 授權驗證 — 放在最前面，任何業務邏輯之前
    if not verify_license():
        print("授權驗證失敗，程式無法啟動。")
        print("請確認 license.lic 存在，或設定環境變數 SSOPG_LICENSE_FILE。")
        sys.exit(1)

    # ── 以下是正常業務邏輯 ──────────────────────────
    print("授權通過，啟動 GIT_SmartSOPGuardian...")
    # ...


if __name__ == "__main__":
    main()
```

### 4-2 指定授權檔路徑（不依賴環境變數）

```python
from license.verify_license import verify_license

# 明確指定路徑
if not verify_license(license_path="/opt/app/license.lic"):
    sys.exit(1)
```

### 4-3 搭配環境變數（推薦正式部署）

`verify_license()` 不傳路徑時，自動讀取環境變數：

```
SSOPG_LICENSE_FILE=/path/to/license.lic
```

```python
# 不傳任何參數，讓 verify_license 自己從環境變數找
if not verify_license():
    sys.exit(1)
```

客戶設定環境變數的方式：

```bash
# Linux / macOS（寫入 ~/.bashrc 或 ~/.zshrc）
export SSOPG_LICENSE_FILE=/home/user/app/license.lic

# Windows PowerShell（永久寫入使用者環境變數）
setx SSOPG_LICENSE_FILE "C:\app\license.lic"

# 或讓客戶執行 bootstrap.py，精靈會自動設定
python license/bootstrap.py
```

---

## 五、授權檔的路徑規則（優先順序）

`verify_license()` 解析授權檔路徑的順序：

```
1. 呼叫時傳入的 license_path 參數          ← 最高優先
2. 環境變數 SSOPG_LICENSE_FILE
3. 當前工作目錄的 license.lic              ← 預設 fallback
```

---

## 六、完整範例：含錯誤提示的啟動流程

```python
# src/main.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from license.verify_license import verify_license, ENV_PREFIX


def check_license() -> bool:
    """驗證授權並印出友善的錯誤訊息。"""
    ok = verify_license()
    if not ok:
        env_key = f"{ENV_PREFIX}_LICENSE_FILE"
        print("=" * 50)
        print("  授權驗證失敗")
        print("=" * 50)
        print(f"  請確認以下事項：")
        print(f"  1. 授權檔 license.lic 存在於執行目錄")
        print(f"     或設定環境變數 {env_key}")
        print(f"  2. 授權是否已到期")
        print(f"  3. 授權是否與本機對應（指紋相符）")
        print(f"  如需重新取得授權，請執行：")
        print(f"     python license/get_fingerprint.py")
        print("=" * 50)
    return ok


def main():
    if not check_license():
        sys.exit(1)

    # 業務邏輯...
    print("GIT_SmartSOPGuardian 啟動成功")


if __name__ == "__main__":
    main()
```

---

## 七、客戶端部署流程（甲方機器操作）

客戶拿到程式後，首次部署流程：

```
① 執行採集指紋（傳給你簽發授權）：
   python license/get_fingerprint.py

② 你在 rich_deploy 簽發 license.lic 並傳回給客戶

③ 客戶執行一鍵部署精靈（自動驗證 + 設定環境變數）：
   python license/bootstrap.py

④ 啟動主程式：
   python src/main.py
```

---

## 八、使用 PyInstaller 編譯為執行檔

若要編譯成 `.exe` 或無 Python 環境的執行檔：

```bash
pip install pyinstaller

# 單一執行檔，公鑰隨 verify_license.py 一起編入 binary
pyinstaller --onefile src/main.py \
    --add-data "license/verify_license.py:license" \
    --add-data "license/get_fingerprint.py:license"
```

編譯後的交付物：

```
dist/
  main.exe           ← 含公鑰，不含私鑰
  license.lic        ← 由 rich_deploy 簽發，隨執行檔一起交付
```

> **注意**：編譯後公鑰已嵌入 binary，客戶無法替換公鑰來偽造授權。

---

## 九、不同情境的 import 寫法

### 情境 A：SDK 在 `license/` 資料夾（推薦）

```python
from license.verify_license import verify_license
```

### 情境 B：SDK 直接放在專案根目錄

```python
from verify_license import verify_license
```

### 情境 C：路徑問題時的保險寫法

```python
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "verify_license",
    Path(__file__).parent.parent / "license" / "verify_license.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
verify_license = mod.verify_license
```

---

## 十、注意事項

| 項目 | 說明 |
|------|------|
| `verify_license.py` 不要手動修改 | 公鑰和 `ENV_PREFIX` 由 rich_deploy 匯出時自動填入 |
| 若更換金鑰對 | 需重新 `[e] 匯出 SDK` 並更新目標專案的 `license/` |
| `license.lic` 不要 commit | 加入目標專案的 `.gitignore`（每個客戶的授權不同） |
| `get_fingerprint.py` 純標準函式庫 | 可單獨分發給客戶，不需要 Python 套件環境 |
