# 版本紀錄

每一版寫三件事：改了什麼、原本通過的專案會不會變成沒過、專案 repo 要不要跟著改設定。版本號的規則見 README 的「改版流程」。

## v2.0.0

整個重寫成 `qtools` 套件。量測算法沿用 v1.0.0：圈複雜度規則、覆蓋率口徑、CRAP 公式、「改到函式」的判斷都沒有改。**預設值下，分數跟 v1.0.0 一致**：`dev/v1_parity.py check` 在五個範例專案上，CRAP 表每一列，以及抓到 + 逾時、沒抓到、測試沒跑到三個數字，都跟 v1.0.0 的記錄相同。

原本通過的專案會不會變成沒過：

- 用 `migrate` 轉換過來的設定，門檻明寫成 v1 實際生效的值（`reach_rate_threshold` 沒寫過就是 0），判定結果跟 v1 相同。
- 各 repo 自己安裝的 StrykerJS、cosmic-ray 不在驗證清單內時，會以結束碼 2 結束（見下方不相容項目第 6 點）。
- 新建的 `.quality.json` 沒寫 `reach_rate_threshold` 時，預設是 50，會擋下沒有測試的新程式。

### 不相容的地方

1. **`.quality.json` 要改成 v2 格式。** 一定要有 `"version": 2`；沒有 `version`，或是出現 v1 的鍵名，所有指令都以結束碼 2 結束，訊息叫人執行 `migrate`。鍵名對照：

   | v1 | v2 |
   |---|---|
   | （無） | `version: 2` |
   | `crap_threshold` | `crap.threshold` |
   | `efficacy_threshold` | `mutation.kill_rate_threshold` |
   | `mutant_coverage_threshold` | `mutation.reach_rate_threshold` |
   | `python_mutant_timeout` | `mutation.timeout_seconds`（只有 `language` 是 python 時轉換，其他語言原本就沒作用，轉換時略過並說明） |
   | `dotnet_solution` | `csharp.solution` |
   | `js_test_runner` | `js.test_runner` |
   | `python` | `python.interpreter` |
   | `language`、`base`、`exclude` | 不變 |

2. **未知的鍵、型別不對的值，以結束碼 2 結束。** v1 會忽略打錯的鍵。
3. **畫面、報告和設定用的名稱改成白話說法。** 殺死→抓到、存活→沒抓到、超時→逾時、沒覆蓋→測試沒跑到、效能→抓錯率、突變體覆蓋率→測到率、變異測試→抓錯檢查、第一重／第二重／第三重→第一關／第二關／第三關。解析 v1 文字輸出的腳本要跟著改。現況報告的表格欄位也用新名稱。
4. **`mutation.reach_rate_threshold` 的預設值是 50。** v1 對應的鍵（上表）預設是 0。`migrate` 轉換沒寫過這個鍵的 v1 設定時寫入 0，維持 v1 的判定；要擋下沒有測試的新程式，手動調成大於 0。
5. **檔案搬移。** 輔助程式搬到 `qtools/helpers/`：`dotnet/CsMetrics/` → `qtools/helpers/dotnet/CsMetrics/`、`js/complexity.cjs` → `qtools/helpers/js/complexity.cjs`、`python/cr_skip_uncovered.py` → `qtools/helpers/python/cr_skip_uncovered.py`。v1 放在根目錄的共用程式和各語言模組檔案刪除，內容移到 `qtools/`。進入點 `quality.py` 和 submodule 路徑 `tools/quality/` 不變。workflow 裡快取 key 寫的 `tools/quality/` 根目錄底下的語言模組檔，以及 `tools/quality/dotnet/**`、`tools/quality/js/**`，要改成 `tools/quality/qtools/langs/<語言>.py` 和 `tools/quality/qtools/helpers/**`；試點期間直接複製工具的寫法也要改成複製 `quality.py` 和 `qtools/`。
6. **StrykerJS 和 cosmic-ray 只接受驗證過的版本。** StrykerJS 10.0.0、10.1.1；cosmic-ray 8.7.0。其他版本以結束碼 2 結束，訊息列出驗證過的版本。
7. **`baseline` 多寫一份同名的 `.json`**（預設 `docs/品質現況.md` 旁邊的 `docs/品質現況.json`），新增的檔案要不要 commit 由各 repo 決定。

