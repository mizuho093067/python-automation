# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code 向けのガイドです。

## プロジェクト概要

Python による各種作業の自動化スクリプトをまとめるプロジェクトです。

## 開発環境

- OS: Windows 11（PowerShell / Git Bash）
- 言語: Python 3
- 仮想環境: プロジェクト直下の `.venv` を使用する
  - 作成: `python -m venv .venv`
  - 有効化（PowerShell）: `.venv\Scripts\Activate.ps1`
  - 有効化（Git Bash）: `source .venv/Scripts/activate`
- 依存パッケージは `requirements.txt` で管理する
  - インストール: `pip install -r requirements.txt`
  - パッケージを追加したら `requirements.txt` も更新する

## コーディング規約

- PEP 8 に従う
- 関数・クラスには型ヒントと簡潔な docstring を付ける
- パスは `pathlib.Path` で扱い、Windows 固有の区切り文字をハードコードしない
- ファイル読み書きは `encoding="utf-8"` を明示する
- API キー・パスワードなどの秘密情報はコードに書かず、`.env` などで管理し、Git にコミットしない

## Git 運用ルール

- **コードを変更するたびに、コミットして GitHub にプッシュする。**
  1. `git status` / `git diff` で変更内容を確認する
  2. 関連する変更だけを `git add` する（秘密情報・不要ファイルを含めない）
  3. 変更内容がわかるコミットメッセージで `git commit` する
  4. `git push` で GitHub のリモートに反映する
- コミットは小さく、1 コミット 1 目的を心がける
- コミットメッセージは日本語可。1 行目に要約、必要なら空行の後に詳細を書く
- `.venv/`、`__pycache__/`、`.env` などは `.gitignore` に含める
- `git push --force` や履歴の書き換えは、ユーザーの明示的な指示がない限り行わない
- プッシュが失敗した場合（リモート未設定・認証エラー・競合など）は、無理に解決せずユーザーに報告する
