# 版本紀錄

每一版寫三件事：改了什麼、原本通過的專案會不會變成沒過、專案 repo 要不要跟著改設定。版本號的規則見 README 的「改版流程」。

## v2.4.0

- 排除清單（`.quality-equivalents.json`）的項目可以加選填的 `column`，只排除那一欄的改壞版本。原本只比對檔案、改法和那一行的原文，同一行、同一種改法有好幾個改壞版本時，寫一項就全部排除；其中有真的缺口時（例如 `if err != nil || !isString || seen[key] {` 的第一個 `||` 改了也沒差，第二個是重複欄位的檢查），沒辦法只排除改了也沒差的那個。欄位照量測工具回報的值，相對於那一行的原始內容（含縮排），只改縮排時這一項就對不上，要人重新判斷。`column` 不是正整數時以結束碼 2 結束。
- 「排除清單有 N 項沒用到」改成逐項判斷：一項只要對到任何一個改壞版本就算有用到。沒寫 `column` 的項目結果跟之前相同。
- 文字輸出列出沒抓到、測試沒跑到的改壞版本時，位置從「檔案:行」改成「檔案:行:欄」（量測工具沒回報欄位時照舊）；沒用到的項目有 `column` 時印出欄位。JSON 報告格式不變。
- 範本的 `CLAUDE片段.md` 和 README：AI 回報改了也沒差的版本時多列「欄」；說明 `column` 的用法。

原本通過的專案不會變成沒過，`.quality.json` 不用改，沒用 `column` 的排除清單結果不變。排除清單用了 `column` 的專案要 v2.4.0 以上：舊版會把它當成不認得的鍵，以結束碼 2 結束。解析文字輸出「檔案:行」的腳本要改成也接受「檔案:行:欄」。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.4.0`。

## v2.3.1

- Go 的 gocyclo 和 gremlins 不再用 `go run 套件@版本` 執行。`go run` 每次都向 GOPROXY 查版本資訊和棄用狀態，模組快取裡已經有也一樣，`GOPROXY=off` 時也失敗；`baseline` 對每個套件各執行一次 gremlins，任何一次網路不通，整份量測就以結束碼 2 停下。現在第一次使用時用 `go install` 裝到工具快取目錄（`QUALITY_TOOLS_DIR`，預設 `~/.cache/quality-tools`）的 `<工具>-<工具版本>-<Go 版本>` 底下，之後直接執行。先裝到暫存目錄再搬過去，安裝中斷不會留下寫一半的執行檔。目錄名稱帶 Go 版本：工具用建置它的 Go 解析原始碼，Go 升級後會重裝。
- 執行外部指令遇到檔案存在卻無法執行（損毀、沒有執行權限）時，以結束碼 2 停下並印「無法執行 …」，提示刪掉工具快取目錄底下的該目錄；之前是 Python traceback。C# 的 Stryker.NET 和 CsMetrics 也適用。
- 實測：GOPROXY 連不到時，v2.3.0 的 Go 範例 33 項失敗，這版全部通過；一個有外部依賴的 Go 專案斷網跑完整 `baseline`，結果跟有網路時完全相同。

原本通過的專案不會變成沒過，量測結果不變，`.quality.json` 不用改。第一次安裝工具和第一次下載專案依賴仍然需要網路。gremlins 每個套件會先執行 `go mod download`：專案依賴的模組沒有完整下載過（例如只給其他作業系統用的依賴）時，斷網仍會失敗。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.3.1`。

## v2.3.0

