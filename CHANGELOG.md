# 版本紀錄

每一版寫三件事：改了什麼、原本通過的專案會不會變成沒過、專案 repo 要不要跟著改設定。版本號的規則見 README 的「改版流程」。

## v1.0.0

第一個版本。

- 支援 Go、C# / .NET、JavaScript / TypeScript（Vitest、Jest）、Python。
- 指令：`test`、`crap`、`mutation`、`baseline`。`crap` 和 `mutation` 加 `--base` 時只檢查改到的部分。
- JS / TS：Jest 的覆蓋率報告把「建立箭頭函式」記成函式起點上的一個敘述，這個敘述不計入函式的覆蓋率。沒有測試的箭頭函式，覆蓋率是 0%。
- Windows 上執行目錄是 8.3 短檔名（例如 `C:/Users/ALEXAN~1.LIN`）時，也能正確對應各工具回報的檔案路徑。
- `selftest.py`：用 `selftest/` 的五個範例專案做回歸測試。
