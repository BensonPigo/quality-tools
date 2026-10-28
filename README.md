# quality-tools

三重約束裡 CRAP 和變異測試的量測工具，各專案 repo 用 git submodule 掛在 `tools/quality/`。單元測試由各 repo 自己寫，這個工具負責量測那些測試寫得夠不夠好。

專案 repo 要怎麼掛上這個工具，見 `docs/範本_三道防線/專案repo範本/README.md`。這份文件寫給維護工具的人。

## 支援的語言

| 語言 | 狀態 | 覆蓋率和圈複雜度 | 變異測試 |
|---|---|---|---|
| Go | ✅ | `go test -cover` + gocyclo v0.6.0 | gremlins v0.6.0 |
| C# / .NET | ✅ | coverlet + 自製的 CsMetrics（Roslyn） | Stryker.NET 5.0.0 |
| JavaScript / TypeScript | ✅ | Vitest 或 Jest + 自製的 complexity.cjs（TypeScript 解析器） | StrykerJS 10 |
| Python | ✅ | coverage.py + Python 內建的 ast | cosmic-ray 8.7.0 |
| Java | 暫不支援 | — | — |

## 運作方式

```
各語言的量測工具 ──→ lang_<語言>.py 轉成共用格式 ──→ quality.py 判定
                                                    ├─ 找出改到的函式和行
                                                    ├─ 算 CRAP、判斷門檻
                                                    └─ 產生現況報告
```

「找出改到的部分」「判斷門檻」「量現況」只寫一次，所有語言共用。每種語言只需要一個轉換模組，負責執行該語言的工具，再把結果轉成共用格式。`quality.py` 只用 Python 標準函式庫，不用 `pip install`。

`quality.py` 用自己所在的目錄找各語言模組，用執行時的目錄找專案，所以要在專案根目錄執行。工具放在哪裡都可以，各專案 repo 約定放在 `tools/quality/`。

## 檔案

```
quality-tools/
├── quality.py             # 共用判定，指令的進入點
├── common.py
├── lang_go.py             # Go 的量測轉換
├── lang_csharp.py         # C# 的量測轉換
├── lang_js.py             # JavaScript / TypeScript 的量測轉換
├── lang_python.py         # Python 的量測轉換
├── dotnet/CsMetrics/      # C# 圈複雜度的量測程式，第一次使用時自動建置
├── js/complexity.cjs      # JS / TS 圈複雜度的量測程式
├── python/cr_skip_uncovered.py   # cosmic-ray 的過濾器：略過沒被測試執行到的突變體
├── selftest.py            # 工具本身的回歸測試
├── selftest/              # 範例專案和預期結果，每個範例三個檔案：
│                          #   <範例>.sample.txt  範例專案打包成的文字檔
│                          #   <範例>.json        測試情境
│                          #   <範例>.crap.txt    CRAP 表格的快照
├── .github/workflows/selftest.yml  # 每次推送和 PR 跑 selftest.py（GitHub 和 Gitea 都讀得到）
├── docs/
│   ├── 範本_三道防線/      # 專案 repo 要放的設定（.quality.json、.claude/、workflow、CLAUDE.md 片段）和套用步驟
│   ├── 01_單元測試/、02_CRAP指標/、03_變異測試/   # 三重約束的課程和練習程式
│   └── 企業級AI代理人品質驗證與自動化防線架構指南.md
├── CLAUDE.md              # 這個 repo 的寫作規範
└── CHANGELOG.md
```

範例專案有五個：`go`、`csharp`、`ts-vitest`（TypeScript + Vitest 4）、`js-jest`（JavaScript + Jest 30）、`python`，都是同一套購物車程式。

範例不能放成一般的檔案。這個 repo 會整個掛進專案 repo 的 `tools/quality/`，Vitest 和 Jest 會把底下所有的測試檔一起跑（`.` 開頭的目錄也一樣），tsc、ESLint 也會檢查到範例的程式。所以每個範例打包成一個文字檔 `selftest/<範例>.sample.txt`，selftest 執行時才解開到暫存目錄。修改範例的方式見「改版流程」。

## 指令

在專案根目錄執行：

```bash
python tools/quality/quality.py test                          # 第一重：單元測試
python tools/quality/quality.py crap --base origin/main       # 第二重：只檢查改到的函式
python tools/quality/quality.py mutation --base origin/main   # 第三重：只計算改到的行
python tools/quality/quality.py baseline                      # 量現況，寫成 docs/品質現況.md
```

`crap` 和 `mutation` 不加 `--base` 時，檢查整個專案。