- Go 的抓錯檢查執行 gremlins 時，GOFLAGS 在 `go env GOFLAGS` 的值後面加 `-count=1`，不讀測試快取。gremlins 用第一次 `go test` 的時間 × `--timeout-coefficient`（30）當每個改壞版本的時限，時限包含重新編譯。CRAP 或前一個套件剛跑過同樣的測試時，那次 `go test` 讀快取，只花零點幾秒，時限只剩幾秒；改壞的版本要重新編譯，被越多套件引用的套件要重編越多，同時跑好幾個時大量超時，測試全過的改壞版本也被算成逾時（算抓到）。實測一個 `go.coverage_scope = "module"`、12 核心機器上跑的專案：逾時從 340 個變成 3 個，其中 67 個實際是沒抓到；整體抓錯率 93.98% → 88.31%，資料存取層的套件 100% → 91.44%，一個套件從 86.67% 變成 77.78%，低於門檻 80。`baseline` 從 18 分鐘變成 30 分鐘。
- 用 `go env GOFLAGS` 取得生效中的值，`go env -w` 寫進設定檔的旗標（例如 `-tags`、`-mod`）照樣帶給 gremlins。GOFLAGS 裡原本寫的 `-count` 會被蓋成 1。
- selftest 的 Go 範例在 macOS 上可以跑：兩個情境原本用 GNU 寫法的 `sed -i`，BSD sed 會把下一個參數當成備份副檔名而失敗，改成寫到暫存檔再 `mv`。`dev/unit_checks.py` 檢查 `selftest/*.json` 不再出現 `sed -i`。

原本通過的專案可能變成沒過：原本被算成逾時的改壞版本，有一部分會變成沒抓到，Go 的抓錯率可能下降；`package` 和 `module` 都受影響，`module`、worker 多、套件被很多套件引用時差最多。真的卡住的改壞版本要等「30 × 實際測試時間」才判定逾時，抓錯檢查和 `baseline` 會變慢。C#、JS、Python 不變。`.quality.json` 不用改。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.3.0`。拿 v2.2.0 以前的 Go 現況報告跟新報告比較時，抓錯率的下降有一部分來自量法修正，不代表測試變差。

## v2.2.0

- `go.coverage_scope = "module"` 也套用到 Go 的抓錯檢查（`mutation`、`check` 的第三關、`baseline`）：gremlins 加上 `--integration --coverpkg <沒被 exclude 排除的套件>`，覆蓋率和每個改壞的版本都跑整個模組的測試。v2.1.0 時這個設定只影響 CRAP，同一行程式在 CRAP 算有測到、在抓錯檢查算「測試沒跑到」。實測一個以整合測試為主的套件，測到率從 13.4% 變成 94.6%，抓錯率 82.2% → 83.3%，沒抓到的改壞版本從 8 個變成 53 個，新增的 45 個原本被歸成「測試沒跑到」。
- 設成 `"module"` 時，畫面印「抓錯檢查：整個模組的測試都算（go.coverage_scope = module），每個改壞的版本跑整個模組的測試」。
- Go 量過抓錯檢查的 JSON 報告，`tools` 多一個 `mutation_scope`（`package` 或 `module`），schema 版本不變。現況報告的抓錯檢查段（Go）多一行寫明範圍。`compare` 和 `baseline --compare` 遇到兩份報告的抓錯範圍不同時，多一行「抓錯檢查的範圍不同（package → module），抓錯率和測到率的變化主要來自量法改變」；v2.2.0 以前的 Go 報告沒有記錄，視為 `package`。所以拿 v2.1.0 設成 `module` 的現況報告跟新的比較，也會出現這一行。

