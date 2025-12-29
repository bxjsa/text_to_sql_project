from __future__ import annotations

import numpy as np
from typing import List, Dict, Optional
import json
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


class RAGText:
    """
    检索增强的Text系统(结合语义相似度 + 关键词匹配)
    """
    
    def __init__(self, training_samples: List[Dict]):
        """
        初始化RAG系统
        
        Args:
            training_samples: 训练样本列表,每个样本应包含 '原始题目'、'生成的sql' 和 'slots' 字段
        """
        self.training_samples: List[Dict] = training_samples
        
        # 使用轻量级中文embedding模型
        self.embedding_model: SentenceTransformer = SentenceTransformer(
            'paraphrase-multilingual-MiniLM-L12-v2'
        )
        self.example_embeddings: Optional[np.ndarray] = None
        self._build_example_index()
    
    def _build_example_index(self) -> None:
        """构建示例向量索引"""
        print("🔧 构建示例向量索引...")
        questions = [s['原始题目'] for s in self.training_samples]
        self.example_embeddings = self.embedding_model.encode(questions)
        print(f"✅ 索引构建完成,共 {len(self.example_embeddings)} 个示例")
    
    def _extract_keywords_from_slots(self, sample: Dict) -> List[str]:
        """
        从样本的 slots 中提取关键词
        
        Args:
            sample: 训练样本,包含 'slots' 字段
            
        Returns:
            关键词列表
        """
        keywords = []
        if 'slots' in sample and sample['slots']:
            slots = sample['slots']
            # 从 target 字段提取关键词
            if 'target' in slots and slots['target']:
                target = slots['target'].strip()
                # print(target)
                if target:
                    keywords.append(target)
                if target == "产生多少热量":
                    keywords.append("产热量")
        return keywords
    
    def _calculate_keyword_score(self, query: str, keywords: List[str]) -> float:
        """
        计算关键词匹配得分
        
        Args:
            query: 用户查询
            keywords: 候选样本的关键词列表
            
        Returns:
            关键词匹配得分 (0-1之间)
        """
        if not keywords:
            return 0.0
        
        # 计算有多少关键词出现在query中
        matched_count = sum(1 for keyword in keywords if keyword in query)
        
        # 归一化得分
        score = matched_count / len(keywords)
        return score
    
    def retrieve_relevant_examples(
        self, 
        query: str, 
        top_k: int = 2,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4,
        min_score: float = 0.2
    ) -> List[Dict]:
        """
        基于语义相似度 + 关键词匹配检索最相关的示例
        
        Args:
            query: 用户查询
            top_k: 返回top-k个示例
            semantic_weight: 语义相似度权重
            keyword_weight: 关键词匹配权重
            min_score: 最小综合得分阈值
            
        Returns:
            相关示例列表,按综合得分排序
        """
        if self.example_embeddings is None:
            raise ValueError("示例索引未构建")
        
        # 1. 计算语义相似度
        query_embedding = self.embedding_model.encode([query])
        semantic_similarities = cosine_similarity(query_embedding, self.example_embeddings)[0]
        
        # 2. 计算关键词匹配得分
        keyword_scores = []
        for sample in self.training_samples:
            keywords = self._extract_keywords_from_slots(sample)
            keyword_score = self._calculate_keyword_score(query, keywords)
            keyword_scores.append(keyword_score)
        keyword_scores = np.array(keyword_scores)
        
        # 3. 计算综合得分
        combined_scores = (
            semantic_weight * semantic_similarities + 
            keyword_weight * keyword_scores
        )
        
        # 4. 获取top-k索引（排除语义相似度为1的示例）
        # 创建有效索引列表，排除语义相似度接近1.0的样本
        valid_indices = [i for i in range(len(semantic_similarities)) 
                        if not np.isclose(semantic_similarities[i], 1.0)]
    
        # 获取有效样本的得分
        valid_scores = combined_scores[valid_indices]
        
        # 在有效样本中排序
        sorted_valid_indices = np.argsort(valid_scores)[::-1][:top_k]
        
        # 映射回原始索引
        top_indices = [valid_indices[i] for i in sorted_valid_indices]
        
        # 5. 过滤低于阈值的示例
        relevant_examples = []
        for idx in top_indices:
            if combined_scores[idx] >= min_score:
                relevant_examples.append({
                    **self.training_samples[idx],
                    'semantic_similarity': float(semantic_similarities[idx]),
                    'keyword_score': float(keyword_scores[idx]),
                    'combined_score': float(combined_scores[idx])
                })
        
        return relevant_examples

    
    def generate_prompt_with_rag(
        self, 
        query: str,
        top_k: int = 3,
        semantic_weight: float = 0.6,
        keyword_weight: float = 0.4
    ) -> str:
        """
        使用RAG找到相似度最高的前k个训练样本
        若没有找到相关示例,则返回空字符串
        
        Args:
            query: 用户查询
            top_k: 返回top-k个示例
            semantic_weight: 语义相似度权重
            keyword_weight: 关键词匹配权重
        """
        # 检索相关示例
        relevant_examples = self.retrieve_relevant_examples(
            query, 
            top_k=top_k,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight
        )
        
        # 如果没有检索到相关示例,返回空字符串
        if not relevant_examples or len(relevant_examples) == 0:
            return ""
        
        # 加载推理过程
        with open(r"data\llm_train_parse.json", "r", encoding="utf-8") as f:
            reason_samples = json.load(f)
        parse_dict = {sample['原始题目']: sample['parse'] for sample in reason_samples}
        
        prompt = f"""

## 以下是与本次查询语义相近的问题示例和推理过程,可进行参考:

## 相似示例(RAG Top-{top_k})
"""

        for i, ex in enumerate(relevant_examples, 1):
            parse_content = parse_dict.get(ex['原始题目'], "")
            
            # 提取关键词用于展示
            keywords = self._extract_keywords_from_slots(ex)
            keywords_str = ", ".join(keywords) if keywords else "无"
            
            print(f"示例{i}: {ex['原始题目']}")
            print(f"  - 语义相似度: {ex['semantic_similarity']:.3f}")
            print(f"  - 关键词得分: {ex['keyword_score']:.3f}")
            print(f"  - 综合得分: {ex['combined_score']:.3f}")
            print(f"  - 匹配关键词: {keywords_str}")

            prompt += f"""
#########################################示例{i}######################################
##问题##: {ex['原始题目']}
##推理过程##:
{parse_content}
"""
            
        return prompt


if __name__ == "__main__":
    # 1) 读取 JSON 数据
    with open(r"data\llm_train_parse.json", "r", encoding="utf-8") as f:
        training_samples = json.load(f)

    # 2) 传入 RAG 类
    rag = RAGText(training_samples)

    # 3) 测试不同的查询
    test_queries = [
        "恒泰热源厂2024-2025供热季每日热单耗最大的是哪一天？"
    ]
    
    for query in test_queries:
        print("\n" + "="*80)
        print(f"查询: {query}")
        print("="*80)
        
        # 可以调整权重参数
        prompt = rag.generate_prompt_with_rag(
            query, 
            top_k=2,
            semantic_weight=0.6,  # 语义相似度权重
            keyword_weight=0.4    # 关键词匹配权重
        )
        
        print("\n生成的Prompt:")
        print(prompt)