結束碼：0 是通過，1 是沒過門檻，2 是量測失敗（例如測試沒過、工具執行失敗）。

「改到的部分」從 `--base` 和目前分支的分岔點算起，包含還沒 commit 的改動和新增的檔案。判斷單位是行：函式的範圍（從宣告那行到結尾）內有任何一行改動，就算改到這個函式，包括只刪除程式行、只改函式裡面的註解。函式外面的註解，以及只有換行字元不同（CRLF 和 LF），不算改到。

## 改版流程

1. 開分支修改，送 PR。
2. CI 跑 `selftest.py`，五個範例都要通過。本機要先跑的話，執行 `python selftest.py`，或只跑改到的語言，例如 `python selftest.py csharp`。五個範例都會跑變異測試，C# 和 Python 最慢。
3. 合併後，在 `CHANGELOG.md` 寫下這版改了什麼、會不會讓原本通過的專案變成沒過，再打版本標籤。
4. 通知各專案 repo。各 repo 自己決定什麼時候升級，步驟見 `docs/範本_三道防線/專案repo範本/README.md`。

版本號的規則：

| 改了什麼 | 版本號 | 例子 |
|---|---|---|
| 修正錯誤，原本通過的專案不會變成沒過 | 第三碼 +1 | v1.0.0 → v1.0.1 |
| 新增語言、新增設定項目，或判定變嚴格 | 第二碼 +1 | v1.0.1 → v1.1.0 |
| 指令或 `.quality.json` 的格式改了，各 repo 要跟著改設定 | 第一碼 +1 | v1.1.0 → v2.0.0 |

標籤打了就不要移動或刪除。各 repo 記錄的是標籤當時的 commit，移動標籤不會改變各 repo 實際用的版本，只會讓版本號和程式對不起來。

### selftest 怎麼測

每個範例都會：

1. 複製到暫存目錄，執行 setup（JS 是 `npm ci`，Python 是建 `.venv` 並安裝 pytest、coverage、cosmic-ray），`git init` 並 commit 到 `main`。
2. 跑 `test`，要通過；跑整個專案的 `crap`，表格要跟 `selftest/<範例>.crap.txt` 一模一樣。
3. 依序跑 `selftest/<範例>.json` 的每個情境：先把工作目錄還原，照 `edits` 改檔案，再執行指令，檢查結束碼和輸出有沒有包含指定的文字。

情境涵蓋：沒改東西、改到沒有測試的舊函式（CRAP 沒過）、只改函式外面的註解、把免運門檻從 1000 改成 999（測試只測了 1000 元，邊界的突變體存活，變異測試沒過）、測試失敗。Go 另外測新增還沒 commit 的檔案。

selftest 的暫存目錄在系統暫存資料夾底下。Windows 的使用者名稱超過 8 個字元或含有 `.` 時，這個路徑通常會是 8.3 短檔名（例如 `C:/Users/ALEXAN~1.LIN`），剛好會測到工具在短檔名目錄下能不能正確對應路徑。

改了圈複雜度或覆蓋率的算法，CRAP 表格一定會變，快照比對就會失敗。確認新的表格是對的之後，用 `python selftest.py --update <範例>` 更新快照，並在 PR 說明為什麼數字變了。

要修改範例專案（例如加一個新的測試情境需要的函式）：

```bash
python selftest.py --unpack go 暫存目錄/go    # 解開成一般的專案
# 在 暫存目錄/go 裡修改、確認能跑
python selftest.py --pack 暫存目錄/go go      # 存回 selftest/go.sample.txt
```

打包時會略過 `node_modules`、`.venv`、`bin`、`obj` 這類安裝或建置產生的目錄，換行字元一律存成 LF。

## 已知限制

| 限制 | 影響 | 處理方式 |
|---|---|---|
| 刪測試、把測試的正確答案改弱 | 工具擋不住 | 審 PR 時看測試檔的 diff |
| 不同語言的圈複雜度和覆蓋率，算法不完全一樣 | 同一個門檻在不同語言的嚴格程度略有差異 | 各語言的算法見下一節。門檻只在同一種語言內比較 |
| 新增一段完全沒有測試的簡單程式碼，三關都會過 | 圈複雜度 1、沒有測試的函式，CRAP 只有 2；變異測試的效能只計算有測試涵蓋的突變體 | 專案的 `.quality.json` 把 `mutant_coverage_threshold` 設成大於 0，例如 50 |

## 各語言注意事項

### Go

