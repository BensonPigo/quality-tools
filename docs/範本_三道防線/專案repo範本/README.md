# 專案 repo 範本

把三道檢查（單元測試、CRAP、抓錯檢查）裝進一個已經在開發中的 repo。量測工具不放在專案 repo 裡，由中心化的 `quality-tools` 提供，專案 repo 只記錄用的是哪一個版本。步驟對齊 `docs/導入步驟_三道檢查.md` 的第 0～7 步。

設計原則只有一條：**舊程式碼先不管，這次改到的才要過。** 舊程式碼的問題用「量現況」列成技術債，改到哪裡清到哪裡。

## 套用之後，專案 repo 的樣子

```
order-service/
├── tools/quality/                 # submodule，指向 quality-tools 的某個版本，不存放程式碼
├── .gitmodules                    # git 自動產生，記錄 submodule 的來源
├── .quality.json                  # 語言、門檻、啟用哪幾關、比較基準、排除目錄
├── .quality-equivalents.json      # 改了也沒差的版本排除清單，由人核准後才寫入
├── CODEOWNERS                     # 放在 .gitea/ 或 .github/，指定誰審核檢查相關的檔案
├── .claude/settings.json          # 禁止 AI 改檢查檔案；結束前自動檢查
├── .claude/hooks/gate.sh          # 結束前自動檢查的腳本
├── .gitea/workflows/quality.yml   # 從 workflows/ 挑一個
└── CLAUDE.md                      # 貼上 CLAUDE片段.md
```

這個資料夾的內容：

| 檔案 | 用途 |
|---|---|
| `.quality.json`、`.quality-equivalents.json`、`.claude/` | 複製到專案 repo 的根目錄 |
| `CODEOWNERS` | 放到專案 repo 的 `.gitea/CODEOWNERS` 或 `.github/CODEOWNERS` |
| `workflows/<語言>.yml` | 挑一個，放到 `.gitea/workflows/quality.yml`（submodule 接法） |
| `workflows/reusable-caller.yml` | 引用 quality-tools 的 reusable workflow 的寫法 |
| `CLAUDE片段.md` | 貼進專案 repo 的 `CLAUDE.md` |

三層防線各擋什麼：

| 層 | 檔案 | 擋什麼 | 擋不住什麼 |
|---|---|---|---|
| 第 1 層 | `CLAUDE.md` | 讓 AI 知道規則和完成的定義 | AI 不照做 |
| 第 2 層 | `.claude/settings.json`、`gate.sh` | AI 用編輯工具或 `sed` 改檢查檔案；AI 沒過第一、二關就說做完 | AI 寫程式（例如 Python）間接改檔案；第三關 |
| 第 3 層 | workflow + CODEOWNERS + 分支保護 | 沒過三道檢查的 PR 不能合併；改檢查檔案要人核准 | 測試被刪掉或改弱，要靠人審 PR |

## 三種接法

| 接法 | 做法 | 適合 |
|---|---|---|
| git submodule | `tools/quality/` 掛在專案 repo 裡，指向某個版本標籤。CI 用 `workflows/<語言>.yml`，AI 的結束前自動檢查（`gate.sh`）也用它 | 預設選這個。開發者本機、AI、CI 用同一份工具，版本記在專案 repo 裡 |
| reusable workflow | CI 只寫一個 job，用 `uses:` 引用 quality-tools 的 `quality.yml`，不用抓 submodule | 想讓 CI 設定只剩一個 job。專案同時掛了 submodule 時，workflow 會比對兩邊的版本，不一致就失敗，所以可以跟 submodule 並用，由 workflow 保證版本一致 |
| pip | `pip install "quality-tools @ git+https://<主機>/<組織>/quality-tools@v2.0.0"`，指令是 `quality` | 本機快速試用。範本的 `gate.sh` 找的是 `tools/quality/quality.py`，只用 pip 時要把 `gate.sh` 裡的呼叫改成 `quality check ...`，這個改法沒有測過 |

選哪一種都要固定版本，各 repo 自己決定什麼時候升級。以下步驟用 submodule 的寫法；改用 pip 時，把 `python tools/quality/quality.py` 換成 `quality`。

### reusable workflow 的寫法

把 `workflows/reusable-caller.yml` 放到 `.gitea/workflows/quality.yml`（GitHub 放 `.github/workflows/quality.yml`），改 `language`。要注意三件事：