沒設 `go.coverage_scope`（或設成 `"package"`）的專案，量法、判定和畫面輸出都跟 v2.1.0 相同，JSON 只多 `tools.mutation_scope`。設成 `"module"` 的專案：抓錯檢查會執行原本被歸成「測試沒跑到」的改壞版本，測到率上升，抓錯率可能下降，已經啟用第三關的可能由通過變成沒過；抓錯檢查和 `baseline` 都會慢很多（見 README 的 Go 注意事項）。`.quality.json` 不用改。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.2.0`。

## v2.1.0

- 新增設定 `go.coverage_scope`：`"package"`（預設，跟之前一樣只算同一個套件的測試）或 `"module"`（整個模組的測試都算，`go test` 加上 `-coverpkg=<所有沒被 exclude 排除的套件>`）。只影響 Go 的 CRAP（`crap`、`check` 的第二關、`baseline`），抓錯檢查不變。測試集中在某個套件、跑整套流程的專案，用 `"module"` 才不會被要求補已經測到的程式。實測一個以整合測試為主的 Go 專案，超標的函式從 82 個變成 36 個。
- 設成 `"module"` 時，畫面印「覆蓋率：整個模組的測試都算（go.coverage_scope = module）」。
- Go 量過 CRAP 的 JSON 報告，`tools` 多一個 `coverage_scope`（`package` 或 `module`）。JSON 的 schema 版本不變，舊的現況報告照樣能拿來比較。
- 現況報告的 CRAP 段（Go）多一行寫明覆蓋率範圍。`compare` 和 `baseline --compare` 比較兩份覆蓋率範圍不同的報告時，多一行「覆蓋率範圍不同（package → module），CRAP 的變化主要來自量法改變」；舊的 Go 報告沒有記錄範圍，視為 `package`。

原本通過的專案不會變成沒過：沒設 `go.coverage_scope` 時量法和判定都跟 v2.0.3 相同，CRAP 指令的畫面輸出也相同。要用 `"module"` 的專案在 `.quality.json` 加 `"go": {"coverage_scope": "module"}`；這個設定要等工具升到 v2.1.0 之後才能加，舊版會因為不認得 `go` 而以結束碼 2 停下。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.1.0`。

## v2.0.3

- Go 的套件裡沒有任何可以改壞的地方時（只有測試、常數、型別或 `doc.go`），gremlins 印「No results to report.」且不寫結果檔。之前只有加 `--base`、同套件其他檔案都略過時才算成沒有改壞的版本，`baseline` 和不帶 `--base` 的 `mutation` 遇到這種套件會以結束碼 2 停下（「gremlins 執行失敗」）；現在一律算成這個套件沒有改壞的版本。gremlins 執行失敗（例如測試失敗）時仍以結束碼 2 停下。

原本通過的專案不會變成沒過；原本因為這種套件跑不完的 `baseline`、`mutation` 現在可以跑完。`.quality.json` 不用改。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.0.3`。

## v2.0.2

- Go 的抓錯檢查加 `--base` 時，只對改到的檔案產生改壞的版本。之前會對改到的套件裡每個檔案都產生改壞的版本、每個都跑一次整包測試，最後才丟掉沒改到的部分，PR 只改一行也要付整個套件的代價。同套件沒改到的檔案現在用 gremlins 的 `-E` 排除，畫面多印一行「只對改到的檔案產生改壞的版本，略過 N 個沒改到的檔案」。
- gremlins 的結果裡還出現應該略過的檔案時，以結束碼 2 停下，訊息是「排除沒改到的檔案沒有生效」。
- 改到的檔案沒有可以改壞的地方（例如只有常數）、同套件其他檔案又都略過時，gremlins 不寫結果檔，這種情況算成沒有改壞的版本，跟 v2.0.1 的結果相同。
- 不帶 `--base` 的抓錯檢查和 `baseline` 不變；C#、JS、Python 不變。

省下的時間是「略過的改壞版本數 × 套件測試一次的時間」，套件測試越慢省越多。測試很快的套件省不了多少：gremlins 每個 worker 開工前會把 go.mod 所在的目錄（通常是 repo 根目錄，含 `node_modules`、`.git` 這類目錄）整個複製到暫存資料夾，這段時間不受這次修改影響。實測一個 11 個程式檔、測試約 1 秒的套件，改一行時 v2.0.1 和 v2.0.2 都約 7 分鐘。

改到的行上每個改壞的版本，結果（抓到、沒抓到、逾時、測試沒跑到）跟 v2.0.1 相同：每個改壞的版本都獨立跑整個套件的測試，覆蓋率和逾時時限在產生改壞的版本之前就由一次完整的 `go test` 算好，排除其他檔案不影響它們。原本通過的專案不會變成沒過，`.quality.json` 不用改。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.0.2`。

