import json
import re

def parse_formula_file(filepath):
    """
    解析常用公式.txt文件,转换为结构化JSON格式
    
    Args:
        filepath: 公式文件路径
    
    Returns:
        dict: 结构化的知识库字典
    """
    
    knowledge_base = {
        "formulas": {}
    }
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 提取heat_formula_dict中的内容
        dict_pattern = r'heat_formula_dict\s*=\s*\{(.*)\}'
        dict_match = re.search(dict_pattern, content, re.DOTALL)
        
        if not dict_match:
            print("警告: 未找到heat_formula_dict")
            return knowledge_base
        
        dict_content = dict_match.group(1)
        
        # 分割各个公式项: "公式名": """内容"""
        formula_pattern = r'"([^"]+)":\s*"""(.*?)"""'
        formula_matches = re.findall(formula_pattern, dict_content, re.DOTALL)
        
        for formula_name, formula_content in formula_matches:
            parsed_formula = parse_formula_content(formula_name, formula_content)
            knowledge_base["formulas"][formula_name] = parsed_formula
        
        return knowledge_base
    
    except Exception as e:
        print(f"错误: 解析文件失败 - {e}")
        return knowledge_base


def parse_formula_content(formula_name, content):
    """
    解析单个公式的内容
    
    Args:
        formula_name: 公式名称
        content: 公式内容文本
    
    Returns:
        dict: 结构化的公式信息
    """
    
    formula_data = {
        "formula": "",
        "description": "",
        "parameters": {},
        "db_mapping": {},
        "keywords": [],
        "notes": []
    }
    
    # 使用正则表达式分割各个主要部分
    sections = split_into_sections(content)
    
    # 1. 解析公式部分 - 保持原始格式,包括多行
    if "formula" in sections:
        formula_data["formula"] = sections["formula"].strip()
    
    # 2. 解析公式描述
    if "description" in sections:
        formula_data["description"] = sections["description"].strip()
    
    # 3. 解析参数
    if "parameters" in sections:
        formula_data["parameters"] = parse_parameters(sections["parameters"])
    
    # 4. 解析数据库映射 - 保持长文本完整
    if "db_mapping" in sections:
        formula_data["db_mapping"] = parse_db_mapping(sections["db_mapping"])
    
    # 5. 生成关键词
    formula_data["keywords"] = extract_keywords(formula_name, formula_data["description"])
    
    return formula_data


def split_into_sections(content):
    """
    将公式内容分割为各个部分
    
    Args:
        content: 公式完整内容
    
    Returns:
        dict: 各部分内容的字典
    """
    sections = {}
    
    # 定义各部分的标识符
    section_markers = [
        ("formula", r"公式[：:]"),
        ("description", r"公式描述[：:]"),
        ("parameters", r"公式中参数含义[：:]"),
        ("db_mapping", r"数据库对应字段[：:]")
    ]
    
    # 找到所有标记的位置
    markers_found = []
    for section_name, pattern in section_markers:
        match = re.search(pattern, content)
        if match:
            markers_found.append({
                "name": section_name,
                "start": match.end(),
                "marker": match.group()
            })
    
    # 按位置排序
    markers_found.sort(key=lambda x: x["start"])
    
    # 提取各部分内容
    for i, marker in enumerate(markers_found):
        start = marker["start"]
        # 确定结束位置(下一个标记的开始,或内容结尾)
        if i < len(markers_found) - 1:
            # 找到下一个标记之前的位置
            next_marker_pos = content.find(markers_found[i+1]["marker"], start)
            end = next_marker_pos if next_marker_pos != -1 else len(content)
        else:
            end = len(content)
        
        section_content = content[start:end].strip()
        sections[marker["name"]] = section_content
    
    return sections


def parse_parameters(param_text):
    """
    解析参数部分
    
    Args:
        param_text: 参数文本内容
    
    Returns:
        dict: 参数字典
    """
    parameters = {}
    
    # 按行分割
    lines = param_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 匹配参数行: 参数名：说明
        param_match = re.match(r'([^：:]+)[：:]\s*(.+)', line)
        if param_match:
            param_name = param_match.group(1).strip()
            param_desc = param_match.group(2).strip()
            
            # 提取单位
            unit_match = re.search(r'[（(]单位[：:]\s*([^）)]+)[）)]', param_desc)
            unit = unit_match.group(1) if unit_match else ""
            
            # 提取时间信息
            time_match = re.search(r'[（(].*?时间为(.+?)[）)]', param_desc)
            time_info = time_match.group(1) if time_match else ""
            
            # 去除单位和时间信息后的含义
            meaning = param_desc
            meaning = re.sub(r'[（(]单位[：:][^）)]+[）)]', '', meaning)
            meaning = re.sub(r'[（(].*?时间为[^）)]+[）)]', '', meaning)
            meaning = meaning.strip()
            
            parameters[param_name] = {
                "meaning": meaning,
                "unit": unit,
                "time_info": time_info
            }
    
    return parameters