1. **`tools-ref` 必須和 `uses:` 後面 `@` 的版本相同**，例如兩處都是 `v2.0.0`，升級時兩處一起改。被呼叫的 workflow 沒有文件記載的方式取得自己被引用的版本，所以靠 `tools-ref` 決定下載哪一版的工具。
2. **quality-tools 是私有 repo 時要傳 `tools-token`。** 預設權杖讀不到 quality-tools；建一個能讀它的存取權杖，存成專案 repo 的密鑰（範例裡叫 `QUALITY_TOOLS_TOKEN`），用 `secrets: tools-token:` 傳進去。quality-tools 公開時不用傳。quality-tools 不在專案 repo 同一個擁有者底下時，另外填 `tools-repository`。
3. **專案有掛 `tools/quality` submodule 時，workflow 會比對版本。** workflow 不抓 submodule（私有 repo 時，預設權杖抓不到），改用 `git ls-tree` 讀專案記錄的 submodule commit，跟 `tools-ref` 的 commit 比對，不同就失敗，訊息是「submodule 記錄的版本和 tools-ref 不一致」。升級時 submodule、`uses:` 的版本、`tools-ref` 三處要改成同一版。

其他參數（`install`、`skip`、各語言的版本）見 quality-tools 的 `README.md`。

## 套用步驟

### 前置：掛上工具、複製檔案

**掛上工具**，在專案 repo 的根目錄執行，`v2.0.0` 換成 `quality-tools` 目前最新的版本：

```bash
git submodule add ../../qa/quality-tools.git tools/quality
git -C tools/quality checkout v2.0.0
git add .gitmodules tools/quality
git commit -m "掛上品質工具 v2.0.0"
```

網址 `../../qa/quality-tools.git` 是相對於專案 repo 自己的網址。例如專案 repo 是 `https://gitea.公司/shop/order-service.git`，就會解析成 `https://gitea.公司/qa/quality-tools.git`。用相對網址，不管開發者用 HTTPS 還是 SSH clone，都能抓到工具。`quality-tools` 放在別的組織時，把 `qa` 換掉。

**複製其他檔案：**

```bash
cp -r 專案repo範本/.quality.json 專案repo範本/.quality-equivalents.json 專案repo範本/.claude 目標repo/
cp 專案repo範本/workflows/<語言>.yml 目標repo/.gitea/workflows/quality.yml
```

- **已經有 `.claude/settings.json`**：不要直接覆蓋，把 `permissions.deny` 和 `hooks.Stop` 兩段合併進去。
- **JavaScript / TypeScript 專案**：另外要安裝 StrykerJS，Vitest 專案還要裝覆蓋率套件，並把 `.stryker-tmp/` 加進 `.gitignore`。StrykerJS 的版本只接受 quality-tools 驗證過的：10.0.0（搭配 Vitest 4、Jest 30）、10.1.1（搭配 Vitest 4、Vitest 5）。Vitest 5 要用 10.1.1：

  ```bash
  # Vitest 4.x
  npm install -D @vitest/coverage-v8@<跟 vitest 同版本> @stryker-mutator/core@10.0.0 @stryker-mutator/vitest-runner@10.0.0
  # Jest
  npm install -D @stryker-mutator/core@10.0.0 @stryker-mutator/jest-runner@10.0.0
  ```
- **Python 專案**：專案的 Python 環境要安裝 pytest、coverage、cosmic-ray。cosmic-ray 的版本只接受 quality-tools 驗證過的 8.7.0，例如加進 `requirements-dev.txt`：

  ```
  pytest==9.1.1
  coverage==7.16.2
  cosmic-ray==8.7.0
  ```
- **用 GitHub**：workflow 放到 `.github/workflows/quality.yml`。
- **`.gitattributes` 加一行 `*.sh text eol=lf`**（沒有這個檔案就新建）。開發者的 Git 設了 `core.autocrlf=true` 時，`gate.sh` 可能被換成 CRLF 換行，bash 執行時會出錯。
- **專案的 linter、格式檢查、型別檢查掃整個 repo 的**，要排除 `tools/quality/`。例如 ESLint 會檢查到 `tools/quality/qtools/helpers/js/complexity.cjs`，ruff、mypy 會檢查到 `tools/quality/` 底下的 `.py` 檔。
- **C# 專案的 `.csproj` 放在 repo 根目錄的**，要在 `.csproj` 加上 `<Compile Remove="tools/**" />`。`.csproj` 預設會編譯所在目錄底下所有的 `.cs` 檔，包括 `tools/quality/qtools/helpers/dotnet/CsMetrics/Program.cs`。`.csproj` 放在 `src/` 這類子目錄的不受影響。