- **變異測試會把改到的套件整包跑一次，再過濾出改到的行。** 套件很大時比較慢。gremlins v0.6.0 的 `--diff` 有問題，不能用。
- **函式結尾是用「單獨一行的 `}`」判斷。** 沒經過 gofmt 的程式碼可能判斷錯。Go 專案幾乎都用 gofmt，CI 可以另外加 `gofmt -l` 檢查。
- **覆蓋率按「敘述」計算**，用的是 `go test -cover`。
- gremlins 在 Windows 上執行完，系統暫存資料夾會留下 `gremlins-*` 目錄。只佔空間、不影響結果，要定期手動刪除。

### C# / .NET

- **圈複雜度用自製的 CsMetrics 計算，不用 coverlet 報告裡的複雜度。** coverlet 的複雜度是用編譯後的 IL 算的，大約是原始碼圈複雜度的兩倍，跟門檻 12 比會過度嚴格。CsMetrics 用 Roslyn 解析原始碼，規則對齊 Go 的 gocyclo，再補上 C# 才有的語法（`foreach`、`catch`、`?:`、`??`、switch 運算式、模式比對的 `and`、`or`），完整規則寫在 `Program.cs` 開頭。範例專案的 `Checkout` 在 Go 和 C# 都算出 14。
- **覆蓋率按「行」計算**，用的是 coverlet。同一段邏輯，數字會比 Go 的「敘述覆蓋率」低一些。
- **測試專案要有 `coverlet.collector` 套件。** `dotnet new xunit` 建立的專案預設就有。
- **測試專案的判斷方式**：`.csproj` 裡有 `Microsoft.NET.Test.Sdk`，或是設了 `<IsTestProject>true</IsTestProject>`。變異測試會找出參照到被改專案的所有測試專案一起跑。
- **沒有任何測試專案參照的專案，不會跑變異測試。** 畫面上會印出「沒有測試專案參照它，略過」，CRAP 則照常計算，覆蓋率是 0%。
- **變異測試只突變改到的檔案**（Stryker 的 `--mutate`），再過濾出改到的行，所以比 Go 快。
- **工具放在 `~/.cache/quality-tools`。** Stryker.NET 和 CsMetrics 第一次執行時會自動下載、建置，之後重複使用。不要放在很深的目錄：Windows 上路徑超過 260 字元時，Stryker 會找不到 VSTest 而當掉。可以用環境變數 `QUALITY_TOOLS_DIR` 改位置。
- 在 .NET SDK 10 和 11 預覽版上都驗證過。

### JavaScript / TypeScript

- **StrykerJS 和 Vitest 的版本要搭配好。Vitest 5 搭配 StrykerJS 10.0.0 時，所有突變體都會被判成存活，而且沒有任何錯誤訊息。** 開發者會以為是自己的測試太弱。實測結果：
  | Vitest | StrykerJS | 結果 |
  |---|---|---|
  | 4.1.11 | 10.0.0 | ✅ 正常 |
  | 5.0.3 | 10.0.0 | ❌ 全部存活 |
  | 5.0.3 | 10.1.1 | ✅ 正常 |

  `lang_js.py` 偵測到 Vitest 5 搭配 10.1.1 以前的 StrykerJS 時，會直接停下來並說明原因。
- **圈複雜度用自製的 `complexity.cjs` 計算**，用 TypeScript 的解析器，所以 `.js`、`.ts`、`.jsx`、`.tsx` 都能讀。規則對齊 Go 的 gocyclo，完整規則寫在檔案開頭。沒有用 ESLint 的 `complexity` 規則，因為規則細節由 ESLint 決定，會隨版本改變；自己寫才能跟其他語言保持同一套算法。另外也省掉每個專案設定 ESLint 和 TypeScript 外掛的麻煩。
- **哪些算一個函式**：最外層的函式宣告、class 的方法，以及指定給變數或屬性的箭頭函式，例如 `const f = () => {...}`。函式裡面的 callback 算進外層的函式。
- **覆蓋率按「敘述」計算**，跟 Go 一樣。範例專案的 `checkout` 在 Go 和 TypeScript 都是 73.9%。
- **測試檔的判斷方式**：檔名是 `*.test.*`、`*.spec.*`，或放在 `__tests__/` 底下。`*.d.ts` 和 `*.config.*` 不算原始碼。
- **「套件」是 `package.json` 所在的目錄**，monorepo 的每個子套件分開跑。現況報告的變異測試表依資料夾分組。
- **變異測試只突變改到的檔案**（StrykerJS 的 `mutate`），再過濾出改到的行。
- 在 Node 24 上驗證過。StrykerJS 10 需要 Node 22 以上。

