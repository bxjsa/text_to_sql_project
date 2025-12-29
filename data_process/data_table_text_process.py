import json
import re
from typing import Dict, List, Any, Optional


class HeatingSystemSchemaParser:
    """解析供热系统数据表描述文件为JSON格式"""
    
    def __init__(self):
        self.tables = {}
        self.db_id = "heating_system"
    
    def parse_schema_file(self, file_path: str) -> Dict[str, Any]:
        """
        解析Schema文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            符合EnhancedSchemaLoader格式的字典
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 匹配多行的detail内容
        table_pattern = r'\{\s*"name":\s*"([^"]+)",\s*"describe":\s*"([^"]+)",\s*"detail":\s*"""(.*?)"""\s*\}'
        
        matches = re.finditer(table_pattern, content, re.DOTALL)
        
        table_count = 0
        for match in matches:
            table_name = match.group(1).strip()
            description = match.group(2).strip()
            detail = match.group(3).strip()
            
            print(f"\n正在解析表: {table_name}")
            print(f"  描述: {description}")
            print(f"  Detail长度: {len(detail)} 字符")
            
            table_info = self._parse_table_info(table_name, description, detail)
            if table_info:
                self.tables[table_name] = table_info
                print(f"  ✓ 成功解析 {len(table_info['fields'])} 个字段")
                table_count += 1
            else:
                print(f"  ✗ 解析失败")
        
        print(f"\n总计成功解析 {table_count} 个表")
        
        return {
            "db_id": self.db_id,
            "tables": self.tables
        }
    
    def _parse_table_info(self, table_name: str, description: str, detail: str) -> Dict[str, Any]:
        """
        解析单个表的信息
        
        Args:
            table_name: 表名
            description: 表描述
            detail: 字段详情文本
        
        Returns:
            表信息字典
        """
        # 提取主键信息
        primary_keys = []
        relationships = []
        
        if "主键为" in description:
            pk_match = re.search(r'主键为(\w+)', description)
            if pk_match:
                primary_keys.append(pk_match.group(1))
        
        # 提取关系信息
        if "=" in description:
            relation_match = re.search(r'(\w+\.\w+=\w+\.\w+)', description)
            if relation_match:
                relationships.append(relation_match.group(1))
        
        # 解析字段
        fields = self._parse_fields(detail)
        
        if not fields:
            print(f"    警告: 表 {table_name} 没有解析到任何字段")
            # 显示前3行用于调试
            lines = detail.strip().split('\n')[:5]
            for i, line in enumerate(lines, 1):
                print(f"    第{i}行: {repr(line[:100])}")
        
        # 构建业务规则
        business_rules = []
        if primary_keys:
            business_rules.append(f"主键字段: {', '.join(primary_keys)}")
        
        # 分析字段特征
        field_names = list(fields.keys())
        
        # 检查时间字段
        time_fields = [f for f in field_names if 'time' in f.lower() or 'date' in f.lower()]
        if time_fields:
            business_rules.append(f"时间相关字段: {', '.join(time_fields)}")
        
        # 检查温度字段
        temp_fields = [f for f in field_names if 'temp' in f.lower()]
        if temp_fields:
            business_rules.append("包含温度监测数据")
        
        # 检查压力字段
        press_fields = [f for f in field_names if 'press' in f.lower()]
        if press_fields:
            business_rules.append("包含压力监测数据")
        
        # 检查流量字段
        flow_fields = [f for f in field_names if 'flow' in f.lower()]
        if flow_fields:
            business_rules.append("包含流量监测数据")
        
        # 检查热量字段
        heat_fields = [f for f in field_names if 'heat' in f.lower() or 'hheat' in f.lower()]
        if heat_fields:
            business_rules.append("包含热量计算数据")
        
        return {
            "table_name": table_name,
            "description": description.split("。")[0],
            "fields": fields,
            "business_rules": business_rules,
            "relationships": relationships
        }
    
    def _parse_fields(self, detail: str) -> Dict[str, Dict[str, Any]]:
        """
        解析字段详情
        
        Args:
            detail: 字段详情文本
        
        Returns:
            字段字典
        """
        fields = {}
        
        # 按行分割
        lines = detail.strip().split('\n')
        
        # 跳过说明行
        data_lines = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or '列名' in line_stripped or '下面内容为' in line_stripped or line_stripped.startswith('--'):
                continue
            data_lines.append(line)  # 保留原始行（包含空格/tab）
        
        print(f"    找到 {len(data_lines)} 行待解析数据")
        
        # 解析每一行
        parsed_count = 0
        for i, line in enumerate(data_lines, 1):
            field_info = self._parse_field_line_smart(line)
            if field_info:
                field_name = field_info.pop('name')
                fields[field_name] = field_info
                parsed_count += 1
            else:
                if i <= 3:  # 只显示前3个失败的行
                    print(f"    行 {i} 解析失败: {line[:100]}")
        
        print(f"    成功解析 {parsed_count}/{len(data_lines)} 个字段")
        
        return fields
    
    def _parse_field_line_smart(self, line: str) -> Optional[Dict[str, Any]]:
        """
        智能解析字段行（处理制表符和多空格混合的情况）
        
        策略：
        1. 优先按制表符分割
        2. 如果没有制表符，按固定位置分割（基于常见类型长度）
        
        Args:
            line: 字段行文本
        
        Returns:
            字段信息字典
        """
        # 策略1: 尝试按制表符分割
        if '\t' in line:
            parts = line.split('\t')
            parts = [p.strip() for p in parts if p.strip()]
            return self._parse_parts(parts)
        
        # 策略2: 按空格分割，但要小心处理小数和日期
        line = line.strip()
        
        # 常见的SQL类型
        sql_types = [
            'int', 'integer', 'bigint', 'smallint', 'tinyint',
            'decimal', 'numeric', 'float', 'double', 'real',
            'char', 'varchar', 'character', 'character varying',
            'text', 'datetime', 'date', 'time', 'timestamp',
            'boolean', 'bool'
        ]
        
        # 先保护小数和日期时间（用占位符替换空格）
        # 匹配小数: 数字.数字
        line = re.sub(r'(\d+\.\d+)', lambda m: m.group(1).replace('.', '§DECIMAL§'), line)
        # 匹配日期时间: YYYY-MM-DD HH:MM:SS
        line = re.sub(r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})', r'\1§DATETIME§\2', line)
        
        # 按空格分割
        words = line.split()
        
        # 恢复小数和日期时间
        words = [w.replace('§DECIMAL§', '.').replace('§DATETIME§', ' ') for w in words]
        
        if len(words) < 2:
            return None
        
        # 第一个词是字段名
        field_name = words[0]
        
        # 第二个词开始查找类型
        field_type = None
        type_end_idx = 1
        
        for i in range(1, len(words)):
            # 检查是否为类型关键字（可能包含空格，如 "character varying"）
            for sql_type in sorted(sql_types, key=len, reverse=True):
                type_words = sql_type.split()
                if i + len(type_words) <= len(words):
                    potential_type = ' '.join(words[i:i+len(type_words)])
                    if potential_type.lower() == sql_type.lower():
                        field_type = potential_type
                        type_end_idx = i + len(type_words)
                        break
            if field_type:
                break
        
        if not field_type:
            # 如果没找到，假设第二个词就是类型
            field_type = words[1]
            type_end_idx = 2
        
        # 剩余部分
        rest_words = words[type_end_idx:]
        
        # 构建parts列表
        parts = [field_name, field_type]
        parts.extend(rest_words)
        
        return self._parse_parts(parts)
    
    def _is_numeric(self, s: str) -> bool:
        """判断字符串是否为数字（整数或小数）"""
        try:
            float(s)
            return True
        except ValueError:
            return False
    
    def _parse_parts(self, parts: List[str]) -> Optional[Dict[str, Any]]:
        """
        从分割好的部分解析字段信息
        
        智能识别模式：
        - 字段名 类型 描述 [示例值] [范围min 范围max]
        - 字段名 类型 描述 [范围min 范围max]
        
        规则：
        1. 前两个必是: 字段名、类型
        2. 从后往前找连续的数字:
           - 最后2个都是数字 → 范围
           - 最后3个都是数字 → 示例值 + 范围
        3. 剩余的是描述
        
        Args:
            parts: 分割后的部分列表
        
        Returns:
            字段信息字典
        """
        if len(parts) < 2:
            return None
        
        field_name = parts[0]
        field_type = parts[1]
        
        # 初始化字段信息
        field_info = {
            "name": field_name,
            "type": field_type,
            "description": "",
            "constraints": [],
            "examples": []
        }
        
        # 如果只有字段名和类型，直接返回
        if len(parts) == 2:
            return field_info
        
        # 剩余部分
        rest_parts = parts[2:]
        
        # 从后往前查找连续的数字
        numeric_parts = []
        desc_parts = []
        
        # 倒序遍历
        for i in range(len(rest_parts) - 1, -1, -1):
            if self._is_numeric(rest_parts[i]):
                numeric_parts.insert(0, rest_parts[i])
            else:
                # 遇到非数字，剩余的都是描述
                desc_parts = rest_parts[:i+1]
                break
        
        # 如果全是数字，说明没有描述
        if not desc_parts and numeric_parts:
            desc_parts = []
        
        # 解析描述
        if desc_parts:
            field_info["description"] = ' '.join(desc_parts)
        
        # 解析数字部分
        # 情况1: 3个数字 → 示例值 + 范围 (例: 54 40 120)
        if len(numeric_parts) == 3:
            field_info["examples"] = [numeric_parts[0]]
            field_info["constraints"] = [f"{numeric_parts[1]}, {numeric_parts[2]}"]
        
        # 情况2: 2个数字 → 范围 (例: 30 100)
        elif len(numeric_parts) == 2:
            field_info["constraints"] = [f"{numeric_parts[0]}, {numeric_parts[1]}"]
        
        # 情况3: 1个数字 → 示例值 (例: 86)
        elif len(numeric_parts) == 1:
            field_info["examples"] = [numeric_parts[0]]
        
        # 情况4: 4+个数字 → 前面的作为示例，最后两个作为范围
        # (这种情况比较少见，可以根据实际情况调整)
        elif len(numeric_parts) >= 4:
            field_info["examples"] = [' '.join(numeric_parts[:-2])]
            field_info["constraints"] = [f"{numeric_parts[-2]}, {numeric_parts[-1]}"]
        
        return field_info
    
    def save_to_json(self, output_file: str, indent: int = 2):
        """
        保存为JSON文件
        
        Args:
            output_file: 输出文件路径
            indent: JSON缩进空格数
        """
        schema_data = {
            "db_id": self.db_id,
            "tables": self.tables
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(schema_data, f, ensure_ascii=False, indent=indent)
        
        print(f"\n✓ Schema已保存到: {output_file}")
        print(f"  - 数据库ID: {self.db_id}")
        print(f"  - 共解析 {len(self.tables)} 个表")
        total_fields = sum(len(t["fields"]) for t in self.tables.values())
        print(f"  - 共解析 {total_fields} 个字段")


def convert_heating_schema(input_file: str, output_file: str):
    """
    转换供热系统Schema文件
    
    Args:
        input_file: 输入的文本文件路径
        output_file: 输出的JSON文件路径
    """
    print(f"正在读取Schema文件: {input_file}")
    print("=" * 80)
    
    parser = HeatingSystemSchemaParser()
    schema_data = parser.parse_schema_file(input_file)
    
    # 保存为JSON
    parser.save_to_json(output_file)
    
    print("\n" + "=" * 80)
    print("转换完成!")
    print("=" * 80)
    
    # 打印表列表
    print("\n已解析的表:")
    for i, table_name in enumerate(schema_data["tables"].keys(), 1):
        table = schema_data["tables"][table_name]
        print(f"  {i}. {table_name}")
        print(f"     描述: {table['description']}")
        print(f"     字段数: {len(table['fields'])}")
        if table['business_rules']:
            print(f"     业务规则: {'; '.join(table['business_rules'][:2])}")
        print()


def validate_and_preview_schema(schema_file: str):
    """
    验证并预览Schema JSON
    
    Args:
        schema_file: Schema JSON文件路径
    """
    print("\n" + "=" * 80)
    print("Schema验证与预览")
    print("=" * 80)
    
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema_data = json.load(f)
    
    # 统计信息
    print(f"\n数据库ID: {schema_data['db_id']}")
    print(f"表数量: {len(schema_data['tables'])}")
    
    # 检查每个表的字段数
    print("\n各表字段统计:")
    for table_name, table_info in schema_data['tables'].items():
        field_count = len(table_info['fields'])
        status = "✓" if field_count > 0 else "✗"
        print(f"  {status} {table_name}: {field_count} 个字段")
    
    # 显示第一个有字段的表的详细结构
    for table_name, table_info in schema_data['tables'].items():
        if len(table_info['fields']) > 0:
            print(f"\n示例表结构 ({table_name}):")
            print(f"字段数: {len(table_info['fields'])}")
            print("-" * 80)
            
            # 显示前5个字段的详细信息
            for i, (field_name, field_info) in enumerate(list(table_info['fields'].items())[:5], 1):
                print(f"\n字段 {i}: {field_name}")
                print(json.dumps(field_info, ensure_ascii=False, indent=2))
            
            if len(table_info['fields']) > 5:
                print(f"\n... 还有 {len(table_info['fields']) - 5} 个字段")
            break


# ==================== 主程序 ====================

if __name__ == "__main__":
    input_file = r"baseline\能源热力问数模型算法挑战赛\数据表描述.txt"
    output_file = "schema_knowledge_base.json"
    
    # 转换Schema
    convert_heating_schema(input_file, output_file)
    
    # 验证和预览
    validate_and_preview_schema(output_file)
    
    print("\n✅ 所有操作完成!")
    print(f"输出文件: {output_file}")