**調整 `.quality.json`：**

```json
{
  "version": 2,
  "language": "go",
  "base": "origin/main",
  "gates": ["test"],
  "exclude": ["tools/", "vendor/", "node_modules/"],
  "crap": { "threshold": 12 },
  "mutation": {
    "kill_rate_threshold": 80,
    "reach_rate_threshold": 50
  }
}
```

| 設定 | 說明 |
|---|---|
| `version` | 固定是 `2` |
| `language` | `go`、`csharp`、`js`（JavaScript 和 TypeScript 都用 `js`）或 `python` |
| `base` | 主分支。叫 `master` 就改成 `origin/master`，workflow 的 `branches: [main]` 也要一起改 |
| `gates` | 啟用哪幾關：`test`、`crap`、`mutation`。範本只開 `["test"]`，對應導入步驟「一次上一關」，何時加下一關見下方各步驟 |
| `crap.threshold` | 指南建議從 12 開始，上限 30 |
| `mutation.kill_rate_threshold` | 抓錯率門檻（百分比）。先跑步驟 0 看現況，再決定要設多少 |
| `mutation.reach_rate_threshold` | 測到率門檻（百分比），一定要設，範本是 50，原因見步驟 4 |
| `exclude` | 不量測的目錄 |

沒寫的鍵用工具預設值。其餘的鍵（`mutation.timeout_seconds`、`mutation.workers`、`mutation.exclude_mutators`、`mutation.equivalents_file`、`baseline.*`、`csharp.solution`、`js.test_runner`、`python.interpreter`）寫法和預設值見 quality-tools 的 `README.md`。C# 根目錄有多個 `.sln` 或 `.slnx` 時要設 `csharp.solution`；JS / TS 專案自動判斷錯了才需要設 `js.test_runner`。寫錯鍵名或型別，指令會以結束碼 2 結束，不會默默用預設值。

### 步驟 0：先量現況

```bash
python tools/quality/quality.py baseline
```

這個指令不看 `gates`，三關都量。產生 `docs/品質現況.md` 和同名的 `docs/品質現況.json`。以一個三個套件的小專案為例，內容如下：

```markdown
## CRAP

門檻 12。函式總數 4，通過 2，超標 2（補測試就能過 1，要拆函式 1），優先處理 1。

| CRAP | C | 覆蓋率 | 修改次數 | 函式 | 位置 | 改善方向 | 優先處理 |
|---|---|---|---|---|---|---|---|
| 17.5 | 14 | 73.9% | 6 | `Checkout` | `checkout.go:31` | 要拆函式 | 優先處理 |
| 30.0 | 5 | 0.0% | 1 | `Weight` | `shipping/fee.go:15` | 覆蓋率要到 35% |  |

## 抓錯檢查

| 套件 | 抓到 | 逾時 | 沒抓到 | 測試沒跑到 | 抓錯率 | 測到率 |
|---|---|---|---|---|---|---|
| `.` | 10 | 0 | 10 | 4 | 50.00% | 83.33% |
| `notest` | 0 | 0 | 0 | 1 | — | 0.00% |
| `shipping` | 2 | 0 | 0 | 9 | 100.00% | 18.18% |
```

（這是報告的一部分，省略了開頭的日期和兩個比例的公式說明。）

讀報告的重點：

- **「優先處理」**：CRAP 超標、而且最近常被修改（修改次數達到 `baseline.hot_churn`，預設 5）的函式，要主動排進開發排程先處理，原因見導入步驟第二節。修改次數只對超標的函式計算，統計 `baseline.churn_since`（預設 6 個月）以來改到它的 commit 數，建立的那一次不算。
- **CRAP 標「要拆函式」的**：改到時一定要重構，排進技術債清單時優先處理。
- **抓錯率和測到率要一起看。** 例如 `shipping` 的抓錯率是 100%，但測到率只有 18%。意思是有測試的部分都測得很好，但大部分程式碼根本沒有測試。

