from m_schema import MSchema
import json
import re
from typing import List,Dict


def parse_heating_table_descriptions(text_content: str) -> List[Dict]:
    """
    解析供热系统表描述文本 - 处理非标准JSON格式
    """
    tables = []

    # 匹配每个表的完整描述块（处理三引号格式）
    table_pattern = r'\{\s*"name":\s*"([^"]+)"\s*,\s*"describe":\s*"([^"]+)"\s*,\s*"detail":\s*"""([\s\S]*?)"""\s*\}'

    matches = re.findall(table_pattern, text_content)

    for match in matches:
        table_name, table_describe, table_detail = match
        tables.append({
            "name": table_name.strip(),
            "describe": table_describe.strip(),
            "detail": table_detail.strip()
        })

    return tables


def parse_single_table_manual(block: str) -> Dict:
    """
    手动解析单个表描述块 - 处理三引号格式
    """
    table_data = {}

    # 提取表名
    name_match = re.search(r'"name":\s*"([^"]+)"', block)
    if name_match:
        table_data["name"] = name_match.group(1)
    else:
        return None

    # 提取描述
    describe_match = re.search(r'"describe":\s*"([^"]+)"', block)
    if describe_match:
        table_data["describe"] = describe_match.group(1)
    else:
        return None

    # 提取详细信息（处理三引号）
    detail_match = re.search(r'"detail":\s*"""([\s\S]*?)"""', block)
    if detail_match:
        table_data["detail"] = detail_match.group(1).strip()
    else:
        # 如果没有三引号，尝试双引号
        detail_match = re.search(r'"detail":\s*"([\s\S]*?)"(?:\s*,|\s*\})', block)
        if detail_match:
            table_data["detail"] = detail_match.group(1).strip()
        else:
            return None

    return table_data


def load_table_descriptions(file_path: str):
    """从文件加载表描述"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

        # 首先尝试直接解析整个文件为JSON数组
        try:
            # 如果是标准JSON数组格式
            tables = json.loads(content)
            print("成功解析为标准JSON格式")
            return tables
        except json.JSONDecodeError:
            # 如果不是标准JSON，使用正则表达式解析
            print("检测到非标准JSON格式，使用正则表达式解析...")
            tables = parse_heating_table_descriptions(content)

            if not tables:
                # 如果正则解析失败，尝试逐表解析
                print("正则解析失败，尝试逐表解析...")
                tables = parse_tables_individually(content)

            return tables


def parse_tables_individually(content: str) -> List[Dict]:
    """
    逐个解析表描述 - 更宽松的解析方法
    """
    tables = []

    # 匹配每个表的开始和结束
    # 查找所有 { 开头，包含 name, describe, detail 的块
    table_starts = []
    for match in re.finditer(r'\{\s*"name":', content):
        table_starts.append(match.start())

    # 如果没有找到表，返回空列表
    if not table_starts:
        return tables

    # 解析每个表块
    for i in range(len(table_starts)):
        start_pos = table_starts[i]
        if i < len(table_starts) - 1:
            end_pos = table_starts[i + 1]
        else:
            end_pos = len(content)

        table_block = content[start_pos:end_pos].strip()

        # 清理块内容
        table_block = re.sub(r',\s*#.*?(?=\}|$)', '', table_block)  # 移除注释
        table_block = table_block.rstrip(',')  # 移除末尾的逗号

        # 尝试解析为JSON
        try:
            table_data = json.loads(table_block)
            tables.append(table_data)
        except json.JSONDecodeError:
            # 如果JSON解析失败，使用手动解析
            table_data = parse_single_table_manual(table_block)
            if table_data:
                tables.append(table_data)
            else:
                print(f"无法解析表块: {table_block[:100]}...")

    return tables


def mschema_from_descriptions(descriptions_file: str):
    """
    从表描述生成 M-Schema
    """
    # 加载表描述
    table_descriptions = load_table_descriptions(descriptions_file)

    if not table_descriptions:
        print("错误：无法解析任何表描述！")
        return None

    print(f"成功加载 {len(table_descriptions)} 个表描述")
    for i, table in enumerate(table_descriptions, 1):
        print(f"  {i}. {table['name']} - {table['describe']}")

    # 创建 M-Schema 实例
    mschema = MSchema(db_id='heating_system', schema='public')

    # 从描述创建 schema
    mschema.create_from_text_descriptions(table_descriptions)

    mschema_str = mschema.to_mschema()
    print("\n生成的 M-Schema:")
    print("=" * 50)
    print(mschema_str)
    return mschema_str


if __name__ == '__main__':
    # 使用你的数据表描述文件
    result = mschema_from_descriptions('数据表描述.txt')

    if result:
        # 保存到文件
        with open('heating_system_mschema.txt', 'w', encoding='utf-8') as f:
            f.write(result)
        print("\nM-Schema 已保存到 heating_system_mschema.txt")
    else:
        print("生成 M-Schema 失败！")