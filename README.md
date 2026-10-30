# quality-tools

三道檢查（單元測試、CRAP、抓錯檢查）的量測工具，目前是 v2.0.0。單元測試由各 repo 自己寫，這個工具負責量那些測試寫得夠不夠好：算 CRAP 分數、故意把程式改壞看測試抓不抓得到，並且只檢查這次改到的函式和行。

這份文件寫給維護工具的人。專案 repo 要怎麼掛上這個工具，見 `docs/範本_三道防線/專案repo範本/README.md`。三道檢查為什麼這樣設計，見 `docs/導入步驟_三道檢查.md`。

## 用詞對照

畫面、報告和設定檔用左邊的白話說法，右邊是工具和網路文章裡的名詞。

| 白話說法 | 意思 | 工具和文章裡的名詞 |
|---|---|---|
| 抓錯檢查 | 工具故意把程式改壞，看測試抓不抓得到 | 變異測試（Mutation Testing），指令是 `mutation` |
| 改壞的版本 | 工具改壞程式的每一種改法，例如把 `>=` 改成 `>` | 突變體（Mutant） |
| 抓到 / 沒抓到 | 改壞之後測試會失敗是抓到，測試照樣通過是沒抓到 | 殺死（Killed）/ 存活（Survived） |
| 抓錯率 | 有測到的改壞版本裡，抓到幾成 | 效能（Mutation Score、Efficacy） |
| 測到率 | 全部改壞版本裡，有幾成被測試跑到 | 突變體覆蓋率（Mutant Coverage） |
| 改了也沒差的版本 | 怎麼改，程式的結果都一樣，所以不可能抓到 | 等價突變體（Equivalent Mutant） |

## 支援的語言

| 語言 | 覆蓋率和圈複雜度 | 抓錯檢查 | 工具版本誰管 |
|---|---|---|---|
| Go | `go test -cover` + gocyclo v0.6.0 | gremlins v0.6.0 | 本工具，用 `go run ...@版本` 執行 |
| C# / .NET | coverlet + 自製的 CsMetrics（Roslyn） | Stryker.NET 5.0.0 | 本工具，第一次執行時裝到快取目錄 |
| JavaScript / TypeScript | Vitest 或 Jest + 自製的 `complexity.cjs`（TypeScript 解析器 5.9.3） | StrykerJS | 解析器由本工具裝到快取目錄；StrykerJS 由各 repo 的 `package.json` 安裝 |
| Python | coverage.py + Python 內建的 `ast` | cosmic-ray | 各 repo 的 Python 環境安裝 |

Java、PHP 暫不支援。

StrykerJS 和 cosmic-ray 要跟專案的測試框架裝在一起，版本由各 repo 決定。工具讀實際安裝的版本，不在驗證清單內就以結束碼 2 結束，訊息列出驗證過的版本，分數才不會因為各 repo 自行升級而飄掉：

| 工具 | 驗證過的版本 | 搭配 |
|---|---|---|
| StrykerJS core 和 runner | 10.0.0 | Vitest 4、Jest 30 |
| StrykerJS core 和 runner | 10.1.1 | Vitest 4、Vitest 5 |
| cosmic-ray | 8.7.0 | pytest |

要支援新版本時，改 `qtools/langs/js.py` 的 `STRYKER_VERIFIED` 或 `qtools/langs/python.py` 的 `COSMIC_RAY_VERIFIED`，跑 selftest，再發新版。實際用到的量測工具版本寫在 JSON 報告的 `tools` 欄位。

## 運作方式

```
各語言的量測工具 ──→ qtools/langs/<語言>.py 轉成共用格式 ──→ qtools 核心判定
                                                         ├─ 找出改到的函式和行
                                                         ├─ 算 CRAP、抓錯率、測到率，判斷門檻
                                                         ├─ 比對改了也沒差的版本排除清單
                                                         └─ 輸出文字報告、JSON 報告、現況報告
```

「找出改到的部分」「判斷門檻」「量現況」只寫一次，四種語言共用。每種語言的模組只負責執行該語言的工具，再把結果轉成 `Function` 和 `Mutant`。工具只用 Python 標準函式庫，需要 Python 3.8 以上。

在專案根目錄執行。工具放在哪裡都可以：submodule 放 `tools/quality/`，用 pip 安裝則直接執行 `quality`。

「改到的部分」從 `--base` 和目前分支的分岔點算起，包含還沒 commit 的改動和新增的檔案。判斷單位是行：函式的範圍（從宣告那行到結尾）內有任何一行改動，就算改到這個函式，包括只刪除程式行、只改函式裡面的註解。函式外面的註解，以及只有換行字元不同（CRLF 和 LF），不算改到。

## 檔案

