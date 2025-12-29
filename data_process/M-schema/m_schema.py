from utils import examples_to_str, read_json, write_json
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
import re
import json


class MSchema:
    def __init__(self, db_id: str = 'Anonymous', schema: Optional[str] = None):
        self.db_id = db_id
        self.schema = schema
        self.tables = {}
        self.foreign_keys = []

    def add_table(self, name, fields={}, comment=None):
        self.tables[name] = {"fields": fields.copy(), 'examples': [], 'comment': comment}

    def add_field(self, table_name: str, field_name: str, field_type: str = "",
                  primary_key: bool = False, nullable: bool = True, default: Any = None,
                  autoincrement: bool = False, comment: str = "", examples: list = [], **kwargs):
        self.tables[table_name]["fields"][field_name] = {
            "type": field_type,
            "primary_key": primary_key,
            "nullable": nullable,
            "default": default if default is None else f'{default}',
            "autoincrement": autoincrement,
            "comment": comment,
            "examples": examples.copy(),
            **kwargs}

    def add_foreign_key(self, table_name, field_name, ref_schema, ref_table_name, ref_field_name):
        self.foreign_keys.append([table_name, field_name, ref_schema, ref_table_name, ref_field_name])

    def create_from_text_descriptions(self, table_descriptions: List[Dict]):
        """
        从文本描述创建 M-Schema
        table_descriptions: 包含表描述的字典列表
        """
        for table_desc in table_descriptions:
            table_name = table_desc["name"]
            table_comment = table_desc["describe"]

            # 添加表
            self.add_table(table_name, comment=table_comment)

            # 解析字段信息
            detail_text = table_desc["detail"]
            fields_info = self._parse_field_details(detail_text)

            # 添加字段
            for field_info in fields_info:
                field_name = field_info["name"]
                field_type = self._map_data_type(field_info["type"])
                field_comment = field_info.get("comment", "")
                examples = field_info.get("examples", [])

                # 判断是否为主键
                primary_key = self._is_primary_key(table_desc, field_name)

                self.add_field(
                    table_name, field_name, field_type=field_type,
                    primary_key=primary_key, comment=field_comment,
                    examples=examples
                )

            # 解析外键关系
            self._parse_foreign_keys(table_desc)

    def _parse_field_details(self, detail_text: str) -> List[Dict]:
        """改进的字段详细信息解析"""
        fields = []
        lines = detail_text.strip().split('\n')

        start_parsing = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否到达字段数据开始行
            if "列名" in line and "数据类型" in line:
                start_parsing = True
                continue

            if start_parsing:
                # 跳过空行和注释行
                if not line or line.startswith('#'):
                    continue

                # 解析字段行
                field_info = self._parse_field_line(line)
                if field_info:
                    fields.append(field_info)

        return fields

    def _parse_field_line(self, line: str) -> Dict:
        """解析单个字段行，改进对中文示例值和范围数字的处理"""
        # 处理复合数据类型
        if 'timestamp without time zone' in line:
            field_name = line.split()[0]
            field_type = 'timestamp without time zone'
            remaining = line.replace(field_name, '').replace(field_type, '').strip()
        elif 'character varying' in line:
            field_name = line.split()[0]
            field_type = 'character varying'
            remaining = line.replace(field_name, '').replace(field_type, '').strip()
        else:
            parts = line.split()
            if len(parts) < 3:
                return None
            field_name = parts[0]
            field_type = parts[1]
            remaining = ' '.join(parts[2:])

        # 改进描述和示例解析
        field_description, examples = self._parse_description_and_examples(remaining, field_type)

        # 判断是否为主键
        primary_key = self._is_primary_key_from_description(field_description)

        # 新增：判断是否为自增字段
        autoincrement = self._is_autoincrement_from_description(field_description)

        # 若为时间类型且示例是日期，补齐时分秒
        if field_type.lower() in ['timestamp', 'datetime', 'timestamp without time zone']:
            new_examples = []
            for e in examples:
                if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', e):
                    new_examples.append(e + " 00:00:00")
                else:
                    new_examples.append(e)
            examples = new_examples

        field_description = re.sub(r'\s+', ' ', field_description).strip()
        return {
            "name": field_name,
            "type": field_type,
            "comment": field_description,
            "examples": examples,
            "primary_key": primary_key,
            "autoincrement": autoincrement  # 新增自增标记
        }

    def _is_primary_key_from_description(self, description: str) -> bool:
        """从字段描述中判断是否为主键"""
        if not description:
            return False
        pk_indicators = ['主键', 'primary key', 'primary_key']
        return any(indicator in description.lower() for indicator in pk_indicators)

    def _is_autoincrement_from_description(self, description: str) -> bool:
        """从字段描述中判断是否为自增字段"""
        if not description:
            return False
        auto_indicators = ['自增', 'auto increment', 'auto_increment', 'autoincrement', 'serial']
        return any(indicator in description.lower() for indicator in auto_indicators)

    def _parse_description_and_examples(self, remaining: str, field_type: str) -> Tuple[str, List[str]]:
        """
        调整后：保留原有所有策略，只加强对枚举末尾数字/NULL识别：
        - 像 "天气现象(描述)0:晴 ... 晴"：前半为描述，末尾独立词为示例（若有）
        - 若行以 NULL 或 0/1 等数字结尾，强制将其作为 Examples 提取
        """
        if not remaining:
            return "", []

        raw = remaining.strip()
        raw_orig = raw

        # 优先提取带括号的描述片段（如 入网面积(建筑面积)）
        bracket_pattern = re.compile(r'([\u4e00-\u9fff0-9_\s\-]+?[\(\（][^\)\）]+[\)\）])')
        bracket_match = bracket_pattern.search(raw)
        bracket_desc = ""
        if bracket_match:
            bracket_desc = bracket_match.group(1).strip()
            raw = raw.replace(bracket_desc, ' ').strip()

        raw_norm = re.sub(r'[，、,；;]', ' ', raw).strip()

        # 关键词紧贴示例优先拆分（例如 "所属单位商河恒泰供热公司"）
        desc_keywords = [
            '所属单位', '负责人', '换热站名称', '入网面积', '数据时间', '加载数据的时间',
            '机组1ID', '机组2ID', '机组ID', '建设时间', '状态变更时间', '下发失败的原因', '失败原因', '原因','热源名称'
        ]
        for kw in desc_keywords:
            m = re.search(rf'^{re.escape(kw)}\s*(.+)$', raw_norm)
            if m:
                tail = m.group(1).strip()
                if tail:
                    tokens = re.split(r'[\s,，、;；]+', tail)
                    merged = []
                    i = 0
                    while i < len(tokens):
                        if i + 1 < len(tokens) and re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$', tokens[i]) and re.match(
                                r'^\d{1,2}:\d{1,2}(:\d{1,2}(\.\d+)?)?$', tokens[i + 1]):
                            merged.append(tokens[i] + ' ' + tokens[i + 1])
                            i += 2
                        else:
                            merged.append(tokens[i])
                            i += 1
                    return kw, merged

        # 检测是否为枚举映射（含多个 "数字:中文" 项）
        enum_matches = re.findall(r'\d+\s*[:：]\s*[\u4e00-\u9fff\w]+', raw_orig)
        if len(enum_matches) >= 2:
            # 若是枚举型，将枚举说明作为描述的一部分。
            # 但若末尾存在独立 token（中文/数字/NULL），把它作为示例
            tail_tokens = re.split(r'[\s,，、;；]+', raw_orig.strip())
            tail_tokens = [t for t in tail_tokens if t.strip()]
            example = ""
            if tail_tokens:
                last_tok = tail_tokens[-1]
                # 若末尾为中文短词，或为数字，或为 NULL，则作为示例
                if (re.match(r'^[\u4e00-\u9fff]{1,10}$', last_tok)
                        or re.match(r'^-?\d+\.?\d*$', last_tok)
                        or last_tok.upper() == 'NULL'):
                    example = last_tok
                    # 把描述截断到末尾示例之前
                    idx = raw_orig.rfind(last_tok)
                    if idx != -1:
                        desc_part = raw_orig[:idx].strip()
                    else:
                        desc_part = raw_orig
                else:
                    desc_part = raw_orig
            else:
                desc_part = raw_orig

            # 合并括号描述（若存在且未包含在 desc_part 中）
            desc = desc_part.strip(' ，、;；')
            if bracket_desc and bracket_desc not in desc:
                desc = f"{bracket_desc}{desc}".strip()
            # 清洗 example
            if example:
                example = example.strip(' ,，、;；"\'')
                return desc, [example]
            else:
                return desc, []

        # 常规处理：分词并合并可能的 date+time
        parts = re.split(r'[\s,，、;；]+', raw_norm)
        merged_parts = []
        i = 0
        while i < len(parts):
            p = parts[i]
            if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$', p) and i + 1 < len(parts) and re.match(
                    r'^\d{1,2}:\d{1,2}(:\d{1,2}(\.\d+)?)?$', parts[i + 1]):
                merged_parts.append(p + ' ' + parts[i + 1])
                i += 2
            else:
                merged_parts.append(p)
                i += 1
        parts = [p for p in merged_parts if p]

        # 检测范围/最大最小等数值
        range_values = []
        range_pattern = re.compile(r'(?:最小值|最大值|范围|正常范围|最小|最大)[^\d\-\.]*(-?\d+\.?\d*)')
        range_matches = range_pattern.findall(raw_orig)
        if range_matches:
            range_values.extend(range_matches)

        def token_obviously_example(tok: str) -> bool:
            if not tok or tok.strip() == '':
                return False
            t = tok.strip()
            if re.match(r'^-?\d+\.?\d*$', t):
                return True
            if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}(\s+\d{1,2}:\d{1,2}(:\d{1,2}(\.\d+)?)?)?$', t):
                return True
            if not re.search(r'[\u4e00-\u9fff]', t) and re.search(r'[A-Za-z]', t) and re.search(r'\d', t):
                return True
            if re.match(r'^\d{11}$', t):
                return True
            if t.upper() == 'NULL':
                return True
            return False

        # 从尾部收集连续的明显示例（数字/日期/NULL/英文ID）
        example_parts = []
        description_parts = parts.copy()
        i = len(parts) - 1
        tail_examples = []
        while i >= 0:
            tok = parts[i]
            if token_obviously_example(tok):
                tail_examples.insert(0, tok)
                i -= 1
            else:
                # 若尾部为短中文且上下文表明这是示例（如包含关键词），也可当示例
                if re.search(r'[\u4e00-\u9fff]', tok) and len(tok) <= 12:
                    if any(k in raw_orig for k in ['原因', '所属', '负责人', '名称', '换热站', '单位']):
                        tail_examples.insert(0, tok)
                        i -= 1
                        continue
                break
        if tail_examples:
            example_parts = tail_examples
            description_parts = parts[:i + 1]

        # 把范围值也并入示例
        if range_values:
            example_parts.extend(range_values)

        # 清洗示例（去重，保持顺序）
        cleaned_examples = []
        seen = set()
        for ex in example_parts:
            if not ex or ex.strip() == '':
                continue
            v = ex.strip(' ，、;；"\'')
            if v in seen:
                continue
            seen.add(v)
            cleaned_examples.append(v)

        # 最后保守策略：若未识别到示例，但原文以 NULL 或 数字 结尾，也把它当示例（补救规则）
        if not cleaned_examples:
            tail_match = re.search(r'(?:(?:\s|,|，))(?P<tail>(?:NULL|-?\d+\.?\d*))\s*$', raw_orig, flags=re.I)
            if tail_match:
                tail_val = tail_match.group('tail').strip()
                if tail_val:
                    cleaned_examples = [tail_val]

        # 组装最终描述：优先使用 bracket_desc（若存在），再加上 description_parts
        final_description = bracket_desc if bracket_desc else ""
        if description_parts:
            dp_join = ''.join(description_parts) if all(
                re.search(r'^[\u4e00-\u9fff0-9_\-]+$', p) for p in description_parts) else ' '.join(description_parts)
            if final_description and dp_join and dp_join not in final_description:
                final_description = final_description + ' ' + dp_join
            elif not final_description:
                final_description = dp_join

        return final_description.strip(' ，、;；'), cleaned_examples

    def _is_description_content(self, text: str) -> bool:
        """判断文本是否可能是描述内容"""
        if not text:
            return False

        # 包含中文括号、冒号等标点符号的内容很可能是描述
        if any(char in text for char in ['（', '）', '(', ')', '：', ':', '，', '。', '/', '、']):
            return True

        # 包含中文的文本很可能是描述
        if re.search(r'[\u4e00-\u9fff]', text):
            return True

        # 包含特定关键词的文本很可能是描述
        description_keywords = ['ID', '时间', '温度', '压力', '流量', '热量', '名称', '类型', '状态', '方式', '性质']
        if any(keyword in text for keyword in description_keywords):
            return True

        return False

    def _is_likely_example_value(self, text: str, field_type: str) -> bool:
        """判断文本是否可能是示例值"""
        if not text or text.strip() == '':
            return False

        # 空值或占位符
        if text in ['NULL', 'None', '']:
            return True

        # 数字格式（整数、小数）
        if re.match(r'^-?\d+\.?\d*$', text):
            return True

        # 日期时间格式
        date_patterns = [
            r'^\d{4}-\d{1,2}-\d{1,2}',  # 2024-11-01
            r'^\d{4}/\d{1,2}/\d{1,2}',  # 2024/11/01
            r'^\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{1,2}:\d{1,2}',  # 2024-11-01 00:00:04
            r'^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{1,2}:\d{1,2}',  # 2024/11/01 00:00:04
            r'^\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{1,2}:\d{1,2}\.\d+',  # 2024-10-14 21:57:17.029802
        ]

        for pattern in date_patterns:
            if re.match(pattern, text):
                return True

        # 编码格式（字母+数字，包含点和下划线）
        if re.match(r'^[A-Za-z][A-Za-z0-9_\.]*$', text) and len(text) > 1:
            return True

        # 电话号码格式
        if re.match(r'^\d{11}$', text):
            return True

        # 布尔值或状态码
        if text in ['0', '1', 'true', 'false', 'True', 'False']:
            return True

        # 特殊格式：如命令GUID、阀门ID等
        if re.match(r'^FK\d+$', text) or re.match(r'^[A-Za-z]\d+$', text):
            return True

        # 包含点和特殊字符的ID（如阀门ID）
        if '.' in text and any(c.isalpha() for c in text) and any(c.isdigit() for c in text):
            return True

        # JSON格式的示例值
        if text.startswith('{') and text.endswith('}'):
            return True

        # 对于CHAR/VARCHAR类型，如果是短字符串且不包含中文，可能是示例值
        if field_type.lower() in ['char', 'varchar', 'character', 'character varying', 'bpchar']:
            if len(text) <= 50 and not re.search(r'[\u4e00-\u9fff]', text) and not any(
                    char in text for char in ['（', '）', '(', ')', '：', ':']):
                return True

        return False

    def _map_data_type(self, original_type: str) -> str:
        """映射数据类型到标准格式"""
        type_mapping = {
            'int': 'INTEGER',
            'integer': 'INTEGER',
            'bigint': 'BIGINT',
            'decimal': 'DECIMAL',
            'numeric': 'NUMERIC',
            'varchar': 'VARCHAR',
            'character varying': 'VARCHAR',
            'character': 'CHAR',
            'bpchar': 'CHAR',
            'char': 'CHAR',
            'datetime': 'DATETIME',
            'timestamp': 'TIMESTAMP',
            'timestamp without time zone': 'TIMESTAMP',
            'text': 'TEXT',
            'bool': 'BOOLEAN',
            'boolean': 'BOOLEAN',
            'bigserial': 'BIGSERIAL',
            'decimalv3': 'DECIMAL',
            'decimalv3(10, 4)': 'DECIMAL',
            'decimalv3(12, 4)': 'DECIMAL',
            'decimalv3(10, 2)': 'DECIMAL',
            'int8': 'BIGINT',
            'int4': 'INTEGER',
            'bpchar(1)': 'CHAR',
            'varchar(10)': 'VARCHAR',
            'varchar(14)': 'VARCHAR',
            'varchar(30)': 'VARCHAR',
            'varchar(60)': 'VARCHAR',
            'varchar(500)': 'VARCHAR'
        }

        # 精确匹配（包括复合类型）
        original_lower = original_type.lower().strip()
        for key, value in type_mapping.items():
            if original_lower == key.lower():
                return value

        # 处理带括号的类型
        if '(' in original_lower:
            base_type = original_lower.split('(')[0]
            for key, value in type_mapping.items():
                if base_type == key.lower():
                    return value

        return 'VARCHAR'  # 默认类型

    def _is_primary_key(self, table_desc: Dict, field_name: str) -> bool:
        """判断字段是否为主键"""
        describe = table_desc.get("describe", "")
        # 简单的关键词匹配
        pk_indicators = [
            f"主键为{field_name}",
            f"主键是{field_name}",
            f"{field_name}为主键",
            f"主键{field_name}"
        ]
        for indicator in pk_indicators:
            if indicator in describe:
                return True
        return False

    def _parse_foreign_keys(self, table_desc: Dict):
        """解析外键关系"""
        describe = table_desc.get("describe", "")
        table_name = table_desc["name"]

        # 支持多种外键描述格式
        fk_patterns = [
            r'(\w+)\.(\w+)=(\w+)\.(\w+)',
            r'(\w+)\s*的\s*(\w+)\s*关联\s*(\w+)\s*的\s*(\w+)'
        ]

        # 表名映射：将简化的表名映射到完整表名
        table_mapping = {
            'heat_station_info': 'ods_sc01_ntjt_zhgr_heat_station_info',
            'heat_station_inst_data': 'ods_sc01_ntjt_zhgr_heat_station_inst_data',
            'heat_source_inst_data': 'ods_sc01_ntjt_zhgr_heat_source_inst_data',
            'heat_source_info': 'ods_sc01_ntjt_zhgr_heat_source_info'
        }

        for pattern in fk_patterns:
            matches = re.findall(pattern, describe)
            for match in matches:
                if len(match) == 4:
                    ref_table, ref_field, target_table, target_field = match

                    # 应用表名映射
                    ref_table = table_mapping.get(ref_table, ref_table)
                    target_table = table_mapping.get(target_table, target_table)

                    if ref_table == table_name:
                        self.add_foreign_key(
                            table_name, ref_field,
                            self.schema, target_table, target_field
                        )

    def get_field_type(self, field_type, simple_mode=True) -> str:
        if not simple_mode:
            return field_type
        else:
            return field_type.split("(")[0]

    def has_table(self, table_name: str) -> bool:
        if table_name in self.tables.keys():
            return True
        else:
            return False

    def has_column(self, table_name: str, field_name: str) -> bool:
        if self.has_table(table_name):
            if field_name in self.tables[table_name]["fields"].keys():
                return True
            else:
                return False
        else:
            return False

    def get_field_info(self, table_name: str, field_name: str) -> Dict:
        try:
            return self.tables[table_name]['fields'][field_name]
        except:
            return {}

    def single_table_mschema(self, table_name: str, selected_columns: List = None,
                             example_num=3, show_type_detail=False) -> str:
        table_info = self.tables.get(table_name, {})
        output = []
        table_comment = table_info.get('comment', '')
        if table_comment is not None and table_comment != 'None' and len(table_comment) > 0:
            if self.schema is not None and len(self.schema) > 0:
                output.append(f"# Table: {self.schema}.{table_name}, {table_comment}")
            else:
                output.append(f"# Table: {table_name}, {table_comment}")
        else:
            if self.schema is not None and len(self.schema) > 0:
                output.append(f"# Table: {self.schema}.{table_name}")
            else:
                output.append(f"# Table: {table_name}")

        field_lines = []
        for field_name, field_info in table_info['fields'].items():
            if selected_columns is not None and field_name.lower() not in selected_columns:
                continue

            raw_type = self.get_field_type(field_info['type'], not show_type_detail)
            field_line = f"({field_name}:{raw_type.upper()}"
            if field_info['comment'] != '':
                field_line += f", {field_info['comment'].strip()}"

            # 判断是否为主键
            is_primary_key = field_info.get('primary_key', False)
            if is_primary_key:
                field_line += f", Primary Key"

            # 新增：判断是否为自增字段
            is_autoincrement = field_info.get('autoincrement', False)
            if is_autoincrement:
                field_line += f", Auto Increment"

            # 新增：如果字段注释中包含"自增"或"主键"但未在primary_key/autoincrement标记中体现，也进行识别
            comment_lower = field_info.get('comment', '').lower()
            if not is_primary_key and ('主键' in comment_lower or 'primary key' in comment_lower):
                field_line += f", Primary Key"

            if not is_autoincrement and (
                    '自增' in comment_lower or 'auto increment' in comment_lower or 'auto_increment' in comment_lower):
                field_line += f", Auto Increment"

            if len(field_info.get('examples', [])) > 0 and example_num > 0:
                examples = field_info['examples']
                examples = [s for s in examples if s is not None]
                examples = examples_to_str(examples)
                if len(examples) > example_num:
                    examples = examples[:example_num]

                if raw_type in ['DATE', 'TIME', 'DATETIME', 'TIMESTAMP']:
                    # 对于日期时间类型，保留完整的时间戳
                    examples = [examples[0]]
                elif len(examples) > 0 and max([len(s) for s in examples]) > 20:
                    if max([len(s) for s in examples]) > 50:
                        examples = []
                    else:
                        examples = [examples[0]]
                else:
                    pass
                if len(examples) > 0:
                    example_str = ', '.join([str(example) for example in examples])
                    field_line += f", Examples: [{example_str}]"
                else:
                    pass
            else:
                field_line += ""
            field_line += ")"

            field_lines.append(field_line)
        output.append('[')
        output.append(',\n'.join(field_lines))
        output.append(']')

        return '\n'.join(output)

    def to_mschema(self, selected_tables: List = None, selected_columns: List = None,
                   example_num=3, show_type_detail=False) -> str:
        """
        convert to a MSchema string.
        selected_tables: 默认为None，表示选择所有的表
        selected_columns: 默认为None，表示所有列全选，格式['table_name.column_name']
        """
        output = []

        output.append(f"【DB_ID】 {self.db_id}")
        output.append(f"【Schema】")

        if selected_tables is not None:
            selected_tables = [s.lower() for s in selected_tables]
        if selected_columns is not None:
            selected_columns = [s.lower() for s in selected_columns]
            selected_tables = [s.split('.')[0].lower() for s in selected_columns]

        for table_name, table_info in self.tables.items():
            if selected_tables is None or table_name.lower() in selected_tables:
                cur_table_type = table_info.get('type', 'table')
                column_names = list(table_info['fields'].keys())
                if selected_columns is not None:
                    cur_selected_columns = [c.lower() for c in column_names if
                                            f"{table_name}.{c}".lower() in selected_columns]
                else:
                    cur_selected_columns = selected_columns
                output.append(
                    self.single_table_mschema(table_name, cur_selected_columns, example_num, show_type_detail))

        if self.foreign_keys:
            output.append("【Foreign keys】")
            for fk in self.foreign_keys:
                ref_schema = fk[2]
                table1, column1, _, table2, column2 = fk
                if selected_tables is None or \
                        (table1.lower() in selected_tables and table2.lower() in selected_tables):
                    if ref_schema == self.schema:
                        output.append(f"{fk[0]}.{fk[1]}={fk[3]}.{fk[4]}")

        return '\n'.join(output)

    def dump(self):
        schema_dict = {
            "db_id": self.db_id,
            "schema": self.schema,
            "tables": self.tables,
            "foreign_keys": self.foreign_keys
        }
        return schema_dict

    def save(self, file_path: str):
        schema_dict = self.dump()
        write_json(file_path, schema_dict)

    def load(self, file_path: str):
        data = read_json(file_path)
        self.db_id = data.get("db_id", "Anonymous")
        self.schema = data.get("schema", None)
        self.tables = data.get("tables", {})
        self.foreign_keys = data.get("foreign_keys", [])