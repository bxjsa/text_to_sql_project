"""
SQL静态检查器 - 反馈增强版
基于Schema的表名和字段验证 + 详细中文映射反馈

使用方式:
  from sql_checker import SQLRuleChecker

  checker = SQLRuleChecker()
  result = checker.check(sql, context_desc="查询供热面积数据")
"""
import re
import os
import sqlparse
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass
from collections import defaultdict
from sqlparse.sql import IdentifierList, Identifier, Token
from sqlparse.tokens import Keyword, DML, Whitespace, Newline


@dataclass
class FieldInfo:
    """字段信息结构"""
    table_name: str
    field_name: str
    data_type: str
    cn_desc: str = ""  # 中文描述


class SQLRuleChecker:
    """
    SQL规则检查器 - 反馈增强版

    核心功能:
    1. 表名验证
    2. 字段名验证
    3. 基础语法检查
    4. 危险操作检查
    5. 🆕 提供详细的中文映射反馈（表名、字段名、单位等）
    """

    def __init__(self, schema_file: str = None):
        """初始化检查器"""
        print("\n" + "=" * 80)
        print("🚀 初始化 SQL 规则检查器（反馈增强版）")
        print("=" * 80)

        # Schema文件路径（硬编码默认路径）
        if schema_file is None:
            self.schema_file = r"data\heating_system_mschema.txt"
        else:
            self.schema_file = schema_file

        print(f"📄 Schema文件: {self.schema_file}")

        # 初始化数据结构
        self.tables: Set[str] = set()
        self.table_fields: Dict[str, Set[str]] = defaultdict(set)
        self.fields_info: List[FieldInfo] = []

        # 表英文名->中文名 字典
        self.table_name_cn_map: Dict[str, str] = {}

        # 字段中文描述字典，形如: {'table': {'field': '中文描述'}}
        self.field_cn_map: Dict[str, Dict[str, str]] = defaultdict(dict)

        # 加载Schema
        self._load_schema()

        print(f"\n{'=' * 80}")
        print(f"✅ 初始化完成")
        print(f"{'=' * 80}")
        print(f"📊 已加载 {len(self.tables)} 张表")
        print(f"📊 已索引 {sum(len(fields) for fields in self.table_fields.values())} 个字段")
        print(f"📊 表名中文字典条目: {len(self.table_name_cn_map)}")
        print(f"📊 字段中文字典条目(表数): {len(self.field_cn_map)}")
        print(f"{'=' * 80}\n")

    # ========================================================================
    # Schema 加载
    # ========================================================================

    def _load_schema(self):
        """加载并解析Schema文件"""
        schema_text = self._read_file(self.schema_file)
        if not schema_text:
            raise FileNotFoundError(f"❌ 无法加载Schema文件: {self.schema_file}")

        print(f"\n{'=' * 80}")
        print("🔧 解析Schema结构")
        print(f"{'=' * 80}\n")

        # 分割表块
        table_blocks = re.split(r'(?=# Table:)', schema_text)
        table_blocks = [b.strip() for b in table_blocks if '# Table:' in b]

        for block in table_blocks:
            self._parse_table_block(block)

        print(f"\n✅ Schema解析完成\n")

    def _read_file(self, filepath: str) -> str:
        """读取文件内容"""
        try:
            if not os.path.exists(filepath):
                return ""

            # 尝试UTF-8
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return f.read()
            except UnicodeDecodeError:
                # 尝试GBK
                with open(filepath, 'r', encoding='gbk') as f:
                    return f.read()
        except Exception as e:
            print(f"  ✗ 读取文件失败: {e}")
            return ""

    def _parse_table_block(self, block: str):
        """解析单个表块"""
        lines = block.strip().split('\n')

        # 解析表头: # Table: heating_system.buildings, 建筑基本信息表,主键为building_id
        table_match = re.match(r'#\s*Table:\s*([^,]+)', lines[0])
        if not table_match:
            return

        table_name = table_match.group(1).strip()
        normalized_table = self._normalize_table_name(table_name)

        # 解析表的中文描述
        table_cn = ""
        header_parts = [p.strip() for p in lines[0].split(',') if p.strip()]
        if len(header_parts) >= 2:
            table_cn = header_parts[1]

        self.tables.add(normalized_table)

        # 保存到表中文字典
        if table_cn:
            self.table_name_cn_map[normalized_table] = table_cn
        else:
            self.table_name_cn_map[normalized_table] = normalized_table

        print(f"📊 表: {normalized_table} -> {self.table_name_cn_map[normalized_table]}")

        # 解析字段
        in_field_section = False
        for line in lines[1:]:
            line = line.strip()

            if line == '[':
                in_field_section = True
                continue
            elif line == ']':
                break

            if in_field_section and line.startswith('('):
                field_info = self._parse_field_line(line, normalized_table)
                if field_info:
                    self.table_fields[normalized_table].add(field_info.field_name)
                    self.fields_info.append(field_info)
                    print(f"   ├─ {field_info.field_name} ({field_info.data_type}) - {field_info.cn_desc}")

                    # 保存字段中文描述
                    if field_info.cn_desc:
                        self.field_cn_map[normalized_table][field_info.field_name] = field_info.cn_desc

        print()

    def _parse_field_line(self, line: str, table_name: str) -> Optional[FieldInfo]:
        """解析字段行"""
        # 提取括号内容
        content = self._extract_parentheses_content(line)
        if not content:
            return None

        # 分割字段
        parts = self._smart_split(content)
        if len(parts) < 2:
            return None

        # 解析字段名和类型: building_id:int
        field_match = re.match(r'([^:]+):(.+)', parts[0].strip())
        if not field_match:
            return None

        field_name = field_match.group(1).strip()
        data_type = field_match.group(2).strip()

        # 提取中文描述(第二个部分)
        cn_desc = parts[1].strip() if len(parts) > 1 else ""

        return FieldInfo(
            table_name=table_name,
            field_name=field_name,
            data_type=data_type,
            cn_desc=cn_desc
        )

    def _extract_parentheses_content(self, line: str) -> Optional[str]:
        """提取括号内容"""
        start = line.find('(')
        end = line.rfind(')')
        if start == -1 or end == -1:
            return None
        return line[start + 1:end]

    def _smart_split(self, text: str) -> List[str]:
        """智能分割（考虑嵌套括号）"""
        parts = []
        current = []
        depth = 0

        for char in text:
            if char in '([{':
                depth += 1
                current.append(char)
            elif char in ')]}':
                depth -= 1
                current.append(char)
            elif char == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(char)

        if current:
            parts.append(''.join(current))

        return [p.strip() for p in parts]

    def _normalize_table_name(self, table_name: str) -> str:
        """标准化表名（移除schema前缀）"""
        if '.' in table_name:
            return table_name.split('.')[-1]
        return table_name

    # ========================================================================
    # SQL 检查主函数
    # ========================================================================

    def check(self, sql: str, context_desc: str = None) -> Dict[str, Any]:
        """
        执行SQL检查

        Args:
            sql: SQL语句
            context_desc: 查询上下文（原始问题）

        Returns:
            dict: {'passed': bool, 'errors': [], 'warnings': [], 'feedback': {}}
        """
        result = {
            'passed': True,
            'errors': [],
            'warnings': [],
            'feedback': {
                'original_question': context_desc or "未提供",
                'sql': sql,
                'table_mappings': {},  # 表名映射
                'field_mappings': {},  # 字段名映射
                'units': {}  # 单位信息
            }
        }

        # 空值检查
        if not sql or not sql.strip():
            result['errors'].append("❌ SQL语句为空")
            result['passed'] = False
            return result

        print(f"\n{'=' * 80}")
        print(f"🔍 开始检查SQL")
        if context_desc:
            print(f"📝 原始问题: {context_desc}")
        print(f"{'=' * 80}\n")

        try:
            # 1. 基础语法检查
            syntax_errors = self._check_basic_syntax(sql)
            result['errors'].extend(syntax_errors)

            # 2. 解析SQL
            try:
                parsed = sqlparse.parse(sql)[0]
            except Exception as e:
                result['errors'].append(f"❌ SQL解析失败: {str(e)}")
                result['passed'] = False
                return result

            # 3. 提取SQL中的表名和字段名
            tables_in_sql = self._extract_tables(parsed)

            # 4. 表名检查并收集映射信息
            table_errors = self._check_table_existence(parsed, sql, result['feedback'])
            result['errors'].extend(table_errors)

            # 5. 字段检查并收集映射信息
            if not result['errors']:  # 只有表名正确才检查字段
                field_errors = self._check_column_existence(parsed, sql, tables_in_sql, result['feedback'])
                result['errors'].extend(field_errors)

            # 6. 危险操作检查
            danger_errors = self._check_dangerous_operations(sql)
            result['errors'].extend(danger_errors)

        except Exception as e:
            result['errors'].append(f"❌ 检查过程出错: {str(e)}")
            result['passed'] = False

        # 设置检查结果
        if result['errors']:
            result['passed'] = False

        # 打印结果
        self._print_result(result)

        return result

    # ========================================================================
    # 具体检查方法
    # ========================================================================

    def _check_basic_syntax(self, sql: str) -> List[str]:
        """基础语法检查"""
        errors = []

        # 括号匹配
        if sql.count('(') != sql.count(')'):
            errors.append("❌ 括号不匹配")

        # 单引号匹配
        single_quotes = [i for i, c in enumerate(sql) if c == "'" and (i == 0 or sql[i - 1] != '\\')]
        if len(single_quotes) % 2 != 0:
            errors.append("❌ 单引号不匹配")

        # 子查询别名检查（改进版）
        # 先移除 CTE 部分，避免误判
        sql_without_cte = self._remove_cte(sql)
        
        # 只检查非 CTE 部分的子查询
        subquery_pattern = r'\)\s*(?:WHERE|JOIN|FROM|,|\)|$)'
        matches = re.finditer(subquery_pattern, sql_without_cte, re.IGNORECASE)
        
        for match in matches:
            # 向前查找，确认这是一个子查询而非函数调用
            start_pos = match.start()
            preceding_text = sql_without_cte[max(0, start_pos - 200):start_pos + 1]
            
            # 排除函数调用（如 COUNT()、MAX() 等）
            if re.search(r'\b(?:COUNT|SUM|AVG|MAX|MIN|CAST|CONVERT|DATE|SUBSTRING|CONCAT)\s*\($', 
                        preceding_text, re.IGNORECASE):
                continue
                
            # 检查是否有 FROM/JOIN 关键字（确认是子查询）
            if not re.search(r'\bFROM\b', preceding_text, re.IGNORECASE):
                continue
            
            # 检查子查询后是否有别名
            following_text = sql_without_cte[match.end():match.end() + 50]
            if not re.match(r'^\s*(?:AS\s+)?\w+', following_text, re.IGNORECASE):
                # 检查是否是在 IN/EXISTS 子句中（这些不需要别名）
                context = sql_without_cte[max(0, start_pos - 30):start_pos]
                if not re.search(r'\b(?:IN|EXISTS)\s*$', context, re.IGNORECASE):
                    errors.append("❌ 子查询缺少别名")
                    break  # 只报一次错误

        return errors

    def _remove_cte(self, sql: str) -> str:
        """移除 SQL 中的 CTE 部分，返回主查询"""
        # 匹配 WITH ... AS (...) 结构
        cte_pattern = r'\bWITH\s+.*?\)\s*(?=SELECT|INSERT|UPDATE|DELETE)'
        
        # 使用栈来匹配括号，确保正确提取 CTE
        sql_upper = sql.upper()
        with_pos = sql_upper.find('WITH')
        
        if with_pos == -1:
            return sql  # 没有 CTE
        
        # 找到 CTE 结束位置（最后一个 CTE 的右括号后）
        bracket_count = 0
        in_cte = False
        cte_end = with_pos
        
        for i in range(with_pos + 4, len(sql)):
            if sql[i] == '(':
                bracket_count += 1
                in_cte = True
            elif sql[i] == ')':
                bracket_count -= 1
                if bracket_count == 0 and in_cte:
                    # 检查后面是否还有 CTE（逗号分隔）
                    remaining = sql[i+1:].lstrip()
                    if remaining.startswith(','):
                        continue  # 还有下一个 CTE
                    else:
                        cte_end = i + 1
                        break
        
        # 返回 CTE 之后的主查询
        return sql[cte_end:].lstrip()


    def _check_table_existence(self, parsed, sql: str, feedback: dict) -> List[str]:
        """检查表名是否存在并收集映射信息"""
        errors = []

        print("🔍 检查表名...")

        # 提取SQL中的表名
        tables_in_sql = self._extract_tables(parsed)

        for table in tables_in_sql:
            normalized_table = self._normalize_table_name(table)

            if normalized_table in self.tables:
                print(f"  ✓ 表名正确: {normalized_table}")

                # 收集表名映射
                cn_name = self.table_name_cn_map.get(normalized_table, normalized_table)
                feedback['table_mappings'][normalized_table] = cn_name

            else:
                # 模糊匹配
                similar_tables = self._find_similar_tables(normalized_table)

                error_msg = f"❌ 表 '{table}' 不存在"
                errors.append(error_msg)

                if similar_tables:
                    suggestion = f"   💡 您是否想使用: {', '.join(similar_tables[:3])}"
                    errors.append(suggestion)

        print()
        return errors

    def _check_column_existence(self, parsed, sql: str, tables_in_sql: List[str], feedback: dict) -> List[str]:
        """检查字段是否存在并收集映射信息"""
        errors = []

        print("🔍 检查字段...")

        for table in tables_in_sql:
            normalized_table = self._normalize_table_name(table)

            if normalized_table not in self.tables:
                continue  # 表不存在的错误已在上一步报告

            # 提取该表的字段
            fields_in_sql = self._extract_fields_for_table(parsed, sql, table)

            # 初始化该表的字段映射
            if normalized_table not in feedback['field_mappings']:
                feedback['field_mappings'][normalized_table] = {}

            for field in fields_in_sql:
                if field == '*':
                    continue

                if field in self.table_fields[normalized_table]:
                    print(f"  ✓ 字段存在: {normalized_table}.{field}")

                    # 收集字段映射
                    cn_desc = self.field_cn_map.get(normalized_table, {}).get(field, field)
                    feedback['field_mappings'][normalized_table][field] = cn_desc

                    # 提取单位信息（从中文描述中）
                    unit = self._extract_unit_from_description(cn_desc)
                    if unit:
                        feedback['units'][f"{normalized_table}.{field}"] = unit

                else:
                    # 字段不存在
                    similar_fields = self._find_similar_fields(normalized_table, field)

                    error_msg = f"❌ 字段 '{normalized_table}.{field}' 不存在"
                    errors.append(error_msg)

                    if similar_fields:
                        suggestion = f"   💡 该表的相似字段: {', '.join(similar_fields[:5])}"
                        errors.append(suggestion)
                    else:
                        available_fields = list(self.table_fields[normalized_table])[:5]
                        suggestion = f"   💡 该表的可用字段: {', '.join(available_fields)}"
                        errors.append(suggestion)

        print()
        return errors

    def _extract_unit_from_description(self, description: str) -> Optional[str]:
        """从字段描述中提取单位信息"""
        # 常见单位模式
        unit_patterns = [
            r'单位[:：]?\s*([^\s,，)）]+)',
            r'\(([^\)]*[米吨度℃平方千瓦兆帕立方][^\)]*)\)',
            r'（([^）]*[米吨度℃平方千瓦兆帕立方][^）]*)）'
        ]

        for pattern in unit_patterns:
            match = re.search(pattern, description)
            if match:
                return match.group(1).strip()

        return None

    def _check_dangerous_operations(self, sql: str) -> List[str]:
        """检查危险操作"""
        errors = []

        dangerous_keywords = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE', 'INSERT', 'UPDATE']

        for keyword in dangerous_keywords:
            if re.search(rf'\b{keyword}\b', sql, re.IGNORECASE):
                errors.append(f"❌ 禁止使用 {keyword} 操作")

        return errors

    # ========================================================================
    # 表名和字段提取方法
    # ========================================================================

    def _extract_tables(self, parsed) -> List[str]:
        """提取SQL中的表名(排除CTE临时表和子查询别名)"""
        tables = []
        cte_names = set()  # 存储CTE定义的临时表名
        
        # 第一步: 识别所有CTE临时表名
        cte_names = self._extract_cte_names(parsed)
        
        # 第二步: 从FROM/JOIN提取表名,但排除CTE临时表
        i = 0
        while i < len(parsed.tokens):
            token = parsed.tokens[i]

            if token.ttype is Keyword:
                token_value = token.value.upper().strip()

                # 只处理 FROM 和 JOIN 关键字
                if token_value in ['FROM', 'JOIN'] or 'JOIN' in token_value:
                    for j in range(i + 1, len(parsed.tokens)):
                        next_token = parsed.tokens[j]
                        if next_token.ttype not in (Whitespace, Newline):
                            self._extract_from_token_safe(next_token, tables, cte_names)
                            break
            i += 1

        return list(dict.fromkeys(tables))

    def _extract_cte_names(self, parsed) -> Set[str]:
        """提取CTE(WITH子句)中定义的临时表名"""
        cte_names = set()
        sql_text = str(parsed)
        
        # 匹配 WITH 子句中的临时表定义
        # 模式: WITH table_name AS (...) 或 WITH table_name AS (...), table_name2 AS (...)
        with_pattern = r'\bWITH\s+(\w+)\s+AS\s*\('
        recursive_pattern = r',\s*(\w+)\s+AS\s*\('
        
        # 查找第一个CTE表名
        match = re.search(with_pattern, sql_text, re.IGNORECASE)
        if match:
            cte_names.add(match.group(1).lower())
            
            # 查找后续的CTE表名(逗号分隔)
            start_pos = match.end()
            for recursive_match in re.finditer(recursive_pattern, sql_text[start_pos:], re.IGNORECASE):
                cte_names.add(recursive_match.group(1).lower())
        
        return cte_names

    def _extract_from_token_safe(self, token, tables, cte_names: Set[str] = None):
        """安全提取表名(排除CTE临时表和子查询别名)"""
        if cte_names is None:
            cte_names = set()
        
        if isinstance(token, IdentifierList):
            for identifier in token.get_identifiers():
                name = self._get_real_name(identifier)
                if name and not self._is_keyword(name):
                    # 排除CTE临时表和子查询别名
                    if not self._is_subquery_or_cte(identifier, cte_names):
                        tables.append(name)
        elif isinstance(token, Identifier):
            name = self._get_real_name(token)
            if name and not self._is_keyword(name):
                # 排除CTE临时表和子查询别名
                if not self._is_subquery_or_cte(token, cte_names):
                    tables.append(name)

    def _is_subquery_or_cte(self, identifier, cte_names: Set[str]) -> bool:
        """判断标识符是否为子查询别名或CTE临时表"""
        try:
            identifier_str = str(identifier).strip()
            
            # 1. 检查是否为CTE临时表
            real_name = self._get_real_name(identifier)
            if real_name and real_name.lower() in cte_names:
                return True
            
            # 2. 检查是否为子查询(包含SELECT关键字)
            if re.search(r'\bSELECT\b', identifier_str, re.IGNORECASE):
                return True
            
            # 3. 检查是否有AS别名且前面有括号(子查询模式)
            # 模式: (...) AS alias_name
            if re.search(r'\)\s+(?:AS\s+)?\w+', identifier_str, re.IGNORECASE):
                return True
                
            return False
            
        except Exception:
            return False


    def _extract_fields_for_table(self, parsed, sql: str, table: str) -> List[str]:
        """提取特定表的字段"""
        fields = []

        try:
            # 从SELECT提取
            select_seen = False
            for token in parsed.tokens:
                if token.ttype is DML and token.value.upper() == 'SELECT':
                    select_seen = True
                    continue

                if select_seen and token.ttype is Keyword and token.value.upper() not in ['DISTINCT']:
                    break

                if select_seen:
                    if isinstance(token, IdentifierList):
                        for identifier in token.get_identifiers():
                            field = self._extract_field_from_identifier(identifier, table)
                            if field:
                                fields.append(field)
                    elif isinstance(token, Identifier):
                        field = self._extract_field_from_identifier(token, table)
                        if field:
                            fields.append(field)

            # 从WHERE/JOIN/ON条件提取
            condition_pattern = rf'\b{re.escape(table)}\.(\w+)'
            condition_fields = re.findall(condition_pattern, sql, re.IGNORECASE)
            fields.extend(condition_fields)

        except Exception as e:
            print(f"  ⚠️ 提取字段时出错: {e}")

        return list(set(fields))

    def _extract_field_from_identifier(self, identifier, target_table: str) -> Optional[str]:
        """从标识符提取字段名"""
        try:
            identifier_str = str(identifier).strip()

            # 移除函数
            func_pattern = r'\b(?:COUNT|SUM|AVG|MAX|MIN|ROUND|CAST|COALESCE|IFNULL|CONCAT|DATE)\s*\('
            identifier_str = re.sub(func_pattern, '', identifier_str, flags=re.IGNORECASE)
            identifier_str = identifier_str.replace(')', '').replace('(', '').strip()

            # 处理别名
            alias_match = re.match(r'^(.+?)\s+(?:AS\s+)?(\w+)$', identifier_str, re.IGNORECASE)
            if alias_match:
                identifier_str = alias_match.group(1).strip()

            # 处理 table.field
            if '.' in identifier_str:
                parts = identifier_str.split('.')
                if len(parts) >= 2:
                    table_part = parts[0].strip().strip('`"\'')
                    field_part = parts[1].strip().strip('`"\'')
                    if (table_part.lower() == target_table.lower() or
                            table_part.lower() in target_table.lower() or
                            target_table.lower() in table_part.lower()):
                        if field_part and re.match(r'^[a-zA-Z_]\w*$', field_part):
                            return field_part

            # 无表名前缀
            elif identifier_str and not self._is_keyword(identifier_str):
                field_candidate = identifier_str.strip().strip('`"\'')
                if field_candidate and re.match(r'^[a-zA-Z_]\w*$', field_candidate):
                    return field_candidate

        except Exception:
            pass

        return None

    def _get_real_name(self, identifier) -> Optional[str]:
        """获取标识符真实名称"""
        try:
            if hasattr(identifier, 'get_real_name'):
                return identifier.get_real_name()
            else:
                name = str(identifier).strip()
                if ' ' in name:
                    name = name.split()[0]
                return name.strip('`"\'')
        except:
            return None

    def _is_keyword(self, word: str) -> bool:
        """判断是否为SQL关键字"""
        keywords = {
            'SELECT', 'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT',
            'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'AS',
            'AND', 'OR', 'NOT', 'IN', 'BETWEEN', 'LIKE', 'IS', 'NULL'
        }
        return word.upper() in keywords

    def _find_similar_tables(self, table_name: str) -> List[str]:
        """查找相似表名"""
        similar = []
        query_keywords = set(table_name.lower().split('_'))

        for schema_table in self.tables:
            schema_keywords = set(schema_table.lower().split('_'))
            common = query_keywords & schema_keywords

            if common:
                score = len(common) / max(len(query_keywords), len(schema_keywords))
                similar.append((schema_table, score))

        similar.sort(key=lambda x: x[1], reverse=True)
        return [table for table, _ in similar[:3]]

    def _find_similar_fields(self, table_name: str, field_name: str) -> List[str]:
        """查找相似字段名"""
        if table_name not in self.table_fields:
            return []

        similar = []
        query_keywords = set(field_name.lower().split('_'))

        for schema_field in self.table_fields[table_name]:
            schema_keywords = set(schema_field.lower().split('_'))
            common = query_keywords & schema_keywords

            if common:
                score = len(common) / max(len(query_keywords), len(schema_keywords))
                similar.append((schema_field, score))

        similar.sort(key=lambda x: x[1], reverse=True)
        return [field for field, _ in similar[:5]]

    def _print_result(self, result: Dict[str, Any]):
        """打印检查结果"""
        print(f"\n{'=' * 80}")
        print("📋 检查结果")
        print(f"{'=' * 80}\n")

        if result['passed']:
            print("✅ SQL检查通过！\n")
        else:
            print("❌ SQL检查未通过\n")

        if result['errors']:
            print(f"🔴 错误 ({len(result['errors'])} 个):")
            for error in result['errors']:
                print(f"  {error}")
            print()

        if result['warnings']:
            print(f"🟡 警告 ({len(result['warnings'])} 个):")
            for warning in result['warnings']:
                print(f"  {warning}")
            print()

        # 输出反馈信息
        feedback = result['feedback']
        print(f"{'=' * 80}")
        print("📢 反馈信息（供大模型重新生成SQL时参考）")
        print(f"{'=' * 80}\n")

        print(f"📝 原始问题: {feedback['original_question']}\n")

        print(f"💻 SQL代码:\n{feedback['sql']}\n")

        if feedback['table_mappings']:
            print("📊 表名映射（英文 → 中文）:")
            for en_name, cn_name in feedback['table_mappings'].items():
                print(f"   • {en_name} → {cn_name}")
            print()

        if feedback['field_mappings']:
            print("📋 字段名映射（英文 → 中文）:")
            for table, fields in feedback['field_mappings'].items():
                print(f"   表: {table}")
                for en_field, cn_field in fields.items():
                    print(f"      • {en_field} → {cn_field}")
            print()

        if feedback['units']:
            print("📏 单位信息:")
            for field_path, unit in feedback['units'].items():
                print(f"   • {field_path}: {unit}")
            print()

        print(f"{'=' * 80}")
        print("💡 提示：请将以上信息提供给大模型，以便其重新生成更准确的SQL")
        print(f"{'=' * 80}\n")


