# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Laarma** は [CSA AARM 仕様](https://aarm.dev/spec) の Python プロトタイプ実装。AI エージェントのツール呼び出しを実行前にインターセプト・評価・記録する。

このファイルは**索引**であり、設計判断・リポジトリの地図・使い方の内容そのものは持たない。それぞれの正典（下記）を参照すること。各正典は現在の実装に合わせて維持される living document であり、本ファイルはそこへ案内するだけに徹する。

## 正典の所在

- **設計判断**（なぜこの設計か、どう実装すべきか） → `docs/design/` の各設計メモ。メモの一覧と要旨は [README.md の「設計メモ（docs/design/）」](README.md#設計メモdocsdesign) にある（ここには列挙しない。二重メンテを避けるため）。
- **リポジトリの地図**（構成・層の分離・処理フロー・主要モジュールの責務） → [README.md](README.md)。
- **セットアップ・使い方・各機能の詳細**（環境変数・静的ポリシー定義・監査ログ・権限スコープ・Embedding・ベンチマーク・DEFER ハンドリングなど） → [README.md の「詳しい使い方（docs/）」](README.md#詳しい使い方docs) からたどれる `docs/*.md`。

**食い違ったときの原則**: 本ファイルの記述と上記の正典が食い違う場合は、**正典を優先**し、その相違を報告すること。本ファイルは案内・索引であり、方針転換の直後などに一時的に古くなっている可能性がある。

## Claude Code 固有の作業規約

これは正典化できない「作業上の約束事」であり、本ファイルに残す。

**テスト基盤を変えない**: 回帰・シナリオテストは `my_project/benchmark.py` のシナリオ追加（`benchmark_data.jsonl` にケース追加、LLM 必須なら `pipeline_only: true`）で行う。新たに pytest 等のテストファイルやテストフレームワークを**追加しない**。これは確定した方針であり、判断の背景と将来導入する場合の基準は [docs/design/laarma-testing-infrastructure.md](docs/design/laarma-testing-infrastructure.md) にある。**テスト基盤を変えたくなったら、実装に入る前に相談すること。**

**設計メモを正典として扱う**: コードと設計メモが食い違っていると気づいたら、勝手にどちらかへ寄せず、相違を報告すること。設計判断を伴う変更（アーキテクチャ・コンポーネントの責務・処理フローの変更など）をするときは、まず `docs/design/` の該当メモを参照し、メモに無い判断が必要なら相談する。

**権限**: merge と delete はリポジトリオーナーが行う。Claude Code は file の読み書き・issue・branch・PR 作成までを担い、merge / ブランチ削除はしない。