### Python

- **變異測試用 cosmic-ray，不用 mutmut。** mutmut 需要 `fork`，官方說明在 Windows 上要透過 WSL 才能跑。
- **cosmic-ray 會直接改原始碼檔案，跑完再改回來。** 中途被打斷，就會留下改壞的程式，所以 `lang_python.py` 一律把專案複製到暫存目錄再跑，不會動到工作目錄。
- **測試輸出一律用 UTF-8。** 測試名稱或錯誤訊息有中文時，Windows 預設用 Big5 輸出，cosmic-ray 用 UTF-8 讀會出錯，把被殺死的突變體誤判成無效。`lang_python.py` 會設定 `PYTHONUTF8=1` 避開這個問題。
- **沒被測試執行到的突變體不會真的去跑**，而是用 `python/cr_skip_uncovered.py` 先標成「沒覆蓋」。cosmic-ray 本身不看覆蓋率，每個突變體都會把全部測試跑一次，沒被執行到的突變體也會被判成「存活」，既浪費時間又不正確。
- **圈複雜度用 Python 內建的 `ast` 模組計算**，不用另外安裝 radon。規則對齊 Go 的 gocyclo，再補上 Python 才有的語法（生成式裡的 `for`、`if`，條件運算式，`match`），完整規則寫在 `lang_python.py` 的 `_complexity`。
- **覆蓋率按「敘述」計算，從函式本體的第一行算起。** `def` 那一行在載入模組時就會執行，不能算成函式有被測試。
- **docstring 在函式裡面，改 docstring 會算成改到這個函式。** 寫在 `def` 上方的 `#` 註解則不算。
- **測試框架只支援 pytest。** 測試檔的判斷方式：檔名是 `test_*.py`、`*_test.py`、`conftest.py`，或放在 `tests/`、`test/` 底下。
- **變異測試比其他語言慢**：cosmic-ray 每個突變體都會重新啟動一次 pytest。範例專案改一行，大約 14 秒。

## 新增一種語言

新增 `lang_<語言>.py`，提供以下內容：

| 名稱 | 說明 |
|---|---|
| `SOURCE_GLOBS` | 原始碼的檔名樣式，例如 `["*.go"]` |
| `is_test(path)` | 這個檔案是不是測試檔 |
| `package_dir(path)` | 這個檔案屬於哪個套件（變異測試以套件為單位執行，現況報告也以套件分組） |
| `report_group(path)` | 選用。現況報告想用比套件更細的單位分組時才需要，例如 JS 依資料夾分組 |
| `run_tests(cfg)` | 執行單元測試，回傳結束碼 |
| `measure_functions(cfg)` | 回傳每個函式：`{file, name, start, end, complexity, coverage}`，coverage 是 0～1 |
| `measure_mutants(cfg, dirs=None, files=None)` | 對 `dirs` 這些套件跑變異測試（`None` 表示全部），回傳每個突變體：`{file, line, status, mutator}`。`files` 是改到的檔案，工具支援的話，可以只突變這些檔案來加快速度；不支援就忽略，`quality.py` 會再過濾 |

`file` 一律是相對於專案根目錄、用 `/` 分隔的路徑。`status` 是 `KILLED`、`TIMED_OUT`、`LIVED`、`NOT_COVERED`、`NOT_VIABLE`、`SKIPPED` 其中之一。測試沒過或工具執行失敗時，丟出 `common.QualityError`。

同時在 `selftest/` 加一個購物車範例（寫好之後用 `--pack` 打包）和它的情境，CI 也要裝好這個語言的工具。

## 驗證狀態

| 項目 | 狀態 |
|---|---|
| `selftest.py` | 在本機（Windows + Git Bash + Python 3.12、Go 1.27、.NET SDK 10、Node 24）和 GitHub Actions 的 Linux 上，五個範例全部通過 |
| 各語言模組 | 範例專案的 CRAP 表格：`Checkout` 的圈複雜度在 Go、C#、TypeScript、Python 範例都是 14（JavaScript + Jest 範例只有運費模組）；敘述覆蓋率在 Go、TypeScript、Python 都是 73.9%，C# 是行覆蓋率 60.5% |
| 掛成 submodule 使用 | 在本機用 git 模擬過完整流程（見 `docs/範本_三道防線/專案repo範本/README.md` 的驗證狀態） |
| `.github/workflows/selftest.yml` | 在 GitHub Actions（ubuntu-latest）上五個範例全部通過，約 3 分鐘。還沒在 Gitea 上跑過 |
