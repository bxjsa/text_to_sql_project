import argparse, os, sys, re, tqdm
import pandas as pd
import logging
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入新的模型调用方式
from text_to_sql_engine import TextToSQLEngine
from config import DEEPSEEK_MODEL

# 设置基本配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def convert_table(s, sql):
    """转换表别名"""
    l = re.findall(' ([^ ]*) +AS +([^ ]*)', sql)
    for li in l:
        s = s.replace(f" {li[1]}.", f" {li[0]}.")
    return s


def parse_ans(sql, ans):
    """解析模型输出"""
    ans = ans.replace('```\n', '').replace('```', '')
    ans = convert_table(ans, sql)

    # 使用更灵活的正则表达式匹配各个部分
    reason_match = re.search("#reason:.*", ans)
    column_match = re.search("#columns:.*", ans)
    values_match = re.search("#values:.*", ans)
    select_match = re.search("#SELECT:.*", ans)
    sqllike_match = re.search("#SQL-[Ll]ike:(.*)", ans)

    reason = reason_match.group() if reason_match else "#reason: 未提供"
    column = column_match.group() if column_match else "#columns: 未提供"
    values = values_match.group() if values_match else "#values: 未提供"
    select = select_match.group() if select_match else "#SELECT: 未提供"
    sqllike = "#SQL-Like:" + (sqllike_match.groups()[0] if sqllike_match else "未提供")

    final_str = "\n".join([reason, column, values, select, sqllike, f"#SQL: {sql}"])
    return final_str


def prepare_train_queries(data_file, new_train_dir, start=0, end=None):
    """
    为文本到SQL任务准备训练查询

    Args:
        data_file (str): 输入数据文件路径
        new_train_dir (str): 输出文件路径
        start (int): 开始索引
        end (int): 结束索引
    """

    # 初始化TextToSQLEngine
    engine = TextToSQLEngine()

    # 加载JSON数据
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 转换为DataFrame
    df = pd.DataFrame(data)

    # 设置结束索引
    if end is None:
        end = len(df)
    else:
        end = min(end, len(df))

    # 只添加parse列
    if 'parse' not in df.columns:
        df['parse'] = None

    # 处理每一行数据
    for i in tqdm.tqdm(range(start, end), total=end - start):
        for attempt in range(3):  # 最多尝试3次
            try:
                # 提取题目和SQL
                question = df.iloc[i]['题目']
                sql = df.iloc[i]['生成的sql']

                # 使用新的模型调用方式
                # 构建系统提示和用户提示
                system_prompt = "你是一个专业的SQL分析专家，专门分析能源供热领域的SQL查询语句。你的任务是根据给定的问题和SQL语句，详细分析SQL处理问题的逻辑和思路和各个组成部分。"
                analysis_prompt = f"问题: {question}\nSQL: {sql}\n\n请分析这个SQL查询，并按照以下格式输出：\n#reason: [解释这个SQL查询的目的和处理问题的逻辑]\n#columns: [列出查询涉及的所有字段]\n#values: [列出SQL中使用的所有字面值，如字符串、数字等]\n#SELECT: [SELECT语句分析]\n#SQL-Like: [类SQL表达式]"

                # 调用模型
                response = engine.client.chat.completions.create(
                    model=DEEPSEEK_MODEL,  # 使用从config导入的模型配置
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": analysis_prompt}
                    ],
                    temperature=0.1,  # 使用较低的温度以获得更稳定的输出
                    max_tokens=1000
                )

                # 获取模型响应
                content = response.choices[0].message.content

                # 只存储parse解析结果
                df.loc[i, 'parse'] = content.strip() + "\n#SQL: " + sql

                break  # 成功则跳出重试循环

            except Exception as e:
                print(f"处理第 {i} 行时出错 (尝试 {attempt + 1}/3): {str(e)}")
                if attempt == 2:  # 最后一次尝试也失败
                    df.loc[i, 'parse'] = f"#reason: 处理失败\n#columns: 处理失败\n#values: 处理失败\n#SELECT: 处理失败\n#SQL-Like: 处理失败\n#SQL: {sql}"

    # 保存结果
    output_data = df[start:end].to_dict('records')
    with open(new_train_dir, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logging.info(f"成功处理 {end - start} 条数据，保存到: {new_train_dir}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='为文本到SQL任务生成训练数据')
    parser.add_argument('--input_file',
                        type=str,
                        help='输入数据文件路径',
                        default="增强后的问题集.json")
    parser.add_argument('--output_file',
                        type=str,
                        help='输出文件路径',
                        default="llm_train_parse.json")
    parser.add_argument('--start',
                        type=int,
                        help='开始处理的索引',
                        default=0)
    parser.add_argument('--end',
                        type=int,
                        help='结束处理的索引',
                        default=None)

    args = parser.parse_args()

    logging.info(f"开始生成训练数据，输入文件: {args.input_file}, 输出文件: {args.output_file}")
    logging.info(f"使用的模型: {DEEPSEEK_MODEL}")

    prepare_train_queries(args.input_file, args.output_file, args.start, args.end)