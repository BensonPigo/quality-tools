## 品質規則（三重約束）

改完程式後依序執行，全部通過才算完成：

1. `python tools/quality/quality.py test`：單元測試
2. `python tools/quality/quality.py crap --base origin/main`：改到的函式，CRAP 不能超過門檻
3. `python tools/quality/quality.py mutation --base origin/main`：改到的行，變異測試效能要達到門檻

規則：

- 不准修改 `.quality.json`、`.gitmodules`，以及 `tools/quality/`、`.gitea/`、`.github/`、`.claude/` 底下的檔案，也不准切換 `tools/quality` 的版本。
- 不准刪除測試，也不准把測試註解掉或標成略過。
- 測試的正確答案要照需求規格寫死，不准呼叫正式程式碼算出來。
- CRAP 超標時，照工具標的方向處理：標「要拆函式」就拆函式，標「覆蓋率要到 X%」就補測試。
- 變異測試有突變體存活時，先補測試。認為是等價突變體（怎麼改輸出都一樣）的，在回報裡列出位置和理由，由人判斷。
- 過不了的時候，說明卡在哪裡、試過什麼，等人處理，不要想辦法繞過檢查。
