# Grounded Tutor

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

学习者使用自己的讲义、笔记与 Office 资料，围绕学习主题提问并核对依据。

## Product Purpose

把资料、带引用的回答和学习活动放在同一个工作区；结论可追溯到实际资料片段。

## Operating Context

本地桌面使用。每个学习主题保存独立的资料、问答历史及学习进度。先导入资料，复核实际处理结果，接受后用于问答。

## Capabilities and Constraints

- 已有 ASK、结构化回答、编号引用、原文定位、历史回显与主题隔离。
- 已有诊断、学习计划、讲解、练习及学习活动恢复。
- 本地后端管理产品状态，FastGPT 提供资料处理、检索及专用生成应用。
- 发布范围为源码下载与本地部署；附带可在本地运行的固定只读示例。
- 支持创建、重命名和删除主题；删除同时清理关联资料、对话与学习进度。
- 当前范围不含移动端、图片支持、登录或未实现功能的按钮占位。
- 一般知识回答加上传提醒已列入计划，尚未实现。

## Brand Commitments

保留 Grounded Tutor 名称。使用中文操作文案。采用石灰白与酒红的书页式视觉，固定主题栏与问答／依据双栏；详见 DESIGN.md。

## Evidence on Hand

apps/web/src/demo/fixture.ts 为可公开的合成 RAG 示例。本轮方案只使用这一主题及示例内容，不复制私有资料。

## Product Principles

- 回答与依据可核对。
- 输入、错误及禁用状态必须明确。
- 一项主要操作有一个清楚入口。
- 不以未实现的功能装饰页面。