## v2.0.1

- reusable workflow 的 `dotnet-version` 預設從 `8.0.x` 改成 `10.0.x`，範本 `workflows/csharp.yml` 從 `9.0.x` 改成 `10.0.x`，跟 selftest 驗證過的 .NET SDK 一致。專案有指定 `dotnet-version` 的不受影響。
- reusable workflow：`tools/quality` 已經有檔案（直接複製進專案的工具）時，印出原因後停下。之前一樣會失敗，只是訊息是 `rmdir` 的錯誤。
- README 的結束碼說明、CHANGELOG v2.0.0 的 `version` 說明改正，程式行為沒變。

原本通過的專案不會變成沒過，`.quality.json` 不用改。用 reusable workflow 的專案，`uses:` 和 `tools-ref` 一起改成 `v2.0.1`。

## v2.0.0

整個重寫成 `qtools` 套件。量測算法沿用 v1.0.0：圈複雜度規則、覆蓋率口徑、CRAP 公式、「改到函式」的判斷都沒有改。**預設值下，分數跟 v1.0.0 一致**：`dev/v1_parity.py check` 在五個範例專案上，CRAP 表每一列，以及抓到 + 逾時、沒抓到、測試沒跑到三個數字，都跟 v1.0.0 的記錄相同。

原本通過的專案會不會變成沒過：

- 照鍵名對照表改好的設定，門檻明寫成 v1 實際生效的值（`reach_rate_threshold` 沒寫過就寫 0），判定結果跟 v1 相同。
- 各 repo 自己安裝的 StrykerJS、cosmic-ray 不在驗證清單內時，會以結束碼 2 結束（見下方不相容項目第 6 點）。
- 新建的 `.quality.json` 沒寫 `reach_rate_threshold` 時，預設是 50，會擋下沒有測試的新程式。

### 不相容的地方

1. **`.quality.json` 要改成 v2 格式。** 一定要有 `"version": 2`；沒有 `version` 或不是 2，`test`、`crap`、`mutation`、`check`、`baseline` 都以結束碼 2 結束，訊息是「.quality.json 的 version 必須是 2」。v1 的鍵名屬於不認得的鍵，同樣以結束碼 2 結束。照下表的鍵名手動改：

   | v1 | v2 |
   |---|---|
   | （無） | `version: 2` |
   | `crap_threshold` | `crap.threshold` |
   | `efficacy_threshold` | `mutation.kill_rate_threshold` |
   | `mutant_coverage_threshold` | `mutation.reach_rate_threshold` |
   | `python_mutant_timeout` | `mutation.timeout_seconds`（只有 `language` 是 python 時改，其他語言原本就沒作用，不要搬） |
   | `dotnet_solution` | `csharp.solution` |
   | `js_test_runner` | `js.test_runner` |
   | `python` | `python.interpreter` |
   | `language`、`base`、`exclude` | 不變 |