def parse_db_mapping(db_text):
    """
    解析数据库映射部分 - 保持长文本完整
    
    Args:
        db_text: 数据库映射文本
    
    Returns:
        dict: 数据库映射字典
    """
    db_mapping = {}
    
    # 按行分割,但保留长文本
    lines = db_text.split('\n')
    
    current_param = None
    current_content = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 检查是否是新的参数行(以参数名:开头)
        param_match = re.match(r'^([A-Za-z_()（）]+)[：:]\s*(.+)', line)
        
        if param_match:
            # 保存之前的参数
            if current_param and current_content:
                db_mapping[current_param] = parse_single_db_mapping(
                    current_param, 
                    ' '.join(current_content)
                )
            
            # 开始新参数
            current_param = param_match.group(1).strip()
            current_content = [param_match.group(2).strip()]
        else:
            # 继续累积当前参数的内容
            if current_param:
                current_content.append(line)
    
    # 保存最后一个参数
    if current_param and current_content:
        db_mapping[current_param] = parse_single_db_mapping(
            current_param, 
            ' '.join(current_content)
        )
    
    return db_mapping


def parse_single_db_mapping(param_name, mapping_desc):
    """
    解析单个参数的数据库映射信息
    
    Args:
        param_name: 参数名
        mapping_desc: 映射描述(可能是长文本)
    
    Returns:
        dict: 映射信息
    """
    mapping_info = {
        "raw_description": mapping_desc,  # 保留原始完整描述
        "table": "",
        "field": "",
        "condition": "",
        "note": ""
    }
    
    # 提取表名
    table_match = re.search(r'(ods_\w+)', mapping_desc)
    if table_match:
        mapping_info["table"] = table_match.group(1)
    
    # 提取字段名(可能有多种表述方式)
    field_patterns = [
        r'的\s*(\w+)',  # "表中xxx的字段名"
        r'中\s*(\w+)',  # "表中字段名"
        r'字段\s*(\w+)'  # "字段 字段名"
    ]
    for pattern in field_patterns:
        field_match = re.search(pattern, mapping_desc)
        if field_match:
            mapping_info["field"] = field_match.group(1)
            break
    
    # 提取条件
    if "src_id" in mapping_desc:
        if any(x in mapping_desc for x in ["src_id分别为1和2", "src_id为1和2"]):
            mapping_info["condition"] = "src_id IN (1, 2)"
        elif "src_id=1" in mapping_desc or "src_id为1" in mapping_desc:
            mapping_info["condition"] = "src_id = 1"
        elif "src_id=2" in mapping_desc or "src_id为2" in mapping_desc:
            mapping_info["condition"] = "src_id = 2"
    
    # 提取重要注意事项
    notes = []
    if "需要分别计算" in mapping_desc or "分别获取" in mapping_desc or "分别计算" in mapping_desc:
        notes.append("需要分别计算不同src_id的值")
    if "汇总" in mapping_desc or "求和" in mapping_desc or "之和" in mapping_desc:
        notes.append("需要对结果进行汇总/求和")
    if "不同src_id要分别获取起始时间和结束时间" in mapping_desc:
        notes.append("不同src_id的起始/结束时间需分别获取")
    if "所有stn_id" in mapping_desc:
        notes.append("需要包含所有stn_id")
    
    mapping_info["note"] = "; ".join(notes)
    
    return mapping_info


def extract_keywords(formula_name, description):
    """
    从公式名称和描述中提取关键词
    """
    keywords = []
    
    keyword_candidates = [
        "热单耗", "采暖季", "指定时段", "能耗", "热量", 
        "供热", "面积", "效率", "累计", "瞬时", "HDD",
        "度日", "平均", "温度", "热源", "换热站"
    ]
    
    text = formula_name + " " + description
    
    for keyword in keyword_candidates:
        if keyword in text:
            keywords.append(keyword)
    
    return keywords


def save_knowledge_base(knowledge_base, output_path):
    """
    保存知识库为JSON文件
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=2)
        print(f"✓ 成功保存知识库到: {output_path}")
    except Exception as e:
        print(f"✗ 错误: 保存文件失败 - {e}")


# 使用示例
if __name__ == "__main__":
    input_file = r"baseline\能源热力问数模型算法挑战赛\公式描述.txt"
    output_file = r"baseline\能源热力问数模型算法挑战赛\formula_knowledge_base_v3.json"
    
    print("=" * 50)
    print("开始解析公式文件...")
    print("=" * 50)
    
    knowledge_base = parse_formula_file(input_file)
    
    print(f"\n✓ 共解析到 {len(knowledge_base['formulas'])} 个公式\n")
    
    # 保存为JSON
    save_knowledge_base(knowledge_base, output_file)
    
    # 打印解析结果示例
    print("\n" + "=" * 50)
    print("解析结果示例")
    print("=" * 50)
    
    for i, (formula_name, formula_data) in enumerate(knowledge_base['formulas'].items()):
        if i >= 2:  # 只打印前2个示例
            break
        print(f"\n【公式 {i+1}】{formula_name}")
        print("-" * 50)
        print(json.dumps(formula_data, ensure_ascii=False, indent=2))