大專案的抓錯檢查可能要跑很久，建議下班前執行。報告要 commit 進 repo，之後每季重新量一次，用 `compare` 跟上一次比較：

```bash
python tools/quality/quality.py baseline --compare docs/品質現況.json
```

會印出超標函式數、要拆函式數、優先處理數，以及各套件抓錯率和測到率的前後差，並在報告最後加「## 跟上一次比較」。要比較兩份已經存在的報告，用 `compare 舊.json 新.json`。

### 步驟 1：只管這次改到的

三個指令加 `--base origin/main`（或 `check` 的預設，讀 `.quality.json` 的 `base`），只檢查和主分支相比改到的函式和行。「改到」從分岔點算起，包含還沒 commit 的改動；函式範圍內任何一行有改動就算改到這個函式，只改函式外面的註解不算。

### 步驟 2：上單元測試這關

`.quality.json` 的 `gates` 是 `["test"]`，workflow 三個步驟都會執行，沒啟用的 `crap`、`mutation` 印「還沒啟用」後以 0 結束，所以只有第一關在擋。用 submodule 接法的，把 `workflows/<語言>.yml` 放到 `.gitea/workflows/quality.yml`；用 reusable workflow 的，放 `reusable-caller.yml`。

跑一兩週，看會不會常常誤擋，再上下一關。

### 步驟 3：上 CRAP

把 `gates` 改成 `["test", "crap"]`。改到的函式 CRAP 超過 `crap.threshold` 就擋下，並標出改善方向：「要拆函式」，或「覆蓋率要到 X%」。workflow 不用改。

### 步驟 4：上抓錯檢查

把 `gates` 改成 `["test", "crap", "mutation"]`。門檻參考步驟 0 的報告：`kill_rate_threshold` 先設在現況附近，例如 80，不要設 100（改了也沒差的版本不可能抓到，設 100 會逼 AI 寫出奇怪的測試）。

`reach_rate_threshold` 一定要設：抓錯率只算有被測試跑到的改壞版本，一段完全沒有測試的新程式，改壞的版本全是「測試沒跑到」，不算進抓錯率，抓錯率不會下降；CRAP 也不一定擋得住（圈複雜度 1 的函式，沒有測試也只有 2 分）。範本設 50，只設抓錯率的話，新程式完全不寫測試，三關反而都會過。

沒抓到的改壞版本，輸出會寫出位置和改了什麼，例如：

```
沒抓到  shipping/fee.go:5  把 `>=` 改成 `>`  ｜ if total >= 1000 {
```

這個邊界值沒有測到，補測試就能抓到。

**處理改了也沒差的版本**：有些改壞版本不管怎麼改，程式的結果都一樣，不可能抓到。AI 不准為它寫奇怪的測試，也不准自己編輯 `.quality-equivalents.json`，要在回報裡列出檔案、行號、改法、那一行的原文和理由。人確認後，把這一項加進 `.quality-equivalents.json`：

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

`reason` 和 `approved_by` 必填，缺了指令以結束碼 2 結束。比對用 `file`、`mutator` 和那一行去頭尾空白後的原文，不用行號；那一行被改了，這一項就失效，要重新判斷。清單裡沒用到的項目會在輸出列成「排除清單有 N 項沒用到」，可以刪掉。`mutator` 的名稱看 `mutation --json 檔名` 寫出的報告裡 `mutation.mutants[].mutator`。這個檔案要由 CODEOWNERS 指定的人核准才能合併（步驟 6）。

大專案的抓錯檢查在 CI 上可能很慢，改到大檔案或核心模組時要先跟團隊講好。要調整逾時或同時跑幾個，在 `.quality.json` 設 `mutation.timeout_seconds`、`mutation.workers`。

### 步驟 5：AI 自己先檢查

`.claude/settings.json` 掛了 Stop hook，AI 要結束時自動執行 `.claude/hooks/gate.sh`，它呼叫 `check --base <base> --skip mutation`：依 `gates` 跑第一、二關，沒過就以結束碼 2 結束，Claude Code 會擋下結束，把錯誤訊息交給 AI 繼續修。第三關太慢，每次 AI 結束都跑會拖慢對話，所以交給 CI。

開發者電腦要有 Git Bash 和 Python 3。在專案 repo 開一個新的 Claude Code 對話，做兩個測試：