2. **未知的鍵、型別不對的值，以結束碼 2 結束。** v1 會忽略打錯的鍵。
3. **畫面、報告和設定用的名稱改成白話說法。** 殺死→抓到、存活→沒抓到、超時→逾時、沒覆蓋→測試沒跑到、效能→抓錯率、突變體覆蓋率→測到率、變異測試→抓錯檢查、第一重／第二重／第三重→第一關／第二關／第三關。解析 v1 文字輸出的腳本要跟著改。現況報告的表格欄位也用新名稱。
4. **`mutation.reach_rate_threshold` 的預設值是 50。** v1 對應的鍵（上表）預設是 0。v1 設定沒寫過對應的鍵時，在 v2 明寫 0 才能維持 v1 的判定；要擋下沒有測試的新程式，調成大於 0。
5. **檔案搬移。** 輔助程式搬到 `qtools/helpers/`：`dotnet/CsMetrics/` → `qtools/helpers/dotnet/CsMetrics/`、`js/complexity.cjs` → `qtools/helpers/js/complexity.cjs`、`python/cr_skip_uncovered.py` → `qtools/helpers/python/cr_skip_uncovered.py`。v1 放在根目錄的共用程式和各語言模組檔案刪除，內容移到 `qtools/`。進入點 `quality.py` 和 submodule 路徑 `tools/quality/` 不變。workflow 裡快取 key 寫的 `tools/quality/` 根目錄底下的語言模組檔，以及 `tools/quality/dotnet/**`、`tools/quality/js/**`，要改成 `tools/quality/qtools/langs/<語言>.py` 和 `tools/quality/qtools/helpers/**`；試點期間直接複製工具的寫法也要改成複製 `quality.py` 和 `qtools/`。
6. **StrykerJS 和 cosmic-ray 只接受驗證過的版本。** StrykerJS 10.0.0、10.1.1；cosmic-ray 8.7.0。其他版本以結束碼 2 結束，訊息列出驗證過的版本。
7. **`baseline` 多寫一份同名的 `.json`**（預設 `docs/品質現況.md` 旁邊的 `docs/品質現況.json`），新增的檔案要不要 commit 由各 repo 決定。

### 升級步驟

在專案 repo 開一個分支，工具版本和設定檔放在同一個 PR：

```bash
git -C tools/quality fetch --tags
git -C tools/quality checkout v2.0.0
git add tools/quality
```

接著照上面的鍵名對照表手動改 `.quality.json`，加上 `"version": 2`，用 `git diff .quality.json` 確認門檻和 v1 的值一致；跑 `python tools/quality/quality.py check --base origin/main`，確認結果跟升級前一樣。workflow、`gate.sh`、`.claude/settings.json`、CODEOWNERS、`.quality-equivalents.json`、`CLAUDE.md` 對照 `docs/範本_三道防線/專案repo範本/` 同步更新。

### 新功能

- **改了也沒差的版本排除清單**：各 repo 根目錄的 `.quality-equivalents.json`，用 file、mutator、該行原文比對，不用行號。`reason`、`approved_by` 必填。清單裡沒用到的項目會列出來。
- **沒抓到的改壞版本寫出改了什麼**：例如「第 5 行 把 `>=` 改成 `>`」。取不到改成什麼時，退回印改法名稱和該行原文。
- **預設值和覆蓋**：`mutation.timeout_seconds`、`mutation.workers`、`mutation.exclude_mutators`，寫 `null` 用語言預設值，repo 可以覆蓋。v2.0.0 的預設值不排除任何改法，也不改逾時和並行。Go 設 `timeout_seconds`、Python 設 `workers` 會印警告，設定沒有作用。
- **一次只開一關**：`gates` 設定哪幾關啟用，沒啟用的關單獨執行時印「還沒啟用」並以 0 結束。新增 `check` 指令，依序跑已啟用的關，第一個沒過就停；`--skip` 略過指定的關，`--json 目錄` 寫出各關的 JSON 報告。
- **現況報告**：CRAP 表加「修改次數」（超標的函式，統計 `baseline.churn_since` 以來改到它的 commit 數，建立的那一次不算），修改次數達到 `baseline.hot_churn` 的標「優先處理」並排在最前面。新增 `baseline --compare 舊.json` 和 `compare 舊.json 新.json`，印出超標函式數、要拆函式數、優先處理數、各套件抓錯率和測到率的前後差。
- **JSON 報告**：`crap`、`mutation`、`check` 加 `--json`（`check` 是目錄）寫出同一份格式，含實際使用的量測工具版本；`baseline` 不用加參數，一律在報告旁邊寫出同名的 `.json`。
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
