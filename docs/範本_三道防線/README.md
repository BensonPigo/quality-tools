# 三道防線導入範本

把三重約束（單元測試、CRAP、變異測試）裝進各個 repo。分成兩個部分：

| 部分 | 是什麼 | 在哪裡 |
|---|---|---|
| quality-tools | CRAP 和變異測試的量測工具，支援 Go、C#、JS / TS、Python | 獨立的 repo：GitHub 私有 repo `BensonPigo/quality-tools`，也就是這份範本所在的 repo。之後可以搬到公司 Gitea，例如 `qa/quality-tools` |
| `專案repo範本/` | 每個專案 repo 自己要放的設定：`.quality.json`、`.claude/`、workflow、CLAUDE.md 片段 | 複製到各專案 repo |

```
qa/quality-tools（v1.0.0、v1.1.0 ...）
        ▲ git submodule，各 repo 自己決定用哪一版
        │
shop/order-service
├── tools/quality/    → quality-tools v1.0.0
├── .quality.json     ← 語言、門檻
├── .claude/          ← AI 結束前自動檢查
├── .gitea/workflows/quality.yml
└── CLAUDE.md
```

單元測試由各專案 repo 自己寫。CRAP 和變異測試的工具是共用的，用來量那些測試寫得夠不夠好；量出問題後，補測試或拆函式還是在專案 repo 裡做。

## 從哪裡開始

1. quality-tools 已經推到 GitHub，打上 `v1.0.0` 標籤。維護方式見這個 repo 根目錄的 `README.md`。
2. 挑一個試點的專案 repo，照 `專案repo範本/README.md` 的步驟套用。
