import json
import os
import re
import numpy as np
from typing import Dict, List, Tuple, Any
from sentence_transformers import SentenceTransformer, util
import torch
from logger_utils import enable_console_to_log
import pandas as pd

class SemanticKnowledgeRetriever:
    """基于语义检索的多层级知识库查询系统(混合检索版)"""
    
    def __init__(self, 
                 schema_file: str,
                 formula_file: str, 
                 common_expr_file: str,
                 model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """
        初始化语义检索器
        
        Args:
            schema_file: 数据库表结构JSON文件路径
            formula_file: 公式描述JSON文件路径
            common_expr_file: 常用表达JSON文件路径
            model_name: Sentence Transformer模型名称(支持中文的多语言模型)
        """
        # 加载预训练的Sentence Transformer模型
        print(f"正在加载语义模型: {model_name}...")
        self.model = SentenceTransformer(model_name)
        
        # 加载知识库文件
        self.schema_data = self._load_json(schema_file)
        self.formula_data = self._load_json(formula_file)
        self.common_expr_data = self._load_json(common_expr_file)
        
        # 构建索引
        print("正在构建语义索引...")
        self._build_indexes()
        print("✓ 初始化完成!")
    
    def _load_json(self, filepath: str) -> Dict:
        """加载JSON文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: 无法加载文件 {filepath}: {e}")
            return {}
    
    
    def _keyword_match_score(self, query: str, text: str, predefined_keywords: List[str]) -> float:
        """
        计算关键词匹配得分
        
        匹配策略:
        1. 匹配用户问题和公式中的关键词
        2. 对完全匹配计算加分
        
        Args:
            query: 用户问题
            text: 公式名称或描述
            predefined_keywords: 公式预定义的关键词列表
        
        Returns:
            匹配得分 (0-1之间)
        """
        
        # 将查询转换为小写以进行不区分大小写的匹配
        query_lower = query.lower()
        
        # 使用列表而非集合处理预定义关键词
        predefined_kw_list = [kw.lower() for kw in predefined_keywords]
        
        # 完全匹配加分(如果公式名称的关键词在问题中完整出现)
        exact_match_bonus = 0.0
        for kw in predefined_kw_list:
            if kw in query_lower:
                exact_match_bonus += 0.2  # 每个完全匹配的词加0.2分
        
        # 最终得分 = 完全匹配加分(上限1.0)
        final_score = min(exact_match_bonus, 1.0)
        
        return final_score

    
    def _build_indexes(self):
        """构建公式和数据库表的语义索引"""
        
        # 1. 构建公式描述索引
        self.formula_index = []
        self.formula_keys = []
        self.formula_keywords = []  # 存储每个公式的关键词
        
        for key, formula_info in self.formula_data.get("formulas", {}).items():
            # 组合公式名称、描述和关键词
            text = f"{key} {formula_info.get('description', '')} "
            keywords = formula_info.get('keywords', [])
            # text += " ".join(keywords)
            
            self.formula_index.append(text)
            self.formula_keys.append(key)
            self.formula_keywords.append(keywords)
        
        if self.formula_index:
            self.formula_embeddings = self.model.encode(
                self.formula_index,
                convert_to_tensor=True
            )
            print(f"✓ 已构建 {len(self.formula_index)} 个公式的语义索引")
        
        # 2. 构建数据库表索引
        self.schema_index = []
        self.schema_keys = []
        
        for table_name, table_info in self.schema_data.get("tables", {}).items():
            # 组合表名、描述和字段信息
            text = f"{table_info.get('description', '')} "
            
            # 添加字段描述
            for field_name, field_info in table_info.get('fields', {}).items():
                text += f"{field_info.get('description', '')} "
            
            self.schema_index.append(text)
            self.schema_keys.append(table_name)
        
        if self.schema_index:
            self.schema_embeddings = self.model.encode(
                self.schema_index,
                convert_to_tensor=True
            )
            print(f"✓ 已构建 {len(self.schema_index)} 张表的语义索引")
    
    def retrieve_relevant_context(self, 
                              question: str, 
                              top_k_formula: int = 1,
                              top_k_schema: int = 3,
                              threshold: float = 0.27,
                              keyword_weight: float = 0.7) -> Dict[str, Any]:
        """
        根据问题检索相关上下文(混合检索: 关键词 + 语义)
        
        Args:
            question: 用户问题
            top_k_formula: 检索的公式数量
            top_k_schema: 检索的数据库表数量
            threshold: 相似度阈值(低于此值的结果将被过滤)
            keyword_weight: 关键词得分权重 (0-1),语义得分权重为 1-keyword_weight
                        推荐值: 0.7 (关键词优先) 或 0.5 (平衡)
        
        Returns:
            包含相关上下文的字典
        """
        # 对问题进行编码
        question_embedding = self.model.encode(question, convert_to_tensor=True)
        
        result = {
            "question": question,
            "formulas": [],
            "schemas": [],
        }
        
        # 定义触发公式检索的关键词
        formula_trigger_keywords = [
            "热单耗", "度日数", "度日数单耗", "COP", "热效率", 
            "负荷率", "电单耗", "水单耗", "单耗", "燃气用量", "损失率"
        ]
        
        # 检查问题中是否包含触发关键词
        should_retrieve_formula = any(keyword in question for keyword in formula_trigger_keywords)
        
        # 第一步: 混合检索相关公式(仅当触发条件满足时)
        if should_retrieve_formula and hasattr(self, 'formula_embeddings'):
            print(f"\n检测到公式相关关键词,开始检索公式...")
            
            # 1. 计算语义相似度
            cos_scores = util.cos_sim(question_embedding, self.formula_embeddings)[0]
            
            # 2. 计算混合得分
            hybrid_scores = []
            for idx, key in enumerate(self.formula_keys):
                formula_info = self.formula_data["formulas"][key]
                
                # 组合文本(公式名 + 描述)
                text = f"{key} {formula_info.get('description', '')}"
                keywords = self.formula_keywords[idx]
        
                # 关键词匹配得分
                kw_score = self._keyword_match_score(question, text, keywords)
                
                # 语义相似度得分
                sem_score = cos_scores[idx].item()
                
                # 混合得分 = 加权平均
                final_score = keyword_weight * kw_score + (1 - keyword_weight) * sem_score
                
                hybrid_scores.append((key, final_score, kw_score, sem_score))
            
            # 3. 排序并过滤
            hybrid_scores.sort(key=lambda x: x[1], reverse=True)
            
            print(f"\n检索到的公式(混合得分 Top {top_k_formula}):")
            for key, final_score, kw_score, sem_score in hybrid_scores[:top_k_formula]:
                if final_score >= threshold:
                    print(f"  - {key}")
                    print(f"    关键词: {kw_score:.3f} | 语义: {sem_score:.3f} | 最终: {final_score:.3f}")
                    
                    formula_info = self.formula_data["formulas"][key]
                    result["formulas"].append({
                        "name": key,
                        "score": float(final_score),
                        "keyword_score": float(kw_score),
                        "semantic_score": float(sem_score),
                        "formula": formula_info.get("formula", ""),
                        "description": formula_info.get("description", ""),
                        "parameters": formula_info.get("parameters", {}),
                        "db_mapping": formula_info.get("db_mapping", {})
                    })
        else:
            if not should_retrieve_formula:
                print(f"\n问题中未检测到公式相关关键词,跳过公式检索步骤")
        
        # 第二步: 基于公式的db_mapping检索相关数据库表
        if hasattr(self, 'schema_embeddings'):
            # 从公式中提取涉及的表名
            related_tables = set()
            for formula in result["formulas"]:
                for param, mapping in formula.get("db_mapping", {}).items():
                    table_name = mapping.get("table", "")
                    if table_name:
                        related_tables.add(table_name)
            
            if related_tables:
                print(f"\n从公式映射中提取到 {len(related_tables)} 张相关表:")
                for table in related_tables:
                    print(f"  - {table}")
            
            # 语义检索数据库表
            schema_results = self._semantic_search(
                question_embedding,
                self.schema_embeddings,
                self.schema_keys,
                top_k_schema * 2,  # 扩大候选池
                threshold
            )
            
            # 优先选择公式映射的表(提升权重30%)
            selected_schemas = []
            
            for key, score in schema_results:
                if key in related_tables:
                    # 提升关联表的权重
                    selected_schemas.append((key, score * 1.5))
                else:
                    selected_schemas.append((key, score))
            
            # 排序并取Top K
            selected_schemas.sort(key=lambda x: x[1], reverse=True)
            selected_schemas = selected_schemas[:top_k_schema]
            
            print(f"\n最终选择 {len(selected_schemas)} 张数据表:")
            for key, score in selected_schemas:
                is_mapped = "✓ [公式映射]" if key in related_tables else ""
                print(f"  - {key} (相似度: {score:.3f}) {is_mapped}")
                
                table_info = self.schema_data["tables"][key]
                result["schemas"].append({
                    "table_name": key,
                    "score": float(score),
                    "description": table_info.get("description", ""),
                    "fields": table_info.get("fields", {}),
                    "business_rules": table_info.get("business_rules", []),
                    "is_from_mapping": key in related_tables
                })
        
        return result

    
    def _semantic_search(self, 
                         query_embedding: torch.Tensor,
                         corpus_embeddings: torch.Tensor,
                         corpus_keys: List[str],
                         top_k: int,
                         threshold: float) -> List[Tuple[str, float]]:
        """
        执行语义搜索
        
        Args:
            query_embedding: 查询的嵌入向量
            corpus_embeddings: 语料库的嵌入向量
            corpus_keys: 语料库的键列表
            top_k: 返回的结果数量
            threshold: 相似度阈值
        
        Returns:
            (key, score)元组的列表
        """
        # 计算余弦相似度
        cos_scores = util.cos_sim(query_embedding, corpus_embeddings)[0]
        
        # 获取Top K结果
        top_results = torch.topk(cos_scores, k=min(top_k, len(corpus_keys)))
        
        results = []
        for score, idx in zip(top_results[0], top_results[1]):
            score = score.item()
            if score >= threshold:
                results.append((corpus_keys[idx], score))
        
        return results
    
    def format_context_for_prompt(self, retrieval_result: Dict) -> str:
        """
        将检索结果格式化为系统提示词
        
        结构:
        1. 常用表达(整体背景知识)
        2. 检索到的相关公式(带混合得分)
        3. 检索到的相关数据表
        
        Args:
            retrieval_result: retrieve_relevant_context的返回结果
        
        Returns:
            格式化的上下文字符串
        """
        context_parts = []
        
        # ===== 第一部分: 常用表达(整体作为背景知识) =====
        context_parts.append("# 一、业务背景知识\n")
        context_parts.append("以下是系统中的常用业务表达和时间范围定义,请在理解用户问题时参考:\n")
        
        if self.common_expr_data.get("expressions"):
            for key, expr_info in self.common_expr_data["expressions"].items():
                context_parts.append(f"-{key} 表示含义: {expr_info.get('description', '')}\n")
                
        
        # ===== 第二部分: 检索到的相关公式 =====
        if retrieval_result["formulas"]:
            context_parts.append("\n" + "=" * 80)
            context_parts.append("# 二、相关计算公式\n")
            
            for i, formula in enumerate(retrieval_result["formulas"], 1):
                context_parts.append(f"\n## {i}. {formula['name']}")
                context_parts.append(f"**公式**: {formula['formula']}")
                context_parts.append(f"**说明**: {formula['description']}")
                
                if formula["parameters"]:
                    context_parts.append("\n**参数含义**:")
                    for param, info in formula["parameters"].items():
                        unit = f"({info['unit']})" if info.get('unit') else ""
                        context_parts.append(f"  - {param}: {info['meaning']} {unit}")
                
                if formula["db_mapping"]:
                    context_parts.append("\n**数据库映射**:")
                    for param, mapping in formula["db_mapping"].items():
                        table = mapping.get('table', '')
                        field = mapping.get('field', '')
                        condition = mapping.get('condition', '')
                        note = mapping.get('note', '')
                        
                        mapping_text = f"  - {param}: {table}.{field}"
                        if condition:
                            mapping_text += f"\n    条件: {condition}"
                        if note:
                            mapping_text += f"\n    注意: {note}"
                        context_parts.append(mapping_text)
                
                # 显示详细得分
                context_parts.append(f"\n**检索得分**:")
                context_parts.append(f"  - 关键词匹配: {formula['keyword_score']:.3f}")
                context_parts.append(f"  - 语义相似度: {formula['semantic_score']:.3f}")
                context_parts.append(f"  - 混合得分: {formula['score']:.3f}")
                context_parts.append("")  # 空行
        
        # ===== 第三部分: 检索到的相关数据表 =====
        if retrieval_result["schemas"]:
            context_parts.append("\n" + "=" * 80)
            context_parts.append("# 三、相关数据库表结构\n")
            
            for i, schema in enumerate(retrieval_result["schemas"], 1):
                # 标记是否来自公式映射
                mapping_flag = " [✓ 公式映射]" if schema.get("is_from_mapping") else ""
                
                context_parts.append(f"\n## {i}. 表名: {schema['table_name']}{mapping_flag}")
                context_parts.append(f"**描述**: {schema['description']}")
                
                if schema["fields"]:
                    context_parts.append("\n**字段信息**:")
                    for field_name, field_info in schema["fields"].items():
                        field_type = field_info.get('type', '')
                        field_desc = field_info.get('description', '')
                        field_example = field_info.get('examples', '')
                        field_constraint = field_info.get('constraints', '')
                        context_parts.append(
                            f"  - {field_name} ({field_type}): {field_desc} 示例值: {field_example}"
                        )
                
                if schema.get("business_rules"):
                    context_parts.append("\n**业务规则**:")
                    for rule in schema["business_rules"]:
                        context_parts.append(f"  - {rule}")
                
                # context_parts.append(f"\n**相似度**: {schema['score']:.3f}")
                context_parts.append("")  # 空行
        
        return "\n".join(context_parts)


class EnhancedSchemaLoader:
    """增强的Schema加载器,集成混合检索"""
    
    def __init__(self, 
                 schema_file: str,
                 formula_file: str,
                 common_expr_file: str):
        # 初始化语义检索器
        self.retriever = SemanticKnowledgeRetriever(
            schema_file=schema_file,
            formula_file=formula_file,
            common_expr_file=common_expr_file
        )
    
    def get_context_for_question(self, 
                                question: str,
                                top_k_formula: int = 1,
                                top_k_schema: int = 3,
                                keyword_weight: float = 0.7) -> str:
        """
        根据用户问题获取相关上下文(混合检索)
        
        流程: 问题 → 混合检索公式 → 数据表检索
        
        Args:
            question: 用户问题
            top_k_formula: 检索的公式数量
            top_k_schema: 检索的数据库表数量
            keyword_weight: 关键词权重(0-1),推荐0.7
        
        Returns:
            格式化的上下文字符串(包含常用表达、公式、数据表)
        """
        print(f"\n{'='*80}")
        print(f"开始处理问题: {question}")
        print(f"{'='*80}")
        
        # 执行混合检索
        retrieval_result = self.retriever.retrieve_relevant_context(
            question=question,
            top_k_formula=top_k_formula,
            top_k_schema=top_k_schema,
            keyword_weight=keyword_weight
        )
        
        # 格式化为提示词
        context = self.retriever.format_context_for_prompt(retrieval_result)
        
        return context
    
    def get_schema_prompt(self, question: str, keyword_weight: float = 0.7) -> str:
        """
        获取完整的系统提示词
        
        Args:
            question: 用户问题
            keyword_weight: 关键词权重(推荐0.7)
        
        Returns:
            系统提示词
        """
        # 使用混合检索获取相关内容
        context = self.get_context_for_question(question, keyword_weight=keyword_weight)
        

        prompt = f"""# 数据库知识库

**用户问题**: {question}

{context}

---
**使用说明**:
1. "业务背景知识"部分包含了所有常用表达和时间范围定义,请优先参考
2. "相关计算公式"是根据混合检索(关键词{keyword_weight:.0%}+语义{1-keyword_weight:.0%})得到的,其中的"数据库映射"指明了如何从数据表中获取数据
3. "相关数据库表结构"包含了需要查询的表,标记为[✓ 公式映射]的表是从公式中直接提取的,可信度更高
"""
        
        return prompt


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # enable_console_to_log(prefix="schema_loader_log")
    # 初始化加载器
    loader = EnhancedSchemaLoader(
        schema_file=r"data\schema_knowledge_base.json",
        formula_file=r"data\formula_knowledge_base.json",
        common_expr_file=r"data\common_expressions.json"
    )
    

    # 测试问题
    test_questions = [
        "2024-2025供暖季商河所有换热站的度日数热单耗最高的5个是哪5个？"
    ]

    # 读取 Excel
    df = pd.read_excel(r"data\验证集评测75题.xlsx")

    # 提取“问题”列为列表
    questions = df["问题"].tolist()
    
    print("\n" + "=" * 80)
    print("混合检索系统测试(关键词 + 语义)")
    print("=" * 80)
    
    # 测试不同权重
    weights_to_test = [0.7]  # 关键词权重
    
    for weight in weights_to_test:
        print(f"\n\n{'#'*80}")
        print(f"测试权重配置: 关键词={weight:.0%}, 语义={1-weight:.0%}")
        print(f"{'#'*80}")
        
        for i, question in enumerate(test_questions, 1):
            # 获取完整提示词
            prompt = loader.get_schema_prompt(question, keyword_weight=weight)
            print(prompt)
    
    print("\n" + "=" * 80)
    print("测试完成!")
    print("=" * 80)
