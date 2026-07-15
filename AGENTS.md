# 專案規則

所有工作都必須遵守 [`.codex/rules/command-confirmation.md`](.codex/rules/command-confirmation.md) 中定義的 Git 提交、Conventional Commits 與 Release 規則。

在執行任何 Git 指令前，必須先以自然語言列出準備執行的步驟與指令，並等待使用者明確確認。

涉及遠端狀態的 Git 操作必須依序執行：

1. `git pull`
2. `git commit`
3. `git push`

除非使用者已明確完成前置步驟，否則不得跳過 `git pull`。建立版本時，還必須依連結規則同步 README Release Notes、建立 annotated tag，並建立 GitHub Release。
