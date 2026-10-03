# LME 鋁價日報 — GitHub 自動更新

每天 台北 08:30，GitHub Actions 會執行 `update.py`：
抓 LME、長江A00、USD/CNY、台指期夜盤 → 更新 `index.html` → 存一份當日快照到 `snapshots/YYYY-MM-DD.html` → 自動 commit。

## 設定步驟（一次）
1. 把本資料夾全部內容（含隱藏的 `.github`、`.nojekyll`）放進 repo `yudy-ai/lme-al-daily` 的根目錄並 push。
2. GitHub → Settings → Pages → Source 選 Deploy from a branch，Branch 選 main、資料夾 `/ (root)`。
3. GitHub → Actions → Daily update → Run workflow，手動跑一次確認成功。

## 網址
- 最新版：https://yudy-ai.github.io/lme-al-daily/
- 歷史版本：https://yudy-ai.github.io/lme-al-daily/snapshots/