1. 叫 AI 把 `.quality.json` 的門檻改成 100，應該被拒絕。
2. 叫 AI 改一個舊的超標函式，而且不准它補測試。它說做完時，應該被 `gate.sh` 擋下來，並收到 CRAP 的錯誤訊息（這個測試要 `gates` 已經包含 `crap`）。

注意：

- **AI 卡住時不會無限循環。** Claude Code 在 Stop hook 連續擋了 8 次、中間 AI 沒有任何工具呼叫時，會自動放行。
- **找不到比較基準時，`gate.sh` 會直接放行，不會報錯。** 例如本機還沒 fetch `origin/main`。`.quality.json` 的 `base` 要填 `gate.sh` 找得到的名稱，也可以用環境變數 `QUALITY_BASE` 覆蓋。如果發現 hook 從來沒擋過東西，先檢查這一點。
- **有改東西、但 `tools/quality/` 是空的時候，`gate.sh` 會擋下來**，請 AI 或開發者執行 `git submodule update --init`。

### 步驟 6：把規則鎖起來

三個地方一起設：

1. **AI 工具的權限**：`.claude/settings.json` 的 `deny` 已經包含 `.quality.json`、`.quality-equivalents.json`、`.gitmodules`、`tools/quality/**`、`.gitea/**`、`.github/**`、`.claude/**`、`CODEOWNERS`。
2. **CODEOWNERS**：把 `CODEOWNERS` 放到 `.gitea/CODEOWNERS`（GitHub 放 `.github/CODEOWNERS`），把裡面的 `@your-org/quality-reviewers` 換成實際的審核群組。改到這些檔案的 PR 要他們核准。Gitea 的 CODEOWNERS 比對規則和 GitHub 不完全相同，貼進去之後對照你們 Gitea 版本的說明確認，範本沒有在 Gitea 上測過。
3. **分支保護**：見下方「設定 Gitea」。

AI 使用的帳號不能有合併權限，也不能有 `quality-tools` 的寫入權限。合併一定由人按，按下合併的人就是簽名負責的人。

### 步驟 7：人改成看測試

審 PR 時先看測試檔改了什麼：正確答案是不是照需求寫的、測試有沒有被刪掉或改鬆；`.quality-equivalents.json` 有新增項目時，逐項看 `reason`。這條規則也寫進 AI 的指示檔：把 `CLAUDE片段.md` 貼到專案 repo 的 `CLAUDE.md`，沒有這個檔案就新建一個。主分支不是 `main` 的話，片段裡的 `origin/main` 也要改。

### 設定 Gitea

**先請管理員確認：**

- 有開啟 Actions，也有註冊 runner（`act_runner`）。
- runner 的映像檔有 Python 3。
- runner 讀得到 `quality-tools`。最簡單是把 `quality-tools` 設成公司 Gitea 內公開，工具程式碼沒有機密。不能公開的話，照 workflow 裡 `token:` 那行的註解設定存取權杖（reusable workflow 則傳 `tools-token`）。
- runner 能連到外網下載工具。內網連不出去的話，要設定鏡像：
  - 所有語言：github.com（`actions/checkout`、`actions/setup-*`、`actions/cache`）
  - Go：Go 模組伺服器（gocyclo、gremlins）
  - C#：NuGet（Stryker.NET、Roslyn）
  - JS / TS：npm registry（專案相依套件、TypeScript 解析器）
  - Python：PyPI（專案相依套件、pytest、coverage、cosmic-ray）

**分支保護**（儲存庫設定 → 分支 → 新增規則，套用到 `main`）：

| 設定 | 值 |
|---|---|
| 停用推送 | 開啟（只能透過 PR 合併） |
| 啟用狀態檢查 | 開啟，加入「三道檢查」的檢查名稱 |
| 所需的核准數 | 至少 1 |
| 受保護的檔案模式 | `.gitea/**;.gitmodules;.quality.json;.quality-equivalents.json;CODEOWNERS;tools/quality;tools/quality/**;.claude/**` |

要填的檢查名稱，以第一次跑完 workflow 後 PR 頁面上顯示的為準。

受保護的檔案模式裡，`tools/quality` 是為了擋「把工具換成別的版本」：submodule 在專案 repo 裡只是一筆指向工具 commit 的紀錄，路徑就是 `tools/quality`，沒有底下的檔案。兩種寫法都放，比較保險。這個設定還沒在 Gitea 上實測，步驟 8 送 PR 時，順便送一個只改工具版本的 PR，確認需要核准。

