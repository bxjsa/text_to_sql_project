# 🏆 神思杯·全球人工智能算法大赛：能源热力问数挑战赛 - Magic AI 团队方案

![License](https://img.shields.io/badge/license-Apache%202.0-blue)
![Model](https://img.shields.io/badge/Model-DeepSeek-blueviolet)
![Award](https://img.shields.io/badge/Award-National%203rd%20Prize-orange)
![Accuracy](https://img.shields.io/badge/Validation-98.6%25-brightgreen)

> **2025 “神思杯”全球人工智能算法大赛 - 国家三等奖获奖作品**
> 
> [cite_start]团队名称：Magic AI
> 
> 核心亮点：基于 DeepSeek 大模型，融合 M-Schema 结构化知识与“生成-诊断-修正”双重闭环机制。

## 📖 项目简介
[cite_start]本项目聚焦于**能源供热领域的 Text-to-SQL 任务**。针对传统模型在处理行业专业术语、复杂表结构（Schema）以及逻辑推理时的痛点，我们提出了一套**基于硬约束混合检索与双重验证机制**的解决方案 [cite: 10, 140]。

[cite_start]本方案在比赛验证集中达到了 **98.667%** 的准确率，在复赛打榜中保持了 **92%** 的高准确率。

## 🏗️ 核心架构
我们的模型摒弃了传统的端到端生成，采用“迭代式 SQL 查询生成与验证”框架。

![整体架构图]<img width="742" height="222" alt="模型整体架构" src="https://github.com/user-attachments/assets/c956ac96-39e7-430f-8f26-f0bea124b58e" />


### 核心技术模块：
1.  [cite_start]**数据预处理 (Structured Pre-processing)**
    * [cite_start]**M-Schema**: 构建半结构化数据库模式，清晰展示表间层级与外键关系
    * [cite_start]**语义槽解析**: 将用户问题解构为 Entity, Target, Time 等原子单元，降低噪声 

2.  [cite_start]**数据表链接 (Hybrid Schema Linking)** 
    * [cite_start]采用 **70% 关键词匹配 + 30% 语义匹配** 的加权混合检索策略
    * 针对公式计算，设计了“公式锁定数据表”的硬约束规则，解决语义漂移问题。

3.  [cite_start]**Few-shot Chain-of-Thought (CoT)**
    * 不仅仅生成 SQL，还强制模型输出 `reason` (业务逻辑)、`columns` (涉及字段) 和 `SQL-Like` 中间表达，增强可解释性。

4.  [cite_start]**双重验证与修正机制 (Dual Verification)** 
    * [cite_start]**第一重：语义检查**。基于 AST (抽象语法树) 进行静态分析，结合 M-Schema 校验字段存在性。
    * [cite_start]**第二重：执行检查**。在本地数据库试运行，捕获运行时错误（如空结果、逻辑冲突），并反馈给模型进行自我修正。

## 📊 效果展示
[cite_start]模型在不同阶段的测试表现如下：

| 测试阶段 | 题目数量 | 正确个数 | 正确率 |
| :--- | :--- | :--- | :--- |
| 初赛打榜 | 25 | 25 | **100%** |
| 验证集 | 75 | 74 | **98.67%** |
| 复赛打榜 | 25 | 23 | **92%** |

## 🚀 快速开始

### 环境依赖
* Python 3.8+
* DeepSeek API (或其他 LLM 接口)
* 本地数据库环境 (用于执行验证)

### 安装与运行
```bash
# 1. 克隆项目
git clone [https://github.com/你的用户名/项目名.git](https://github.com/你的用户名/项目名.git)

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 Config
# 在 config.py 中填入你的 API Key 和数据库连接信息

# 4. 运行推理
python main.py