```
quality-tools/
├── quality.py                 # 進入點，只呼叫 qtools.cli.main
├── pyproject.toml             # pip 安裝設定，指令 quality
├── qtools/
│   ├── cli.py                 # 指令解析、各指令流程、結束碼
│   ├── config.py              # .quality.json v2：預設值、驗證、migrate
│   ├── model.py               # Function、Mutant、狀態和白話名稱
│   ├── changes.py             # git diff → 改到的行
│   ├── crap.py                # CRAP、拆函式或補測試的建議
│   ├── mutation.py            # 抓錯率、測到率、改壞版本的描述
│   ├── equivalents.py         # 讀 .quality-equivalents.json 並比對
│   ├── report.py              # 文字輸出和 JSON 報告
│   ├── report_schema.py       # JSON 報告的欄位和型別
│   ├── baseline.py            # 現況報告、修改次數、比較
│   ├── proc.py                # 執行外部指令、路徑、快取目錄
│   ├── langs/                 # base.py 是介面；go.py、csharp.py、js.py、python.py 各自轉換
│   └── helpers/               # 量測用的輔助程式（pip 安裝會一起帶走）
│       ├── dotnet/CsMetrics/  #   C# 圈複雜度，第一次使用時自動建置
│       ├── js/complexity.cjs  #   JS / TS 圈複雜度
│       └── python/cr_skip_uncovered.py   # cosmic-ray 的過濾器：略過測試沒跑到的改壞版本
├── selftest.py                # 工具本身的回歸測試
├── selftest/                  # 範例專案和預期結果，每個範例三個檔案：
│                              #   <範例>.sample.txt  範例專案打包成的文字檔
│                              #   <範例>.json        測試情境
│                              #   <範例>.crap.txt    CRAP 表格的快照
├── dev/
│   ├── unit_checks.py         # 不需要語言工具的純函式測試（selftest 開頭會先跑）
│   ├── v1_parity.py           # v2 和 v1.0.0 的分數對照
│   └── v1-parity.json         # v1.0.0 的記錄結果
├── .github/workflows/
│   ├── selftest.yml           # 每次推送和 PR 跑 selftest.py
│   └── quality.yml            # reusable workflow，給專案 repo 一行引用
├── docs/
│   ├── 範本_三道防線/          # 專案 repo 要放的設定和套用步驟
│   ├── 01_單元測試/、02_CRAP指標/、03_變異測試/   # 三道檢查的課程和練習程式
│   ├── 導入步驟_三道檢查.md
│   └── 企業級AI代理人品質驗證與自動化防線架構指南.md
├── CLAUDE.md                  # 這個 repo 的寫作規範
└── CHANGELOG.md
```

範例專案有五個：`go`、`csharp`、`ts-vitest`（TypeScript + Vitest 4）、`js-jest`（JavaScript + Jest 30）、`python`，都是同一套購物車程式。

範例不能放成一般的檔案。這個 repo 會整個掛進專案 repo 的 `tools/quality/`，Vitest 和 Jest 會把底下所有的測試檔一起跑（`.` 開頭的目錄也一樣），tsc、ESLint 也會檢查到範例的程式。所以每個範例打包成一個文字檔 `selftest/<範例>.sample.txt`，selftest 執行時才解開到暫存目錄。`dev/unit_checks.py` 的檔名刻意不符合 `test_*.py`、`*_test.py`、`*.test.*`，專案的 pytest、Vitest、Jest 預設不會收進來。

## 指令

在專案根目錄執行。submodule 的寫法是 `python tools/quality/quality.py <指令>`，pip 安裝的寫法是 `quality <指令>`，兩者參數相同。

| 指令 | 說明 |
|---|---|
| `test` | 第一關：單元測試 |
| `crap [--base B] [--json 檔名]` | 第二關：CRAP。加 `--base` 只檢查改到的函式，並且在超標的函式後面標出改善方向；不加則檢查整個專案 |
| `mutation [--base B] [--json 檔名]` | 第三關：抓錯檢查。加 `--base` 只計算改到的行；不加則計算整個專案 |
| `check [--base B] [--skip 名稱 ...] [--json 目錄]` | 依 `gates` 的啟用狀態，照 test、crap、mutation 的順序跑，第一個沒過就停。`--base` 沒給就用 `.quality.json` 的 `base`。`--skip` 可以接多個關名，AI 結束前的自動檢查用 `--skip mutation`。`--json 目錄` 把 crap、mutation 兩關各寫成 `crap.json`、`mutation.json`，沒跑到的關不寫檔 |
| `baseline [--out 檔名] [--compare 舊.json]` | 量整個專案的現況，寫成 `baseline.out`（預設 `docs/品質現況.md`）和同名的 `.json`。CRAP 表有「修改次數」和「優先處理」。加 `--compare` 時，量完跟舊的現況報告比較，印出前後差，並在 markdown 最後加「## 跟上一次比較」 |
| `compare 舊.json 新.json` | 不量測，只比較兩份現況報告（JSON），印出前後差 |
| `migrate` | 把專案根目錄的 v1 `.quality.json` 改寫成 v2，並印出前後差異 |

結束碼：

| 碼 | 意思 |
|---|---|
| 0 | 通過 |
| 1 | 沒過門檻 |
| 2 | 量測失敗或設定有誤（例如測試沒過、工具執行失敗、`.quality.json` 有未知的鍵、排除清單格式錯誤、工具版本不在驗證清單） |

`compare` 只呈現前後差，不判定，讀得了兩份報告就是 0；讀不了、格式不符、或不是現況報告是 2。

單獨執行 `test`、`crap`、`mutation` 時，如果該關不在 `gates` 裡，會印「第 N 關（名稱）還沒啟用」並以結束碼 0 結束，不跑量測；有加 `--json` 時，寫出 `result` 為 `skipped` 的報告。

`check` 開頭印「比較基準：<base>」，每一關印「== 第 N 關：名稱 ==」，第一個沒過的關以那一關的結束碼結束，並印「停在第 N 關」；全部通過印「PASS：已啟用的 K 關都通過（略過：…；還沒啟用：…）」。`--skip` 給了不認得的關名是結束碼 2。