### 步驟 8：送一個會失敗的 PR

開一個分支，改一個舊的超標函式，不補測試，送出 PR。確認三件事，導入才算完成：

- workflow 跑了，而且有抓到 `tools/quality` 的工具（log 裡看得到 CRAP 表格）
- 第二關失敗
- 「合併」按鈕不能按

這個測試要 `gates` 已經包含 `crap`。

## 開發者要知道的事

**clone 時加 `--recurse-submodules`：**

```bash
git clone --recurse-submodules https://gitea.公司/shop/order-service.git
```

已經 clone 過的，執行一次 `git submodule update --init`。

**建議每個人設定一次：**

```bash
git config --global submodule.recurse true
```

沒設定的話，切換分支或 `git pull` 之後，`tools/quality` 會停在原本的版本，跑的工具跟 CI 不一樣。設定之後，這兩個指令會自動把工具切到分支記錄的版本。

**看目前用的是哪一版：**

```bash
git -C tools/quality describe --tags
```

## 升級工具

`quality-tools` 發布新版本時，各 repo 自己決定什麼時候升級。升級前先看 `tools/quality/CHANGELOG.md`，第二碼或第一碼有變的版本，可能讓原本通過的程式變成沒過。

```bash
git checkout -b 升級品質工具
git -C tools/quality fetch --tags
git -C tools/quality checkout v2.1.0
git add tools/quality
git commit -m "品質工具升級到 v2.1.0"
```

用 reusable workflow 的，同一個 PR 裡把 `uses:` 後面的版本和 `tools-ref` 也改成 `v2.1.0`。送 PR，這個 PR 的 CI 會用新版工具檢查，有問題就看得到，不合併就好。

**退回舊版**也是同樣的步驟，把 `v2.1.0` 換成舊的版本號。

## 從 v1 升級

v2.0.0 的 `.quality.json` 格式不相容：v2 的工具讀到 v1 的設定檔，所有指令都以結束碼 2 結束；v1 的工具讀 v2 的設定檔時，會忽略不認得的鍵，`crap.threshold` 等門檻悄悄退回 v1 的預設值。所以工具版本和設定檔要在同一個 PR 裡改。

1. **升級 submodule**，在新分支上：

   ```bash
   git checkout -b 升級品質工具v2
   git -C tools/quality fetch --tags
   git -C tools/quality checkout v2.0.0
   git add tools/quality
   ```

2. **轉換設定檔**：

   ```bash
   python tools/quality/quality.py migrate
   ```

   把 `.quality.json` 改寫成 v2，並印出前後差異。轉換後的判定結果跟 v1 相同：`gates` 寫成三關全開；v1 沒寫過測到率門檻的，`mutation.reach_rate_threshold` 寫成 0；`python_mutant_timeout` 只在 Python 專案轉成 `mutation.timeout_seconds`。步驟 4 說明為什麼要把 `reach_rate_threshold` 調成大於 0，跑過現況報告之後再決定要不要調。

3. **檢查差異**：用 `git diff .quality.json` 確認門檻和 v1 的值一致；在專案根目錄執行 `python tools/quality/quality.py check --base origin/main`，確認結果跟升級前一樣。
4. **同步更新範本的其他檔案**（跟這個資料夾的版本對照）：
   - `.claude/hooks/gate.sh`：新版呼叫 `check --skip mutation`。
   - `.claude/settings.json`：`permissions.deny` 加 `Edit(/.quality-equivalents.json)`、`Edit(/CODEOWNERS)`。
   - 新增 `.quality-equivalents.json`（內容 `[]`）和 `CODEOWNERS`。
   - workflow：步驟名稱改成「第一關／第二關／第三關」，快取 key 的路徑改成 `tools/quality/qtools/langs/<語言>.py` 和 `tools/quality/qtools/helpers/**`（舊路徑，也就是 `tools/quality/` 根目錄的語言模組檔和 `tools/quality/dotnet/**`、`tools/quality/js/**`，已經不存在）。
   - `CLAUDE.md`：用新的 `CLAUDE片段.md` 取代舊的品質規則。
   - 分支保護的受保護檔案模式加 `.quality-equivalents.json`、`CODEOWNERS`。
   - JS 專案確認 StrykerJS 是 10.0.0 或 10.1.1；Python 專案確認 cosmic-ray 是 8.7.0，其他版本會以結束碼 2 結束。
