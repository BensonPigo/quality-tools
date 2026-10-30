# 三道防線導入範本

把三道檢查（單元測試、CRAP、抓錯檢查）裝進各個 repo。分成兩個部分：

| 部分 | 是什麼 | 在哪裡 |
|---|---|---|
| quality-tools | CRAP 和抓錯檢查的量測工具，支援 Go、C#、JS / TS、Python，目前是 v2.0.0 | 獨立的 repo：GitHub 私有 repo `BensonPigo/quality-tools`，也就是這份範本所在的 repo。之後可以搬到公司 Gitea，例如 `qa/quality-tools` |
| `專案repo範本/` | 每個專案 repo 自己要放的設定：`.quality.json`、`.quality-equivalents.json`、`CODEOWNERS`、`.claude/`、workflow、CLAUDE.md 片段 | 複製到各專案 repo |

```
qa/quality-tools（v2.0.0、v2.1.0 ...）
        ▲ 三種接法，各 repo 自己決定用哪一版：
        │   git submodule（tools/quality/）、reusable workflow、pip
        │
shop/order-service
├── tools/quality/                  → quality-tools v2.0.0
├── .quality.json                   ← 語言、門檻、啟用哪幾關
├── .quality-equivalents.json       ← 改了也沒差的版本排除清單，要人核准
├── CODEOWNERS                      ← 檢查相關的檔案由誰審核
├── .claude/                        ← AI 結束前自動檢查
├── .gitea/workflows/quality.yml
└── CLAUDE.md
```

單元測試由各專案 repo 自己寫。CRAP 和抓錯檢查的工具是共用的，用來量那些測試寫得夠不夠好；量出問題後，補測試或拆函式還是在專案 repo 裡做。

## 三種接法

| 接法 | 說明 | 驗證狀態 |
|---|---|---|
| git submodule | 各 repo 掛 `tools/quality/`，指向工具的某個版本標籤。AI 結束前的自動檢查也用這個目錄 | v1.0.0 時在本機用 git 模擬過完整流程；v2.0.0 的 submodule 路徑和進入點沒變，`selftest.py` 用同樣的掛載方式測過 |
| reusable workflow | CI 用 `uses:` 一行引用 quality-tools 的 `.github/workflows/quality.yml`，要填 `tools-ref`，且必須和 `uses:` 的版本相同 | 只用 actionlint 檢查過語法，還沒在 GitHub 或 Gitea 的 runner 上跑過 |
| pip | `pip install "quality-tools @ git+https://...@v2.0.0"`，指令是 `quality` | 本機路徑安裝檢查過 |

選擇建議和 reusable workflow 的寫法，見 `專案repo範本/README.md` 的「三種接法」。

## 從哪裡開始

1. quality-tools 的版本用標籤發布，v2.0.0 由維護者驗證後打標籤。標籤打好之前，範本裡寫的 `v2.0.0` 還不存在。維護方式見這個 repo 根目錄的 `README.md`，每一版改了什麼見 `CHANGELOG.md`。
2. 挑一個試點的專案 repo，照 `專案repo範本/README.md` 的步驟套用。範本的 `.quality.json` 只啟用第一關（單元測試），之後依導入步驟「一次上一關」，一兩週加一關。
3. 已經在用 v1 的專案 repo，看 `專案repo範本/README.md` 的「從 v1 升級」。