## 設定檔：`.quality.json`

專案根目錄的 `.quality.json`，鍵名用白話名稱。未知的鍵、型別不對、缺 `version` 或用了 v1 的鍵名，都以結束碼 2 結束，不會默默變成預設值。v1 的檔案讀到時，訊息會叫人執行 `migrate`。

```json
{
  "version": 2,
  "language": "go",
  "base": "origin/main",
  "gates": ["test", "crap", "mutation"],
  "exclude": ["tools/", "vendor/", "node_modules/"],
  "crap": { "threshold": 12 },
  "mutation": {
    "kill_rate_threshold": 80,
    "reach_rate_threshold": 50,
    "timeout_seconds": null,
    "workers": null,
    "exclude_mutators": null,
    "equivalents_file": ".quality-equivalents.json"
  },
  "baseline": { "out": "docs/品質現況.md", "churn_since": "6 months ago", "hot_churn": 5 },
  "csharp": { "solution": null },
  "js": { "test_runner": null },
  "python": { "interpreter": null }
}
```

沒寫的鍵用上面的預設值。`language` 沒有預設值，一定要寫。

| 鍵 | 預設 | 說明 |
|---|---|---|
| `version` | 必填 | 固定是 `2` |
| `language` | 必填 | `go`、`csharp`、`js`（JavaScript 和 TypeScript 都用 `js`）、`python` |
| `base` | `"origin/main"` | 比較基準。主分支叫 `master` 就改成 `origin/master` |
| `gates` | `["test","crap","mutation"]` | 啟用哪幾關，合法值是 `test`、`crap`、`mutation`。執行順序固定是 test → crap → mutation，跟陣列裡的排列無關 |
| `exclude` | `["tools/","vendor/","node_modules/"]` | 不量測的目錄 |
| `crap.threshold` | `12` | CRAP 門檻 |
| `mutation.kill_rate_threshold` | `80` | 抓錯率門檻（百分比） |
| `mutation.reach_rate_threshold` | `50` | 測到率門檻（百分比） |
| `mutation.timeout_seconds` | `null` | 每個改壞版本的逾時秒數，正數。`null` 用該語言的預設值，見下表 |
| `mutation.workers` | `null` | 同時跑幾個，正整數。`null` 用該語言的預設值 |
| `mutation.exclude_mutators` | `null` | 要排除的改法名稱，字串陣列。名稱是各工具報告裡的名稱，也就是 JSON 報告 `mutation.mutants[].mutator` 的值。`null` 用該語言的預設值（不排除任何改法） |
| `mutation.equivalents_file` | `".quality-equivalents.json"` | 改了也沒差的版本排除清單的檔名，檔案不存在等於空清單 |
| `baseline.out` | `"docs/品質現況.md"` | 現況報告的檔名，JSON 寫到同名的 `.json` |
| `baseline.churn_since` | `"6 months ago"` | 修改次數從什麼時候算起，傳給 `git log --since` |
| `baseline.hot_churn` | `5` | 超標的函式，修改次數達到這個數字就標「優先處理」 |
| `csharp.solution` | `null` | 根目錄有多個 `.sln` 或 `.slnx` 時，指定要測哪一個 |
| `js.test_runner` | `null` | `"vitest"`、`"jest"` 或 `null`。`null` 依 `package.json` 自動判斷 |
| `python.interpreter` | `null` | 執行測試用的 Python。`null` 用專案根目錄的 `.venv`，沒有的話用執行 `quality.py` 的那個 Python |

`reach_rate_threshold` 預設 50，原因是抓錯率只算有被測試跑到的改壞版本，一段完全沒有測試的新程式不會讓抓錯率下降，CRAP 也不一定擋得住（圈複雜度 1、沒有測試的函式只有 2 分）。

### 工具預設值

`timeout_seconds`、`workers`、`exclude_mutators` 寫 `null` 時，用語言模組的 `DEFAULTS`。v2.0.0 的預設不排除任何改法，也不改逾時和並行，分數才能跟 v1 和各 repo 第 0 步的報告比較。之後要調預設值時，發第二碼版本。實際生效的值寫進 JSON 報告的 `mutation.settings`，文字輸出也會印一行「設定：逾時 …、同時跑 …、排除改法 …」。

| 語言 | `timeout_seconds` | `workers` | `exclude_mutators` |
|---|---|---|---|
| Go（gremlins） | 不支援，設了會在 stderr 印警告。固定用 `--timeout-coefficient 30` | 傳給 `--workers`；`null` 用 gremlins 的預設 | 預設不排除；只在核心過濾 |
| C#（Stryker.NET） | 秒數 × 1000 寫成 `additional-timeout`（毫秒，加在依正常測試時間算出的時限之外），放在暫存的設定檔，用 `--config-file` 傳入，用完即刪 | 傳給 `--concurrency` | 預設不排除；只在核心過濾 |
| JS / TS（StrykerJS） | 秒數 × 1000 傳給 `timeoutMS`，意義同上 | 傳給 `concurrency` | 預設不排除；傳給 `mutator.excludedMutations`，StrykerJS 就不會產生這些改壞版本，省時間；核心也會標記 |
| Python（cosmic-ray） | 預設 30 秒，每個改壞版本的總時限（同 v1） | 不支援，設了會在 stderr 印警告 | 預設不排除；只在核心過濾 |

