# SQLite 終端機入門（超基礎）

> 給**沒用過 sqlite** 的人。看完你就能安全地開啟 licmgr 的 `registry.db`、查資料、必要時改一筆，然後正確離開。
>
> **寫這份的起因**：把一整段指令貼進去後「按 Enter 沒反應」——多半**不是你做錯**，而是 SQL 少了一個分號 `;`。第 3 節專門解這個。

---

## 1. 開啟與離開

在**一般終端機**打（以 licmgr 的資料庫為例）：

```bash
sqlite3 ~/.licmgr/registry.db
```

成功後，提示字元會變成：

```
sqlite>
```

這代表你「進到 sqlite 裡面」了——之後打的東西都是給 sqlite，不是給一般終端機。

離開、回到一般終端機：

```
.quit
```

（按 `Ctrl+D` 或打 `.exit` 也可以。）

---

## 2. 最重要的觀念：裡面有「兩種」指令

進到 `sqlite>` 之後，你打的東西分**兩種**，規則不一樣：

| 種類 | 長相 | 規則 | 範例 |
|---|---|---|---|
| **點指令（dot command）** | 以 `.` 開頭 | 一行一個、**不用分號**、Enter 立刻執行 | `.tables`、`.schema keys`、`.quit` |
| **SQL 指令** | `SELECT` / `UPDATE` / `INSERT`… | **一定要用分號 `;` 結尾**才會執行；可跨好幾行 | `SELECT * FROM keys;` |

👉 **新手 90% 的「沒反應」都是 SQL 忘了打分號 `;`。**

---

## 3. 「按了 Enter 卻沒反應」是怎麼回事？（對症下藥）

- **提示字元從 `sqlite>` 變成 `...>`** ＝ sqlite 還在等你把指令打完（你少了分號）。
  → 直接打一個 `;` 再按 Enter，它就會執行：

  ```
  sqlite> SELECT * FROM keys      ← 忘了分號，按 Enter…
     ...>                          ← 變成這樣在等你（不是當機）
     ...> ;                        ← 補上分號 + Enter，這時才真的跑
  ```

- **跑完是一片空白、又回到 `sqlite>`** ＝ 指令**成功了**，只是「查不到任何資料列」（0 筆）。這**不是錯誤**。

- **想放棄正在打的這一行** → 按 **`Ctrl+C`**（清掉這行，回到乾淨的 `sqlite>`）。

---

## 4. 「整段貼」還是「一行一行」？

- 技術上**整段貼可以**：sqlite 會把每個點指令、每個 `;` 結尾的 SQL 各自跑掉。
- 但新手**建議一段一段貼、SQL 記得 `;`**，比較看得懂哪行在做什麼、哪行出錯。
- ⚠️ **不要把 `-- 註解` 接在點指令後面**，例如 `.tables   -- 列出表`：點指令會把後面整串當成「篩選參數」，結果什麼都沒列 → 一片空白（這就是常見的「貼進去沒反應」陷阱之一）。註解要嘛**獨立成一行**、要嘛只放在 SQL 裡。

---

## 5. 先讓輸出變好看（強烈建議）

進去後先打這兩行（點指令，不用分號）：

```
.mode box
.headers on
```

- `.mode box`：把結果排成漂亮的方框表格。
- `.headers on`：顯示欄位名稱。

（這兩行打了不會有輸出，是正常的。）

---

## 6. 最小速查表

| 想做的事 | 指令（點指令免分號；SQL 要分號） |
|---|---|
| 看有哪些表 | `.tables` |
| 看某張表有哪些欄位 | `.schema keys` |
| 讓輸出好看 | `.mode box` 然後 `.headers on` |
| 查全部 | `SELECT * FROM keys;` |
| 只看某幾欄 | `SELECT id, project_id FROM keys;` |
| 加條件 | `SELECT * FROM keys WHERE project_id='GIT_SmartSOPGuardian';` |
| 改一筆 | `UPDATE keys SET notes='x' WHERE id=1;` |
| 看所有點指令說明 | `.help` |
| 離開 | `.quit` |

---

## 7. 照著做一次（用 licmgr 的 db）

逐行輸入、每行後按 Enter；括號是「你應該會看到什麼」。

```text
$ sqlite3 ~/.licmgr/registry.db          ← 在一般終端機打這行
sqlite>                                   ← 提示變這樣 = 進來了

sqlite> .mode box                         （沒有輸出，正常）
sqlite> .headers on                       （沒有輸出，正常）

sqlite> .tables                           ← 列出三張表
keys  licenses  projects

sqlite> SELECT id, project_id, private_key_path FROM keys;
                                          ↑ 注意結尾的分號！按 Enter 才會印出方框表格

sqlite> .quit                             ← 回到一般終端機
$
```

> 如果某次 `SELECT …` 按 Enter 後變成 `...>`，就是漏了分號——補一個 `;` 再 Enter 即可。

---

## 8. 操作 licmgr 的 db 時的安全提醒

- 要**改東西**（`UPDATE` / `DELETE`）前先備份。在**一般終端機**（不是 sqlite 裡面）執行：

  ```bash
  cp ~/.licmgr/registry.db ~/.licmgr/registry.db.bak
  ```

- 改之前先確認 **licmgr 沒有同時開著**，避免互相干擾。
- 只是想「看」的話，純 `SELECT` 不會改到任何資料，可以放心。
- 不確定自己在哪個 db？licmgr 的 `⚙ 設定` 會顯示目前生效的 DB 路徑（預設 `~/.licmgr/registry.db`；若當前目錄有 `licmgr.toml` 會以它為準）。
