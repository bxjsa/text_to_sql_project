"""
Text-to-SQL核心引擎 - 基于DeepSeek API
集成SQL静态检查和强反馈自动修正功能
"""
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, TEMPERATURE, MAX_TOKENS, TOP_P, SCHEMA_FILE, FORMULA_FILE, COMMON_EXPR_FILE
from sql_checker import SQLRuleChecker  # 【新增】导入SQL检查器
import time
import re
from rag_to_prompt import RAGText
from enhanced_schema_loader import EnhancedSchemaLoader
import json

class TextToSQLEngine:  # 【修改】类名从 TextToSQLEngine 改为 TextToSQLEngine2
    """基于DeepSeek的Text-to-SQL引擎（强反馈版本）"""  # 【修改】文档字符串更新

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

    def _build_system_prompt(self, question: str) -> str:
        """构建系统提示词"""
        self.loader = EnhancedSchemaLoader(SCHEMA_FILE, FORMULA_FILE, COMMON_EXPR_FILE)
        self.schema_prompt = self.loader.get_schema_prompt(question, keyword_weight=0.7)
        self.rag_prompt = self.ragtext.generate_prompt_with_rag(question)
        return f"""你是一个专业的SQL查询生成专家，专门处理能源供热领域的数据查询任务。

你的任务是：根据用户的自然语言问题，生成准确的、MySQL支持的SQL查询语句。

{self.schema_prompt}

## 重要规则：

1. **表名和字段名准确性**：严格使用上述提供的表名和字段名，不要臆造，同时谨慎使用示例值，这通常包含不完整的信息
2. **业务逻辑**：
   - 热源厂指标需要计算src_id为1和2的总和（商河恒泰热源厂和玉泉生物质电厂）
   - 换热站指标需要注意机组数量（plan_num）
   - 累计量计算使用结束时间值减去开始时间值
   - 总燃气用量需考虑blr_id为1、2、3、4(4台锅炉)和pump_id为1、2(2台热泵)的燃气用量
3. **公式计算**：严格按照公式描述中的计算逻辑生成SQL
4. **输出格式**：只输出SQL语句，不要有任何解释或markdown标记
5. **SQL类型限制**：
   - 只能生成SELECT查询语句
   - 禁止使用UPDATE、DELETE、INSERT、DROP、CREATE、ALTER、TRUNCATE等修改数据的语句
   - 筛选条件中使用字段名时，避免使用包含敏感关键词的字段（如is_delete字段改用其他条件）

{self.rag_prompt}

"""

    def _build_user_prompt(self, question):
        """构建用户提示词（首次生成）"""
        with open(r"data\增强表达.json", "r", encoding="utf-8") as f:
            reason_samples = json.load(f)
        enhanced_question_dict = {sample['原始题目']: sample['题目'] for sample in reason_samples}
        enhanced_question = enhanced_question_dict.get(question, "")
        # 【保持不变】用户提示词内容与代码1完全一致
        return f"""请根据以下增强表达的问题生成SQL查询语句：

原始问题：{question}
增强表达的问题：{enhanced_question}

要求：
1. 只输出SQL语句，不要有任何解释
2. SQL语句末尾加分号
3. 确保语法正确，字段名和表名准确
4. 如果涉及计算，严格按照公式描述中的逻辑

SQL："""

    def _build_feedback_prompt(self, question, previous_sql, check_result, attempt):
        """
        构建强反馈提示词

        【新增方法】根据SQL检查结果生成包含详细反馈信息的提示词

        Args:
            question: 原始问题
            previous_sql: 上一次生成的SQL
            check_result: 检查结果（包含feedback字典）
            attempt: 当前是第几次尝试（2或3）
        """
        # 【核心逻辑】从检查结果中提取反馈信息
        feedback = check_result.get('feedback', {})
        errors = check_result.get('errors', [])
        warnings = check_result.get('warnings', [])

        # 构建提示词
        prompt_parts = []

        # 1. 基本信息 - 根据尝试次数使用不同开场白
        if attempt == 2:
            prompt_parts.append("你刚才生成的SQL已经过检查，现在需要你根据反馈信息进行优化。")
        else:
            prompt_parts.append("你第二次生成的SQL仍存在问题，这是最后一次修正机会。")

        prompt_parts.append(f"\n原始问题：\n{question}")
        prompt_parts.append(f"\n你上次生成的SQL：\n{previous_sql}")

        # 2. 错误和警告信息
        if errors or warnings:
            prompt_parts.append("\n## 检测到的问题：")
            if errors:
                prompt_parts.append("\n错误：")
                for error in errors:
                    prompt_parts.append(f"  ✗ {str(error)}")
            if warnings:
                prompt_parts.append("\n警告：")
                for warning in warnings:
                    prompt_parts.append(f"  ⚠ {str(warning)}")
        else:
            prompt_parts.append("\n## 检查结果：未检测到明显错误")

        # 3. 【核心增强】表名映射反馈 - 显示使用的表及其中文含义
        table_mappings = feedback.get('table_mappings', {})
        if table_mappings:
            prompt_parts.append("\n## 你使用的表信息：")
            for eng_table, chn_desc in table_mappings.items():
                prompt_parts.append(f"  📊 {eng_table} → {chn_desc}")

        # 4. 【核心增强】字段映射反馈 - 显示使用的字段及其中文含义
        field_mappings = feedback.get('field_mappings', {})
        if field_mappings:
            prompt_parts.append("\n## 你使用的字段信息：")
            for table, fields in field_mappings.items():
                prompt_parts.append(f"\n  表 [{table}] 的字段：")
                for eng_field, chn_desc in fields.items():
                    prompt_parts.append(f"    📋 {eng_field} → {chn_desc}")

        # 5. 【核心增强】单位信息反馈 - 显示字段的计量单位
        units = feedback.get('units', {})
        if units:
            prompt_parts.append("\n## 字段单位信息：")
            for field, unit in units.items():
                prompt_parts.append(f"  📏 {field} 的单位: {unit}")

        # 6. 修正指导 - 根据是否有错误给出不同的优化建议
        prompt_parts.append("\n## 优化要求：")
        if errors:
            prompt_parts.append("1. 必须修复上述所有错误")
            prompt_parts.append("2. 根据字段的中文含义，确认是否选对了字段")
        else:
            prompt_parts.append("1. 根据表/字段的中文含义，确认语义是否准确匹配问题")
            prompt_parts.append("2. 检查是否有更合适的字段可以使用，替换时需谨慎")

        prompt_parts.append("3. 如果有单位信息，确认计算逻辑是否需要单位转换")
        # prompt_parts.append("4. 对生成SQL语句的逻辑进行仔细检查，特别注意问题中出现各月、每月时需要各月独立计算，不跨月计算")
        # prompt_parts.append("5. 若出现明显的逻辑错误，则立即进行修正优化")
        prompt_parts.append("4. 只输出优化后的完整SQL，不要解释")
        prompt_parts.append("5. SQL末尾加分号")

        prompt_parts.append("\n优化后的SQL：")

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

        system_prompt = self._build_system_prompt(question)
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

                # print("%"*80)
                # print(system_prompt)
                # print("%"*80)
                # print("&"*80)
                # print(user_prompt)
                # print("&"*80)


                # 提取并清理生成的SQL
                sql = response.choices[0].message.content
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
