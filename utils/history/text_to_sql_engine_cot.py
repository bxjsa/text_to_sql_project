"""
Text-to-SQL核心引擎 - 基于DeepSeek API
集成SQL静态检查、强反馈自动修正功能、思维链
"""
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, TEMPERATURE, MAX_TOKENS, TOP_P, SCHEMA_FILE, FORMULA_FILE, COMMON_EXPR_FILE
from sql_checker import SQLRuleChecker  # 【新增】导入SQL检查器
import time
import re
from utils.rag_to_prompt import RAGText
from enhanced_schema_loader import EnhancedSchemaLoader
import json

class TextToSQLEngine3: 
    """基于DeepSeek的Text-to-SQL引擎（强反馈+思维链版本）"""  # 【修改】文档字符串更新

    def __init__(self, training_samples):
        """初始化DeepSeek客户端和Schema加载器"""
        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL
        )
        # 初始化Schema加载器
        self.ragtext = RAGText(training_samples)

        # 【新增】初始化SQL检查器，包含错误处理机制
        try:
            self.sql_checker = SQLRuleChecker()
            print("✓ SQL检查器初始化成功")
        except Exception as e:
            print(f"⚠ 警告: SQL检查器初始化失败 ({e})，将跳过SQL检查")
            self.sql_checker = None

    def _build_system_prompt_CoT(self, question: str) -> str:
        """构建系统提示词（思维链版本）"""
        self.loader = EnhancedSchemaLoader(SCHEMA_FILE, FORMULA_FILE, COMMON_EXPR_FILE)
        self.schema_prompt = self.loader.get_schema_prompt(question, keyword_weight=0.7)
        self.rag_prompt = self.ragtext.generate_prompt_with_rag(question)
        
        return f"""你是一个专业的SQL查询生成专家，专门处理能源供热领域的数据查询任务。

你的任务是：根据用户的自然语言问题，按照思维链方式逐步分析并生成准确的、MySQL支持的SQL查询语句。

{self.schema_prompt}

## 重要规则：

1. **表名和字段名准确性**：严格使用上述提供的表名和字段名，不要臆造，同时谨慎使用示例值，这通常包含不完整的信息
2. **业务逻辑**：
- 商河热源厂指标需要计算src_id为1和2的总和（商河恒泰热源厂和玉泉生物质电厂）
- 换热站指标需要注意机组数量（plan_num）
- 累计量计算使用结束时间值减去开始时间值
- 总燃气用量需考虑blr_id为1、2、3、4(4台锅炉)和pump_id为1、2(2台热泵)的燃气用量
3. **公式计算**：严格按照公式描述中的计算逻辑生成SQL
4. **输出格式要求**：
- 第一部分：输出你的分析思考过程（使用<思考>标签包裹）
- 第二部分：输出最终的SQL语句（使用<SQL>标签包裹）
5. **SQL类型限制**：
- 只能生成SELECT查询语句
- 禁止使用UPDATE、DELETE、INSERT、DROP、CREATE、ALTER、TRUNCATE等修改数据的语句
- 筛选条件中使用字段名时，避免使用包含敏感关键词的字段（如is_delete字段改用其他条件）

{self.rag_prompt}

## 思维链分析步骤：

请按以下步骤进行思考和分析：

**步骤1 - 理解问题意图**：
- 用户想要查询什么信息？
- 涉及哪些业务概念（如热源厂、换热站、锅炉等）？
- 需要什么样的统计维度（时间、地点、设备等）？
- 是否涉及计算或聚合？

**步骤2 - 识别相关表和列**：
- 根据业务概念，确定需要查询哪些表？
- 每个表需要选择哪些字段？
- 这些字段的中文含义是否匹配问题需求？
- 是否需要使用公式计算字段？

**步骤3 - 确定连接关系**：
- 多个表之间如何关联（JOIN条件）？
- 使用什么类型的JOIN（INNER/LEFT/RIGHT）？
- 关联字段是什么？

**步骤4 - 确定筛选和聚合逻辑**：
- 需要什么WHERE条件？
- 是否需要GROUP BY？按什么字段分组？
- 需要什么聚合函数（SUM/AVG/COUNT等）？
- 是否需要HAVING条件？
- 是否需要排序（ORDER BY）？

**步骤5 - 构建SQL查询**：
- 根据以上分析，组装完整的SQL语句
- 检查语法正确性
- 验证业务逻辑合理性

"""

    def _build_user_prompt(self, question):
        """构建用户提示词（思维链版本 - 首次生成）"""
        with open(r"text_to_sql_project\data\llm_train_parse_v2.json", "r", encoding="utf-8") as f:
            reason_samples = json.load(f)
        enhanced_question_dict = {sample['原始题目']: sample['题目'] for sample in reason_samples}
        enhanced_question = enhanced_question_dict.get(question, "")
        
        return f"""请根据以下问题，按照思维链方式进行分析并生成SQL查询语句：

**原始问题**：{question}

**增强表达的问题**：{enhanced_question}

请严格按照以下格式输出：

<思考>
[在这里写出你的分析过程，包括：]
1. 问题意图理解：...
2. 相关表和列识别：...
3. 连接关系确定：...
4. 筛选和聚合逻辑：...
5. SQL构建思路：...
</思考>

<SQL>
[在这里写出最终的SQL语句，以分号结尾]
</SQL>

现在请开始分析："""

    def _build_feedback_prompt(self, question, previous_sql, check_result, attempt):
        """
        构建强反馈提示词（思维链版本）

        根据SQL检查结果生成包含详细反馈信息的提示词，引导模型重新思考并优化SQL
        """
        feedback = check_result.get('feedback', {})
        errors = check_result.get('errors', [])
        warnings = check_result.get('warnings', [])

        prompt_parts = []

        # 1. 基本信息
        if attempt == 2:
            prompt_parts.append("你刚才生成的SQL已经过检查，发现了一些问题。请重新进行分析和优化。")
        else:
            prompt_parts.append("你第二次生成的SQL仍存在问题，这是最后一次修正机会。请仔细重新分析。")

        prompt_parts.append(f"\n**原始问题**：\n{question}")
        prompt_parts.append(f"\n**你上次生成的SQL**：\n{previous_sql}")

        # 2. 错误和警告信息
        if errors or warnings:
            prompt_parts.append("\n## 检测到的问题：")
            if errors:
                prompt_parts.append("\n**❌ 错误**：")
                for error in errors:
                    prompt_parts.append(f"  - {str(error)}")
            if warnings:
                prompt_parts.append("\n**⚠️ 警告**：")
                for warning in warnings:
                    prompt_parts.append(f"  - {str(warning)}")
        else:
            prompt_parts.append("\n## 检查结果：未检测到明显错误，但可能需要优化")

        # 3. 表名映射反馈
        table_mappings = feedback.get('table_mappings', {})
        if table_mappings:
            prompt_parts.append("\n## 你使用的表信息：")
            for eng_table, chn_desc in table_mappings.items():
                prompt_parts.append(f"  📊 {eng_table} → {chn_desc}")

        # 4. 字段映射反馈
        field_mappings = feedback.get('field_mappings', {})
        if field_mappings:
            prompt_parts.append("\n## 你使用的字段信息：")
            for table, fields in field_mappings.items():
                prompt_parts.append(f"\n  **表 [{table}]**：")
                for eng_field, chn_desc in fields.items():
                    prompt_parts.append(f"    📋 {eng_field} → {chn_desc}")

        # 5. 单位信息反馈
        units = feedback.get('units', {})
        if units:
            prompt_parts.append("\n## 字段单位信息：")
            for field, unit in units.items():
                prompt_parts.append(f"  📏 {field} 的单位: {unit}")

        # 6. 重新分析指导
        prompt_parts.append("\n## 请重新进行思维链分析：")
        prompt_parts.append("\n请特别注意以下方面的重新思考：")
        
        if errors:
            prompt_parts.append("- **步骤1重审**：问题意图理解是否准确？是否遗漏了关键信息？")
            prompt_parts.append("- **步骤2重审**：选择的表和字段是否正确？根据上述反馈的中文含义重新验证")
        else:
            prompt_parts.append("- **步骤2优化**：虽然没有明显错误，但根据字段的中文含义，是否有更准确的字段可用？")
        
        prompt_parts.append("- **步骤3重审**：表的关联关系是否合理？JOIN类型是否正确？")
        prompt_parts.append("- **步骤4重审**：筛选条件、聚合逻辑是否符合问题要求？")
        
        if units:
            prompt_parts.append("- **单位检查**：涉及的字段单位是否需要转换？计算逻辑是否考虑了单位？")
        
        prompt_parts.append("\n请严格按照以下格式输出优化结果：")
        prompt_parts.append("\n<思考>")
        prompt_parts.append("[重新写出你的分析过程，特别说明与上次的改进点]")
        prompt_parts.append("</思考>")
        prompt_parts.append("\n<SQL>")
        prompt_parts.append("[优化后的完整SQL语句，以分号结尾]")
        prompt_parts.append("</SQL>")
        prompt_parts.append("\n现在请开始重新分析：")

        return '\n'.join(prompt_parts)


    def _format_check_result(self, result):
        """
        格式化检查结果用于日志输出

        【新增方法】将检查结果字典格式化为易读的字符串

        Args:
            result: 检查结果字典
        """
        # 【健壮性检查】处理非字典类型的结果
        if not isinstance(result, dict):
            return f"检查结果格式异常: {result}"

        lines = []

        # 格式化错误信息
        errors = result.get('errors', [])
        if errors:
            lines.append("检测到的错误:")
            for error in errors:
                error_str = str(error)
                # 如果错误信息已包含符号则保持，否则添加 ✗ 符号
                lines.append(f"  {error_str}" if error_str.startswith('❌') else f"  ✗ {error_str}")

        # 格式化警告信息
        warnings = result.get('warnings', [])
        if warnings:
            lines.append("检测到的警告:")
            for warning in warnings:
                warning_str = str(warning)
                # 如果警告信息已包含符号则保持，否则添加 ⚠ 符号
                lines.append(f"  {warning_str}" if warning_str.startswith('⚠️') else f"  ⚠ {warning_str}")

        return '\n'.join(lines) if lines else "无错误或警告"
    def extract_sql_from_response(self, response: str) -> str:
        """从思维链响应中提取SQL语句"""
        import re
        
        # 提取<SQL>标签中的内容
        sql_match = re.search(r'<SQL>(.*?)</SQL>', response, re.DOTALL | re.IGNORECASE)
        if sql_match:
            sql = sql_match.group(1).strip()
            return sql
        
        # 如果没有标签，尝试直接提取SQL（向后兼容）
        lines = response.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.upper().startswith('SELECT'):
                return line
        
        return response.strip()


    def generate_sql(self, question, max_attempts=3):
        """
        生成SQL查询语句（强反馈版本）

        【核心方法重构】实现3次强反馈机制：
        - 第1次：生成 → 检查 → 必定反馈
        - 第2次：生成 → 检查 → 错误才反馈
        - 第3次：生成 → 结束（无论对错）

        Args:
            question: 自然语言问题
            max_attempts: 固定为3次（忽略其他值）

        Returns:
            生成的SQL语句
        """
        # 【参数校验】确保使用3次尝试机制
        if max_attempts != 3:
            print(f"⚠ 警告：强反馈模式固定为3次尝试，已忽略参数max_attempts={max_attempts}")

        system_prompt = self._build_system_prompt_CoT(question)
        last_sql = ""  # 保存上一次生成的SQL
        last_check_result = {}  # 保存上一次的检查结果

        for attempt in range(1, 4):  # 固定3次循环：1, 2, 3
            try:
                # ========== 构建提示词 ==========
                if attempt == 1:
                    # 【第1次】使用普通提示词
                    user_prompt = self._build_user_prompt(question)
                    temperature = TEMPERATURE  # 使用配置的temperature
                else:
                    # 【第2/3次】使用包含反馈信息的提示词
                    user_prompt = self._build_feedback_prompt(
                        question, last_sql, last_check_result, attempt
                    )
                    temperature = 0.1  # 修正时降低随机性，提高稳定性

                # ========== 调用大模型生成SQL ==========
                response = self.client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    max_tokens=MAX_TOKENS,
                    top_p=TOP_P
                )

                print("%"*80)
                print(system_prompt)
                print("%"*80)
                print("&"*80)
                print(user_prompt)
                print("&"*80)


                # 提取并清理生成的SQL
                text = response.choices[0].message.content
                print("*"*80)
                print(text)
                print("*"*80)
                sql = self.extract_sql_from_response(str(text))
                sql = self._clean_sql(sql)

                # ========== SQL检查 ==========
                # 【健壮性检查】如果SQL检查器不可用，直接返回生成的SQL
                if not self.sql_checker:
                    print(f"⚠ SQL检查器不可用，返回生成的SQL")
                    return sql

                try:
                    # 【核心调用】调用SQL检查器的check方法（需要返回包含feedback的字典）
                    check_result = self.sql_checker.check(sql, context_desc=question)
                except TypeError:
                    # 【兼容性处理】如果检查器不支持context_desc参数，使用基础模式
                    print("⚠ SQL检查器不支持context_desc参数，使用基础检查模式")
                    check_result = self.sql_checker.check(sql)
                except Exception as check_error:
                    # 【错误处理】检查执行失败时直接返回生成的SQL
                    print(f"⚠ SQL检查执行失败: {check_error}，返回生成的SQL")
                    return sql

                # 【健壮性检查】验证检查结果格式
                if not isinstance(check_result, dict):
                    print(f"⚠ 检查结果格式异常，跳过检查: {type(check_result)}")
                    return sql

                # 提取检查结果的关键信息
                is_valid = check_result.get('passed', True)
                errors = check_result.get('errors', [])
                warnings = check_result.get('warnings', [])

                # ========== 决策逻辑（核心变化） ==========
                if attempt == 1:
                    # 【第1次】无论SQL是否正确，都必定进行反馈
                    print(f"\n✓ 第1次生成完成，检查通过！")
                    print(self._format_check_result(check_result))
                    print(f"→ 将反馈信息发送给模型进行第2次优化...\n")
                    last_sql = sql
                    last_check_result = check_result
                    print(check_result)
                    print("="*60)
                    time.sleep(1)
                    continue  # 进入第2次循环

                elif attempt == 2:
                    # 【第2次】检查通过则结束，有错误则继续反馈
                    if is_valid:
                        print(f"\n✓ 第2次生成完成，检查通过！")
                        # 即使通过，也显示警告信息（如果有）
                        if warnings:
                            print("\n检测到警告:")
                            for warning in warnings:
                                print(f"  {str(warning)}")
                        return sql
                    else:
                        print(f"\n⚠ 第2次生成仍有问题:")
                        print(self._format_check_result(check_result))
                        print(f"→ 将错误信息发送给模型进行第3次最终修正...\n")
                        last_sql = sql
                        last_check_result = check_result
                        print(check_result)
                        print("="*60)
                        time.sleep(1)
                        continue  # 进入第3次循环

                else:  # attempt == 3
                    # 【第3次】无论对错，都结束流程
                    if is_valid:
                        print(f"\n✓ 第3次生成完成，检查通过！")
                        # 即使通过，也显示警告信息（如果有）
                        if warnings:
                            print("\n检测到警告:")
                            for warning in warnings:
                                print(f"  {str(warning)}")
                        return sql
                    else:
                        # 【失败处理】第3次仍有错误，在SQL中添加错误提示注释
                        print(f"\n⚠ 第3次生成仍有问题（已达最大尝试次数）:")
                        print(self._format_check_result(check_result))
                        print(check_result)
                        print("="*60)

                        # 构建包含错误和警告信息的注释
                        comment_lines = ['-- ⚠ 警告：已达最大尝试次数(3次)，以下SQL可能仍存在问题']
                        for error in errors:
                            comment_lines.append(f'-- 错误: {str(error)}')
                        for warning in warnings:
                            comment_lines.append(f'-- 警告: {str(warning)}')

                        formatted_comments = '\n'.join(comment_lines)
                        print(f"✗ 返回最后一次生成的SQL（含错误提示）\n")
                        print(f"{formatted_comments}\n")
                        return sql

            except Exception as e:
                # 【异常处理】API调用或其他异常
                print(f"✗ 生成SQL时出错 (第 {attempt} 次): {e}")
                if attempt < 3:
                    print(f"→ 等待2秒后重试...")
                    time.sleep(2)
                else:
                    # 第3次出错时返回最后一次的SQL或错误信息
                    if last_sql:
                        return f"-- ⚠ 生成过程出错: {str(e)}\n-- 返回第{attempt - 1}次生成的SQL\n\n{last_sql}"
                    return f"-- ✗ 生成失败: {str(e)}"

        # 【兜底返回】理论上不会到达这里（for循环会提前return）
        if last_sql:
            return f"-- ⚠ 未能完全修正（流程异常）\n\n{last_sql}"
        return "-- ✗ 生成失败：未生成任何SQL"

    def _clean_sql(self, sql):
        """清理SQL语句"""
        # 【保持不变】清理逻辑与代码1完全一致
        # 移除markdown代码块标记
        sql = sql.replace('```sql', '').replace('```', '')
        sql = sql.strip()

        # 移除is_delete相关条件（避免敏感字段问题）
        sql = re.sub(r"\s+AND\s+\w*\.?is_delete\s*=\s*['\"]?0['\"]?", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s+WHERE\s+\w*\.?is_delete\s*=\s*['\"]?0['\"]?\s+AND\s+", " WHERE ", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s+WHERE\s+\w*\.?is_delete\s*=\s*['\"]?0['\"]?", "", sql, flags=re.IGNORECASE)

        # 确保SQL以分号结尾
        if not sql.endswith(';'):
            sql += ';'

        return sql

    def batch_generate(self, questions, show_progress=True):
        """
        批量生成SQL

        Args:
            questions: 问题列表
            show_progress: 是否显示进度

        Returns:
            SQL列表
        """
        results = []
        total = len(questions)

        for i, question in enumerate(questions, 1):
            if show_progress:
                # 【修改】增强进度显示格式，添加分隔线和问题展示
                print(f"\n{'=' * 60}")
                print(f"处理进度: {i}/{total}")
                print(f"问题: {question}")
                print('=' * 60)

            sql = self.generate_sql(question)
            results.append(sql)
            time.sleep(0.5)  # 【保持不变】防止API限流

        return results
