import json
from typing import List

def read_json(file_path: str):
    """读取JSON文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(file_path: str, data):
    """写入JSON文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_raw_text(file_path: str, text: str):
    """保存原始文本"""
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)

def examples_to_str(examples: List) -> List:
    """将示例值转换为字符串格式"""
    return [str(example) for example in examples]