5. **送 PR**，CI 用新版工具跑一遍，確認結果跟升級前一樣再合併。

v1 的 `.quality.json` 鍵名對照見 quality-tools 的 `CHANGELOG.md`。

## 試點期間不想用 submodule

工具還在常常調整時，每改一次就要打標籤、更新 submodule，比較麻煩。試點的那一個 repo 可以先把 `quality-tools` 直接複製進去：

```bash
mkdir -p 目標repo/tools/quality
T=/c/Git/Personal/quality-tools   # quality-tools 在本機的位置
cp -r $T/quality.py $T/qtools 目標repo/tools/quality/
find 目標repo/tools/quality -name __pycache__ -prune -exec rm -rf {} +
```

其他步驟一樣，workflow 的 `submodules: true` 留著也沒關係。試點結束後，刪掉 `tools/quality/` 再照前置步驟掛上 submodule。

## 推動順序

不要一次套用到所有 repo。先挑**一個**改動頻繁、已經有測試的 repo 試做兩週，觀察以下幾件事：

| 觀察項目 | 怎麼調整 |
|---|---|
| CI 跑多久 | 太慢的話，請管理員給 runner 更多 CPU，或拆成兩個 workflow：第三關只在 PR 要合併前跑 |
| 有沒有誤擋 | 記下來，判斷是門檻太嚴，還是遇到工具的已知限制（見 `tools/quality/README.md`） |
| 抓錯率門檻 | 看兩週內 PR 的抓錯率分布，再決定要不要調高 |
| 排除清單 | 看 `.quality-equivalents.json` 新增了哪些項目，`reason` 有沒有寫清楚 |
| AI 有沒有出現「改 A 壞 B」 | 有的話就把 CRAP 門檻往下收（指南 2.2 節） |

工具要修改的，改在 `quality-tools`，發布新版本；門檻和設定要調的，改回這個範本。之後再一個一個 repo 套用。

## 驗證狀態

| 項目 | 狀態 |
|---|---|
| quality-tools 本身 | `selftest.py` 五個範例和 `dev/v1_parity.py check`（分數跟 v1.0.0 一致）在本機 Windows 通過。v2 的程式沒有在 Linux 上跑過 |
| `gate.sh` | 在 `selftest.py` 的 Go 範例用模擬的輸入驗證過：沒改東西時放行；改舊函式、測試失敗都會擋下；沒抓 submodule 又有改東西時，擋下並提示執行 `git submodule update --init`；找不到比較基準時放行，`QUALITY_BASE` 能覆蓋。還沒接上真的 Claude Code 對話測試，步驟 5 就是在測這個 |
| `.claude/settings.json` 的禁止規則 | 語法照 Claude Code 官方文件寫，還沒實測，步驟 5 會測到 |
| 範本的四個語言 workflow 和 `reusable-caller.yml` | 用 actionlint v1.7.7 檢查語法沒有錯誤。還沒在 Gitea 或 GitHub 的 runner 上實際跑過 |
| reusable workflow | 還沒有在真的 runner 上跑過：`tools-ref` 與 `uses:` 版本相同、`tools-token` 讀私有 repo、submodule 版本比對，都沒有實測。Gitea 要什麼版本才能引用另一個 repo 的 reusable workflow，也沒有確認 |
| submodule 接法 | v1.0.0 時在本機用 git 模擬過完整流程（遠端用本機的 bare repo 代替 Gitea）：發布版本 → `git submodule add` 相對網址 → `clone --recurse-submodules` → 三個指令結果正確 → 改舊函式時 `gate.sh` 擋下 → 升級、退回 → 設定 `submodule.recurse` 時切換分支工具跟著切。v2.0.0 沒有重做這個流程 |
| CODEOWNERS、分支保護 | 還沒在 Gitea 上跑過：CODEOWNERS 語法、受保護的檔案模式擋不擋得住 submodule 版本的變更，步驟 6、8 會測到 |
| 從 v1 升級 | `migrate` 在 `selftest.py` 的情境測過；在真的 v1 專案 repo 上走完整個「從 v1 升級」流程還沒做過 |