### 升級步驟

在專案 repo 開一個分支，工具版本和設定檔放在同一個 PR：

```bash
git -C tools/quality fetch --tags
git -C tools/quality checkout v2.0.0
python tools/quality/quality.py migrate     # 改寫 .quality.json，並印出前後差異
git add tools/quality .quality.json
```

詳細步驟（含 workflow、`gate.sh`、`.claude/settings.json`、CODEOWNERS 要同步更新的檔案）見 `docs/範本_三道防線/專案repo範本/README.md` 的「從 v1 升級」。

### 新功能

- **改了也沒差的版本排除清單**：各 repo 根目錄的 `.quality-equivalents.json`，用 file、mutator、該行原文比對，不用行號。`reason`、`approved_by` 必填。清單裡沒用到的項目會列出來。
- **沒抓到的改壞版本寫出改了什麼**：例如「第 5 行 把 `>=` 改成 `>`」。取不到改成什麼時，退回印改法名稱和該行原文。
- **預設值和覆蓋**：`mutation.timeout_seconds`、`mutation.workers`、`mutation.exclude_mutators`，寫 `null` 用語言預設值，repo 可以覆蓋。v2.0.0 的預設值不排除任何改法，也不改逾時和並行。Go 設 `timeout_seconds`、Python 設 `workers` 會印警告，設定沒有作用。
- **一次只開一關**：`gates` 設定哪幾關啟用，沒啟用的關單獨執行時印「還沒啟用」並以 0 結束。新增 `check` 指令，依序跑已啟用的關，第一個沒過就停；`--skip` 略過指定的關，`--json 目錄` 寫出各關的 JSON 報告。
- **現況報告**：CRAP 表加「修改次數」（超標的函式，統計 `baseline.churn_since` 以來改到它的 commit 數，建立的那一次不算），修改次數達到 `baseline.hot_churn` 的標「優先處理」並排在最前面。新增 `baseline --compare 舊.json` 和 `compare 舊.json 新.json`，印出超標函式數、要拆函式數、優先處理數、各套件抓錯率和測到率的前後差。
- **JSON 報告**：`crap`、`mutation`、`check` 加 `--json`（`check` 是目錄）寫出同一份格式，含實際使用的量測工具版本；`baseline` 不用加參數，一律在報告旁邊寫出同名的 `.json`。
- **`migrate`**：把 v1 的 `.quality.json` 轉成 v2。
- **發布方式**：除了 git submodule，新增 pip 安裝（`pip install "quality-tools @ git+https://...@v2.0.0"`，指令 `quality`）和 reusable workflow（`.github/workflows/quality.yml`）。
- **`gate.sh` 範本**改成呼叫 `check --skip mutation`。
- 範本新增 `.quality-equivalents.json`、`CODEOWNERS`、`workflows/reusable-caller.yml`。

### 驗證

本機（Windows）通過：`selftest.py` 五個範例、`dev/v1_parity.py check` 五個範例、`pip install` 本機路徑安裝。reusable workflow、Gitea、Linux 上的 v2 程式都還沒在真的 runner 上驗證。

## v1.0.0

第一個版本。

- 支援 Go、C# / .NET、JavaScript / TypeScript（Vitest、Jest）、Python。
- 指令：`test`、`crap`、`mutation`、`baseline`。`crap` 和 `mutation` 加 `--base` 時只檢查改到的部分。
- JS / TS：Jest 的覆蓋率報告把「建立箭頭函式」記成函式起點上的一個敘述，這個敘述不計入函式的覆蓋率。沒有測試的箭頭函式，覆蓋率是 0%。
- Windows 上執行目錄是 8.3 短檔名（例如 `C:/Users/ALEXAN~1.LIN`）時，也能正確對應各工具回報的檔案路徑。
- `selftest.py`：用 `selftest/` 的五個範例專案做回歸測試。