`timeout_seconds` 為 `null` 時，一律不傳參數給工具。

## 狀態與兩個比例

每個改壞版本有一個狀態，畫面用白話名稱：

| 畫面 | 內部狀態 | 抓錯率 | 測到率 |
|---|---|---|---|
| 抓到 | `KILLED` | 分子、分母 | 分子、分母 |
| 逾時（算抓到） | `TIMED_OUT` | 分子、分母 | 分子、分母 |
| 沒抓到 | `LIVED` | 分母 | 分子、分母 |
| 測試沒跑到 | `NOT_COVERED` | 不算 | 分母 |
| 已排除：改了也沒差 | `EQUIVALENT` | 不算 | 不算 |
| 已排除：設定排除的改法 | `EXCLUDED_MUTATOR` | 不算 | 不算 |
| 無效、略過 | `NOT_VIABLE`、`SKIPPED` | 不算 | 不算 |

- 抓錯率 =（抓到 + 逾時）÷（抓到 + 逾時 + 沒抓到）
- 測到率 =（抓到 + 逾時 + 沒抓到）÷（抓到 + 逾時 + 沒抓到 + 測試沒跑到）

分母為 0 時，比例顯示「—」，不拿來跟門檻比。任何一個比例低於門檻，`mutation` 就以結束碼 1 結束。

每個沒抓到和測試沒跑到的改壞版本印一行：

```
沒抓到  shipping/fee.go:5  把 `>=` 改成 `>`  ｜ if total >= 1000 {
```

工具報告不提供「改成什麼」時（gremlins 和 cosmic-ray 靠對照表推算，對照表沒有的改法就推算不出來），退回印 `改法 <改法名稱>  ｜ <該行原文>`。

## 改了也沒差的版本：排除清單

`.quality-equivalents.json` 放在各 repo 的根目錄，內容是陣列，每一項描述一個改了也沒差的改壞版本：

```json
[
  {
    "file": "shipping/fee.go",
    "function": "Fee",
    "line_text": "if total >= 1000 {",
    "mutator": "CONDITIONALS_BOUNDARY",
    "reason": "total 是整數，滿 1000 免運的邊界在需求裡沒有差別",
    "approved_by": "王小明"
  }
]
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| `file` | 是 | 相對於專案根目錄的路徑 |
| `mutator` | 是 | 改法名稱，取自 JSON 報告 `mutation.mutants[].mutator` |
| `line_text` | 是 | 該行去頭尾空白後的原文 |
| `reason` | 是 | 為什麼改了也沒差 |
| `approved_by` | 是 | 誰核准的 |
| `function` | 否 | 只用來顯示和人工檢查，不參與比對 |

比對規則：`file`、`mutator`、`line_text` 三者都相同，這個改壞版本就標成「已排除：改了也沒差」，不算進抓錯率和測到率。不用行號，前面插幾行程式碼也還對得上；那一行的原文被改了，項目就失效，要人重新判斷，這是刻意的設計。

- 檔案不存在等於空清單。不是陣列、缺必填欄位、欄位不是非空白字串、出現不認得的鍵，都以結束碼 2 結束，訊息指出第幾項。
- 清單裡沒對到任何改壞版本的項目，輸出會列成「排除清單有 N 項沒用到」，並寫進 JSON 的 `mutation.unused_equivalents`，不影響結束碼。用 `--base` 時，只計算 `file` 在這次量測範圍內的項目，沒改到的檔案不算沒用到。
- `mutation` 和 `baseline` 都套用排除清單。
- 排除清單要鎖起來：專案 repo 用 CODEOWNERS 和 AI 工具的權限設定保護這個檔案，改了要人核准（範本見 `docs/範本_三道防線/專案repo範本/`）。

## JSON 報告

`crap`、`mutation`、`check --json 目錄`、`baseline` 寫出的 JSON 用同一份格式，欄位和型別定義在 `qtools/report_schema.py`，多或少欄位都算格式不符。頂層欄位：`schema`（目前是 1）、`command`、`tool_version`、`language`、`base`、`commit`、`result`（`pass`、`fail` 或 `skipped`）、`tools`（實際用到的量測工具版本）、`crap`、`mutation`。`crap` 指令的 `mutation` 是 `null`，`mutation` 指令的 `crap` 是 `null`，`baseline` 兩者都有。`result` 是 `skipped` 時兩者都是 `null`。

`mutation.mutants[].function` 目前一律是 `null`。

## 發布方式

三種方式可以並用。不管用哪一種，都要固定版本：工具一更新、判斷變嚴格，所有 repo 會同時變紅，所以讓各 repo 自己決定什麼時候升級。

### git submodule

各 repo 掛在 `tools/quality/`，指向某個版本標籤，步驟見 `docs/範本_三道防線/專案repo範本/README.md`。執行方式 `python tools/quality/quality.py <指令>`。

### pip

```bash
pip install "quality-tools @ git+https://<主機>/<組織>/quality-tools@v2.0.0"
quality check --base origin/main
```

套件名 `quality-tools`，指令 `quality`。輔助程式放在 `qtools/helpers/` 底下，會一起裝進去。

### reusable workflow

`.github/workflows/quality.yml` 是 `workflow_call` 的 workflow，專案 repo 的 CI 只要一個 job 引用它：

```yaml
jobs:
  quality:
    uses: <組織>/quality-tools/.github/workflows/quality.yml@v2.0.0
    with:
      language: go
      tools-ref: v2.0.0
    secrets:
      tools-token: ${{ secrets.QUALITY_TOOLS_TOKEN }}   # quality-tools 是私有 repo 時才需要
