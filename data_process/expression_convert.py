import pandas as pd
import re
import json
from typing import List, Dict, Tuple


class CommonExpressionEnhancer:
    def __init__(self, common_express_file: str):
        """
        初始化常用表达增强器

        Args:
            common_express_file: 常用表达文件路径
        """
        self.common_expressions = self.load_common_expressions(common_express_file)
        self.enhancement_rules = self.build_enhancement_rules()

    def load_common_expressions(self, file_path: str) -> List[str]:
        """加载常用表达数据"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 解析列表格式的常用表达
            if content.startswith('common_express = ['):
                # 提取列表内容
                start = content.find('[') + 1
                end = content.find(']')
                list_content = content[start:end]

                # 分割列表项
                expressions = []
                current_expr = ""
                in_quotes = False
                quote_char = None

                for char in list_content:
                    if char in ['"', "'"] and not in_quotes:
                        in_quotes = True
                        quote_char = char
                        current_expr += char
                    elif char == quote_char and in_quotes:
                        in_quotes = False
                        current_expr += char
                    elif char == ',' and not in_quotes and current_expr.strip():
                        expressions.append(current_expr.strip().strip('"').strip("'"))
                        current_expr = ""
                    else:
                        current_expr += char

                if current_expr.strip():
                    expressions.append(current_expr.strip().strip('"').strip("'"))

                return expressions
            else:
                # 如果不是列表格式，按行读取
                return [line.strip() for line in content.split('\n') if line.strip()]

        except Exception as e:
            print(f"加载常用表达文件失败: {e}")
            return []

    def build_enhancement_rules(self) -> List[Dict]:
        """构建增强规则"""
        rules = []

        for expr in self.common_expressions:
            if "表示含义为：" in expr:
                parts = expr.split("表示含义为：")
                if len(parts) == 2:
                    pattern = parts[0].strip()
                    meaning = parts[1].strip()
                    # 处理包含多个词汇的情况（如'供热量'、'用热量'等）
                    if "、" in pattern and "等" in pattern:
                        # 提取引号内的词汇
                        words = re.findall(r"['\"]([^'\"]+)['\"]", pattern)
                        for word in words:
                            rules.append({
                                'pattern': word,
                                'meaning': meaning,
                                'type': 'direct_mapping'
                            })
                    else:
                        rules.append({
                            'pattern': pattern,
                            'meaning': meaning,
                            'type': 'direct_mapping'
                        })
            elif "表述含义：" in expr:
                parts = expr.split("表述含义：")
                if len(parts) == 2:
                    pattern = parts[0].strip()
                    meaning = parts[1].strip()
                    # 处理包含多个词汇的情况
                    if "、" in pattern and "等" in pattern:
                        words = re.findall(r"['\"]([^'\"]+)['\"]", pattern)
                        for word in words:
                            rules.append({
                                'pattern': word,
                                'meaning': meaning,
                                'type': 'direct_mapping'
                            })
                    else:
                        rules.append({
                            'pattern': pattern,
                            'meaning': meaning,
                            'type': 'direct_mapping'
                        })
            elif "表示：" in expr:
                parts = expr.split("表示：")
                if len(parts) == 2:
                    pattern = parts[0].strip()
                    meaning = parts[1].strip()
                    rules.append({
                        'pattern': pattern,
                        'meaning': meaning,
                        'type': 'direct_mapping'
                    })
            elif "的含义为：" in expr:
                parts = expr.split("的含义为：")
                if len(parts) == 2:
                    pattern = parts[0].strip()
                    meaning = parts[1].strip()
                    rules.append({
                        'pattern': pattern,
                        'meaning': meaning,
                        'type': 'direct_mapping'
                    })
        indicators = ['用热量', '供热量', '用电量', '补水量', '用气量']

        # 添加通用规则
        additional_rules = ([
                                {
                                    'pattern': r'(\d{4}-\d{4})供暖季',
                                    'replacement': r'\1供暖季(前一年11月15日00:00:00至第二年03月15日00:00:00)',
                                    'type': 'regex'
                                },
                                {
                                    'pattern': r'(\d{4}-\d{4})采暖季',
                                    'replacement': r'\1采暖季(前一年11月15日00:00:00至第二年03月15日00:00:00)',
                                    'type': 'regex'
                                },
                                {
                                    'pattern': r'(\d{4}-\d{4})供热季',
                                    'replacement': r'\1供热季(前一年11月15日00:00:00至第二年03月15日00:00:00)',
                                    'type': 'regex'
                                },
                                {
                                    'pattern': r'(\d{2}-\d{2})供热季',
                                    'replacement': r'\1供热季(前一年11月15日00:00:00至第二年03月15日00:00:00)',
                                    'type': 'regex'
                                },
                                {
                                    'pattern': r'(\d{4})年(\d{1,2})月(\d{1,2})日',
                                    'replacement': r'\1年\2月\3日(00:00:00-23:59:59)',
                                    'type': 'regex'
                                },
                                {
                                    'pattern': '平均/最高/最低',
                                    'replacement': '统计指标(平均值、最大值、最小值)',
                                    'type': 'direct'
                                },
                                {
                                    'pattern': '总燃气用量',
                                    'replacement': '总燃气用量(即4台锅炉和2台热泵的燃气用量的总和)',
                                    'type': 'direct'
                                }
                            ] + [
                                {
                                    'pattern': indicator,
                                    'replacement': f'{indicator}({indicator}计算公式是用给定时间段结束时刻的值减去给定时间段开始时刻的值求差)',
                                    'type': 'direct'
                                } for indicator in indicators
                            ])

        rules.extend(additional_rules)
        return rules

    def enhance_question(self, question: str) -> str:
        """
        增强问题表述

        Args:
            question: 原始问题

        Returns:
            增强后的问题
        """
        enhanced = question

        # 应用直接映射规则
        for rule in self.enhancement_rules:
            if rule['type'] == 'direct_mapping':
                # 检查模式是否在问题中
                if rule['pattern'] in enhanced:
                    # 避免重复添加含义说明
                    if f"({rule['meaning']})" not in enhanced:
                        enhanced = enhanced.replace(rule['pattern'], f"{rule['pattern']}({rule['meaning']})")

            elif rule['type'] == 'direct':
                if rule['pattern'] in enhanced:
                    enhanced = enhanced.replace(rule['pattern'], rule['replacement'])

            elif rule['type'] == 'regex':
                enhanced = re.sub(rule['pattern'], rule['replacement'], enhanced)

        # 添加时间解释（避免重复）
        time_patterns = [
            (r'(\d{4}-\d{4})供暖季', '供暖季时间为前一年11月15日00:00:00至第二年03月15日00:00:00'),
            (r'(\d{4})年(\d{1,2})月(\d{1,2})日', '该日期表示从00:00:00到23:59:59的完整时间段')
        ]

        for pattern, explanation in time_patterns:
            if re.search(pattern, enhanced):
                # 检查是否已经包含类似的时间解释
                if not any(time_expr in enhanced for time_expr in ['00:00:00', '23:59:59', '完整时间段']):
                    enhanced += f" [{explanation}]"

        return enhanced

    def batch_enhance_questions(self, questions: List[str]) -> List[str]:
        """批量增强问题"""
        return [self.enhance_question(q) for q in questions]

    def analyze_enhancement(self, original_question: str, enhanced_question: str) -> Dict:
        """分析增强效果"""
        return {
            'original': original_question,
            'enhanced': enhanced_question,
            'length_increase': len(enhanced_question) - len(original_question),
            'enhancement_ratio': len(enhanced_question) / len(original_question) if original_question else 0
        }


def main():
    # 初始化增强器
    enhancer = CommonExpressionEnhancer('常用表达.txt')

    # 打印加载的常用表达
    print("加载的常用表达:")
    for i, expr in enumerate(enhancer.common_expressions, 1):
        print(f"{i}. {expr}")

    print("\n构建的增强规则:")
    for i, rule in enumerate(enhancer.enhancement_rules, 1):
        print(f"{i}. 模式: '{rule['pattern']}' -> 含义: '{rule.get('meaning', rule.get('replacement', ''))}'")

    # 读取Excel文件
    try:
        df = pd.read_excel('拓展问题(8-9).xlsx')

        print(f"\n读取到 {len(df)} 个问题")

        # 准备输出数据
        output_data = []
        enhancement_analysis = []

        for index, row in df.iterrows():
            original_question = row['题目']
            # 假设SQL列名为'生成的sql'，如果不是请修改为实际的列名
            sql = row.get('生成的sql', '')  # 如果没有SQL列，默认为空字符串

            enhanced_question = enhancer.enhance_question(original_question)

            # 构建输出对象
            output_item = {
                "序号": index + 1,
                "题目": enhanced_question,
                "生成的sql": sql,
                "原始题目": original_question
            }
            output_data.append(output_item)

            analysis = enhancer.analyze_enhancement(original_question, enhanced_question)
            enhancement_analysis.append(analysis)

            print(f"\n序号: {index + 1}")
            print(f"原始问题: {original_question}")
            print(f"增强问题: {enhanced_question}")
            print(f"SQL: {sql}")
            print(f"增强比例: {analysis['enhancement_ratio']:.2f}")

        # 保存为JSON文件
        output_json_file = '增强后的问题集.json'
        with open(output_json_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\n增强后的问题已保存到JSON文件: {output_json_file}")

        # 统计信息
        total_length_increase = sum([a['length_increase'] for a in enhancement_analysis])
        avg_enhancement_ratio = sum([a['enhancement_ratio'] for a in enhancement_analysis]) / len(enhancement_analysis)

        print(f"\n增强统计:")
        print(f"总长度增加: {total_length_increase} 字符")
        print(f"平均增强比例: {avg_enhancement_ratio:.2f}")

    except Exception as e:
        print(f"处理Excel文件时出错: {e}")


if __name__ == "__main__":
    main()