```

範例見 `docs/範本_三道防線/專案repo範本/workflows/reusable-caller.yml`。

**`tools-ref` 必須和 `uses:` 後面 `@` 的 ref 相同**，兩處要一起改。被呼叫的 workflow 沒有文件記載的方式取得自己被引用的 ref，所以 workflow 靠 `tools-ref` 決定要把哪一版的工具 checkout 下來。兩個填不一樣時，workflow 本身是第二個版本、跑的工具卻是第一個版本。

inputs：

| 名稱 | 必填 | 預設 | 說明 |
|---|---|---|---|
| `language` | 是 | | `go`、`csharp`、`js`、`python` |
| `tools-ref` | 是 | | quality-tools 的標籤或 commit，要跟 `uses` 的 ref 相同 |
| `tools-repository` | 否 | `<呼叫端的擁有者>/quality-tools` | quality-tools 不在同一個擁有者底下時填 |
| `go-version-file` | 否 | `go.mod` | |
| `dotnet-version` | 否 | `8.0.x` | |
| `node-version` | 否 | `22` | StrykerJS 10 需要 Node 22 以上 |
| `python-version` | 否 | `3.12` | |
| `install` | 否 | 空 | 安裝專案相依套件的指令，例如 `npm ci`、`pip install -r requirements-dev.txt` |
| `skip` | 否 | 空 | 不跑的關，空白分隔，例如 `mutation` |

secret：`tools-token`（選用）。quality-tools 是私有 repo 時，預設的 `GITHUB_TOKEN` 讀不到它，要建一個能讀 quality-tools 的存取權杖，存成呼叫端的密鑰後傳進來。沒給時用預設權杖。

步驟：

1. checkout 專案，`fetch-depth: 0`、`submodules: false`。專案如果有掛 `tools/quality` 這個 submodule，而 quality-tools 又是私有 repo，預設權杖讀不到 submodule，抓 submodule 的步驟會直接失敗，所以這裡不抓。
2. 依 `language` 設定語言環境，執行 `install`。
3. 把 quality-tools 的 `tools-ref` checkout 到 `.quality-tools-pin`。
4. **比對 submodule 版本**：用 `git ls-tree HEAD tools/quality` 讀專案記錄的 submodule commit（不需要抓 submodule 內容）。專案沒有這筆記錄（沒用 submodule），直接用 pin。有記錄的話，跟 `.quality-tools-pin` 的 commit 比對，不同就失敗，訊息是「submodule 記錄的版本和 tools-ref 不一致」。目的是避免開發者本機和 AI 用 submodule 的版本，CI 卻用 `tools-ref` 的另一個版本。
5. 把 `.quality-tools-pin` 搬成 `tools/quality`（原本是空的 submodule 目錄就先刪掉），快取 `~/.cache/quality-tools`，key 含 `tools/quality/qtools/helpers/**` 和 `tools/quality/qtools/langs/**` 的雜湊。
6. 依序執行「第一關：單元測試」`test`、「第二關：CRAP」`crap --base origin/<base_ref>`、「第三關：抓錯檢查」`mutation --base origin/<base_ref>`。`skip` 有列的關不跑；`gates` 沒啟用的關，指令本身印「還沒啟用」後以 0 結束。

這個 workflow 只對 `pull_request` 觸發的呼叫有用：`github.base_ref` 只有 PR 事件才有值。

## 改版流程

1. 開分支修改，送 PR。
2. CI 跑 `selftest.py`，五個範例都要通過。
3. 改了量測的程式，在發新版之前跑 `python dev/v1_parity.py check`，確認分數跟 v1.0.0 一致，或是有意的改變並寫進 `CHANGELOG.md`。
4. 合併後，在 `CHANGELOG.md` 寫下這版改了什麼、原本通過的專案會不會變成沒過、專案 repo 要不要跟著改設定，再打版本標籤。
5. 通知各專案 repo。各 repo 自己決定什麼時候升級，步驟見 `docs/範本_三道防線/專案repo範本/README.md`。

版本號的規則：

| 改了什麼 | 版本號 | 例子 |
|---|---|---|
| 修正錯誤，原本通過的專案不會變成沒過 | 第三碼 +1 | v2.0.0 → v2.0.1 |
| 新增語言、新增設定項目，或判定變嚴格（包含調整語言預設值） | 第二碼 +1 | v2.0.1 → v2.1.0 |
| 指令或 `.quality.json` 的格式改了，各 repo 要跟著改設定 | 第一碼 +1 | v2.1.0 → v3.0.0 |

發新版時，`pyproject.toml` 的 `version` 和 `qtools/__init__.py` 的 `__version__` 要一起改成新版本號，JSON 報告的 `tool_version` 讀的是後者。

標籤打了就不要移動或刪除。各 repo 記錄的是標籤當時的 commit，移動標籤不會改變各 repo 實際用的版本，只會讓版本號和程式對不起來。

## selftest 和 v1_parity

### selftest

```bash
python selftest.py                 # 全部範例
python selftest.py go python       # 只跑指定的範例
python selftest.py --update go     # 確認新的 CRAP 表格是對的之後，更新快照
```

需要先裝好各語言的工具：Go、.NET SDK、Node（StrykerJS 10 需要 22 以上）、Python 3.8 以上；Windows 上 gate.sh 的情境需要 Git Bash。開頭先跑 `dev/unit_checks.py`，沒過就整體失敗。

每個範例都會：

1. 把本工具 `git ls-files` 列出的檔案複製到範例的 `tools/quality/`，模擬 submodule 掛載；執行 setup（JS 是 `npm ci`，Python 是建 `.venv` 並安裝 pytest、coverage、cosmic-ray），`git init` 並 commit 到 `main`。
2. 跑 `test`，要通過；跑整個專案的 `crap`，表格要跟 `selftest/<範例>.crap.txt` 一模一樣。
3. 依序跑 `selftest/<範例>.json` 的每個情境：先 `git reset --hard` 回初始 commit 並 `git clean`，照 `edits` 改檔案，執行指令，檢查結束碼、輸出文字，以及 `--json` 寫出的檔案是否符合格式。

情境涵蓋：沒改東西、改到沒有測試的舊函式（CRAP 沒過）、只改函式外面的註解、把免運門檻從 1000 改成 999（改壞的版本沒被抓到）、測試失敗；排除清單、`exclude_mutators`、`timeout_seconds` 和 `workers`、`gates`、`check`、v1 設定與 `migrate`、現況報告的修改次數與 `compare`、範本 `gate.sh`。

selftest 的暫存目錄在系統暫存資料夾底下。Windows 的使用者名稱超過 8 個字元或含有 `.` 時，這個路徑通常會是 8.3 短檔名（例如 `C:/Users/ALEXAN~1.LIN`），剛好會測到工具在短檔名目錄下能不能正確對應路徑。

改了圈複雜度或覆蓋率的算法，CRAP 表格一定會變，快照比對就會失敗。確認新的表格是對的之後，用 `--update` 更新快照，並在 PR 說明為什麼數字變了。

要修改範例專案（例如加一個新的測試情境需要的函式）：

```bash
python selftest.py --unpack go 暫存目錄/go    # 解開成一般的專案
# 在 暫存目錄/go 裡修改、確認能跑
python selftest.py --pack 暫存目錄/go go      # 存回 selftest/go.sample.txt
```

打包時會略過 `node_modules`、`.venv`、`bin`、`obj` 這類安裝或建置產生的目錄，換行字元一律存成 LF。

### v1_parity

```bash
python dev/v1_parity.py check              # 全部範例
python dev/v1_parity.py check go python    # 只跑指定的範例
python dev/v1_parity.py record             # 重新用 v1.0.0 記錄（一般不需要）
```

`check` 用目前的工具對五個範例跑整個專案的 `crap --json` 和 `mutation --json`，跟 `dev/v1-parity.json`（v1.0.0 的記錄）比對：CRAP 表每一列逐列完全相同；抓到 + 逾時的合計、沒抓到、測試沒跑到三個數字完全相同。抓到和逾時會因為機器負載互換，所以合計比對。有差異時自動重跑該範例一次，仍然不同就結束碼 1。`record` 會用 `git worktree` 取出 `v1.0.0` 重新記錄。

## 已知限制

| 限制 | 影響 | 處理方式 |
|---|---|---|
| 刪測試、把測試的正確答案改弱 | 工具擋不住 | 審 PR 時看測試檔的 diff |
| 不同語言的圈複雜度和覆蓋率，算法不完全一樣 | 同一個門檻在不同語言的嚴格程度略有差異 | 各語言的算法見下一節。門檻只在同一種語言內比較 |
| 新增一段完全沒有測試的簡單程式碼，CRAP 和抓錯率都擋不住 | 圈複雜度 1、沒有測試的函式，CRAP 只有 2；抓錯率只算有測試涵蓋的改壞版本 | 設 `mutation.reach_rate_threshold`（預設 50）。從 v1 `migrate` 來的設定保留 v1 的值，沒寫過就是 0，要手動調 |
| gremlins 和 cosmic-ray 取得「改成什麼」靠對照表推算 | 對照表沒有的改法，輸出退回「改法 名稱」和該行原文，不影響分數 | 在 `qtools/langs/go.py`、`python.py` 補對照表 |
| `mutation.mutants[].function` 一律是 `null` | 報告看不到改壞版本所在的函式名稱 | 看 `file` 和 `line` |
| Go 不支援 `timeout_seconds`，Python 不支援 `workers` | 設了只印警告，不生效 | 見「工具預設值」 |
| `gate.sh`（AI 結束前的自動檢查）找 `tools/quality/quality.py` | 只用 pip 安裝、沒掛 submodule 的 repo，`gate.sh` 照範本不能用 | 要把 `gate.sh` 裡的呼叫改成 `quality check ...`，這個改法沒有測過 |

## 各語言注意事項

### Go

- **抓錯檢查會把改到的套件整包跑一次，再過濾出改到的行。** 套件很大時比較慢。gremlins v0.6.0 的 `--diff` 有問題，不能用。
- **函式結尾是用「單獨一行的 `}`」判斷。** 沒經過 gofmt 的程式碼可能判斷錯。Go 專案幾乎都用 gofmt，CI 可以另外加 `gofmt -l` 檢查。
- **覆蓋率按「敘述」計算**，用的是 `go test -cover`。
- gremlins 在 Windows 上執行完，系統暫存資料夾會留下 `gremlins-*` 目錄。只佔空間、不影響結果，要定期手動刪除。

### C# / .NET

- **圈複雜度用自製的 CsMetrics 計算，不用 coverlet 報告裡的複雜度。** coverlet 的複雜度是用編譯後的 IL 算的，大約是原始碼圈複雜度的兩倍，跟門檻 12 比會過度嚴格。CsMetrics 用 Roslyn 解析原始碼，規則對齊 Go 的 gocyclo，再補上 C# 才有的語法（`foreach`、`catch`、`?:`、`??`、switch 運算式、模式比對的 `and`、`or`），完整規則寫在 `qtools/helpers/dotnet/CsMetrics/Program.cs` 開頭。範例專案的 `Checkout` 在 Go 和 C# 都算出 14。
- **覆蓋率按「行」計算**，用的是 coverlet。同一段邏輯，數字會比 Go 的「敘述覆蓋率」低一些。
- **測試專案要有 `coverlet.collector` 套件。** `dotnet new xunit` 建立的專案預設就有。
- **測試專案的判斷方式**：`.csproj` 裡有 `Microsoft.NET.Test.Sdk`，或是設了 `<IsTestProject>true</IsTestProject>`。抓錯檢查會找出參照到被改專案的所有測試專案一起跑。
- **沒有任何測試專案參照的專案，不會跑抓錯檢查。** 畫面上會印出「沒有測試專案參照它，略過」，CRAP 則照常計算，覆蓋率是 0%。
- **抓錯檢查只改壞改到的檔案**（Stryker 的 `--mutate`），再過濾出改到的行，所以比 Go 快。
- **工具放在 `~/.cache/quality-tools`。** Stryker.NET 和 CsMetrics 第一次執行時會自動下載、建置，之後重複使用。不要放在很深的目錄：Windows 上路徑超過 260 字元時，Stryker 會找不到 VSTest 而當掉。可以用環境變數 `QUALITY_TOOLS_DIR` 改位置。
- 本機在 .NET SDK 11 rc 上跑過 selftest。

### JavaScript / TypeScript

- **StrykerJS 和 Vitest 的版本要搭配好。Vitest 5 搭配 StrykerJS 10.0.0 時，所有改壞的版本都會被判成沒抓到，而且沒有任何錯誤訊息。** 開發者會以為是自己的測試太弱。實測結果：

  | Vitest | StrykerJS | 結果 |
  |---|---|---|
  | 4.1.11 | 10.0.0 | 正常 |
  | 5.0.3 | 10.0.0 | 全部沒抓到 |
  | 5.0.3 | 10.1.1 | 正常 |

  `qtools/langs/js.py` 偵測到 Vitest 5 搭配 10.1.1 以前的 StrykerJS 時，會直接停下來並說明原因。StrykerJS 不在驗證清單內也會停下來，見「支援的語言」。
- **圈複雜度用自製的 `qtools/helpers/js/complexity.cjs` 計算**，用 TypeScript 的解析器，所以 `.js`、`.ts`、`.jsx`、`.tsx` 都能讀。規則對齊 Go 的 gocyclo，完整規則寫在檔案開頭。沒有用 ESLint 的 `complexity` 規則，因為規則細節由 ESLint 決定，會隨版本改變；自己寫才能跟其他語言保持同一套算法，也省掉每個專案設定 ESLint 和 TypeScript 外掛的麻煩。
- **哪些算一個函式**：最外層的函式宣告、class 的方法，以及指定給變數或屬性的箭頭函式，例如 `const f = () => {...}`。函式裡面的 callback 算進外層的函式。
- **覆蓋率按「敘述」計算**，跟 Go 一樣。範例專案的 `checkout` 在 Go 和 TypeScript 都是 73.9%。Jest 的覆蓋率報告把「建立箭頭函式」記成函式起點上的一個敘述，這個敘述不計入函式的覆蓋率，所以沒有測試的箭頭函式覆蓋率是 0%。
- **測試檔的判斷方式**：檔名是 `*.test.*`、`*.spec.*`，或放在 `__tests__/` 底下。`*.d.ts` 和 `*.config.*` 不算原始碼。
- **「套件」是 `package.json` 所在的目錄**，monorepo 的每個子套件分開跑。現況報告的抓錯檢查表依資料夾分組。
- **抓錯檢查只改壞改到的檔案**（StrykerJS 的 `mutate`），再過濾出改到的行。
- 本機在 Node 24 上跑過 selftest。StrykerJS 10 需要 Node 22 以上。

### Python

- **抓錯檢查用 cosmic-ray，不用 mutmut。** mutmut 需要 `fork`，官方說明在 Windows 上要透過 WSL 才能跑。
- **cosmic-ray 會直接改原始碼檔案，跑完再改回來。** 中途被打斷，就會留下改壞的程式，所以 `qtools/langs/python.py` 一律把專案複製到暫存目錄再跑，不會動到工作目錄。
- **測試輸出一律用 UTF-8。** 測試名稱或錯誤訊息有中文時，Windows 預設用 Big5 輸出，cosmic-ray 用 UTF-8 讀會出錯，把被抓到的改壞版本誤判成無效。`qtools/langs/python.py` 會設定 `PYTHONUTF8=1` 避開這個問題。
- **測試沒跑到的改壞版本不會真的去跑**，而是用 `qtools/helpers/python/cr_skip_uncovered.py` 先標成「測試沒跑到」。cosmic-ray 本身不看覆蓋率，每個改壞的版本都會把全部測試跑一次，沒被執行到的也會被判成「沒抓到」，既浪費時間又不正確。
- **圈複雜度用 Python 內建的 `ast` 模組計算**，不用另外安裝 radon。規則對齊 Go 的 gocyclo，再補上 Python 才有的語法（生成式裡的 `for`、`if`，條件運算式，`match`），完整規則寫在 `qtools/langs/python.py` 的 `_complexity`。
- **覆蓋率按「敘述」計算，從函式本體的第一行算起。** `def` 那一行在載入模組時就會執行，不能算成函式有被測試。
- **docstring 在函式裡面，改 docstring 會算成改到這個函式。** 寫在 `def` 上方的 `#` 註解則不算。
- **測試框架只支援 pytest。** 測試檔的判斷方式：檔名是 `test_*.py`、`*_test.py`、`conftest.py`，或放在 `tests/`、`test/` 底下。
- **抓錯檢查比其他語言慢**：cosmic-ray 每個改壞的版本都會重新啟動一次 pytest。範例專案改一行，大約 14 秒。
- 專案的 Python 環境要安裝 pytest、coverage、cosmic-ray；cosmic-ray 的版本要在驗證清單內。

## 新增一種語言

在 `qtools/langs/` 新增 `<語言>.py`，定義一個繼承 `qtools.langs.base.Language` 的類別，並在模組末尾寫 `LANGUAGE = <類別名稱>`。接著把語言名稱加進 `qtools/langs/base.py` 的 `MODULES` 和 `qtools/config.py` 的 `LANGUAGES`。類別提供：

| 名稱 | 說明 |
|---|---|
| `SOURCE_GLOBS` | 原始碼的檔名樣式，例如 `["*.go"]` |
| `DEFAULTS` | `timeout_seconds`、`workers`、`exclude_mutators` 三個鍵的預設值，通常 `dict(base.DEFAULTS)` 再改需要不同的項目 |
| `unsupported_warnings(settings)` | 量測工具不支援、但設定檔有設的項目，回傳警告訊息串列 |
| `is_test(path)` | 這個檔案是不是測試檔 |
| `package_dir(path)` | 這個檔案屬於哪個套件（抓錯檢查以套件為單位執行，現況報告也以套件分組） |
| `report_group(path)` | 選用。現況報告想用比套件更細的單位分組時才需要，例如 JS 依資料夾分組 |
| `run_tests(cfg)` | 執行單元測試，回傳結束碼 |
| `measure_functions(cfg)` | 回傳 `Function`：`file`、`name`、`start`、`end`、`complexity`、`coverage`（0～1） |
| `measure_mutants(cfg, dirs=None, files=None)` | 對 `dirs` 這些套件跑抓錯檢查（`None` 表示全部），回傳 `Mutant`：`file`、`line`、`status`、`mutator`，能取得的話加 `column`、`original`、`replacement`。`files` 是改到的檔案，工具支援的話可以只改壞這些檔案來加快速度；不支援就忽略，核心會再過濾 |
| `self.tools` | 把這次用到的量測工具和版本寫進這個字典，會出現在 JSON 報告的 `tools` |

`file` 一律是相對於專案根目錄、用 `/` 分隔的路徑。`status` 用 `KILLED`、`TIMED_OUT`、`LIVED`、`NOT_COVERED`、`NOT_VIABLE`、`SKIPPED`；`EQUIVALENT` 和 `EXCLUDED_MUTATOR` 由核心標記，語言模組不產生。測試沒過或工具執行失敗時，丟出 `qtools.proc.QualityError`（結束碼 2）。

各 repo 自己安裝的工具（像 StrykerJS、cosmic-ray），用 `qtools.langs.base.check_version` 擋下沒驗證過的版本。

同時在 `selftest/` 加一個購物車範例（寫好之後用 `--pack` 打包）和它的情境，CI 也要裝好這個語言的工具。

## 驗證狀態

| 項目 | 狀態 |
|---|---|
| `python selftest.py` | 在本機（Windows + Git Bash + Python 3.12、Go 1.27、.NET SDK 11 rc、Node 24）五個範例全部通過 |
| `python dev/v1_parity.py check` | 在本機（同上）五個範例通過：預設值下 CRAP 表每一列和抓到、沒抓到、測試沒跑到的數字跟 v1.0.0 一致 |
| pip 安裝 | 在本機用新的 venv 執行 `pip install <repo 路徑>` 做過檢查。從遠端網址 `git+https://...@v2.0.0` 安裝沒有試過 |
| reusable workflow `quality.yml` | 用 actionlint v1.7.7 檢查語法沒有錯誤。還沒在 GitHub 或 Gitea 的 runner 上實際跑過，`tools-ref`、`tools-token`、submodule 版本比對都沒有在真的 runner 上驗證 |
| Linux | v2 的程式還沒在 Linux 上跑過。v1.0.0 時 `selftest.yml` 在 GitHub Actions（ubuntu-latest）通過；現在的 `selftest.yml` 還沒有在 GitHub Actions 上跑過 |
| Gitea | 都沒有驗證：`selftest.yml`、reusable workflow、跨 repo 引用 `uses:`、CODEOWNERS 語法和受保護的檔案模式 |
