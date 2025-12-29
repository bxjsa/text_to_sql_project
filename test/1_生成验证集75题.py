"""
验证集生成脚本 - 为验证集的75个问题生成SQL
专门处理"验证-75道题目.xlsx"文件
"""
import pandas as pd
import os
import sys
from pathlib import Path
current_dir = Path.cwd()  # Notebook 当前目录
target_dir = current_dir/'utils' 
sys.path.append(str(target_dir))

from text_to_sql_engine import TextToSQLEngine
from config import DATA_DIR, TRAIN_FILE
import json
from logger_utils import enable_console_to_log
from modify_sql import modify_sql
from verification_sql import run_sql

def load_validation_file():
    """加载验证集文件"""
    # 查找验证-75道题目.xlsx文件
    files = os.listdir(DATA_DIR)
    validation_file = "验证集评测75题.xlsx"
    
    filepath = os.path.join(DATA_DIR, validation_file)
    df = pd.read_excel(filepath)
    
    print(f"加载验证集文件: {validation_file}")
    print(f"数据形状: {df.shape}")
    print(f"列名: {df.columns.tolist()}")
    
    return df, validation_file


def generate_validation_sqls(engine, df, localhost):
    """为验证集生成SQL"""
    # 获取问题列
    questions = df['问题'].tolist()
    
    print(f"\n开始为验证集生成SQL ({len(questions)} 个问题)...\n")
    print("="*80)
    
    generated_sqls = []

    
    for i, question in enumerate(questions, 1):
        print(f"\n[{i}/{len(questions)}] 问题: {question}")
        
        try:
            sql = engine.generate_sql(question)
            if localhost == 'y':
                print("正在使用本地数据库对SQL语句进行检查...")
                success, result = run_sql(sql, fetch=True)
                print(f"执行状态: {success}")
                if success:
                    print(f"查询结果：")
                    for row in result:
                        print(row)
                    generated_sqls.append(sql)
                    print(f"生成的SQL: {sql}")
                else:
                    print(f"错误原因: {result}")
                    modified_sql = modify_sql(question, sql, result)

                    generated_sqls.append(modified_sql)
                    print(f"生成的SQL: {modified_sql}")
            else:
                print("跳过本地数据库的SQL语句检查")
                generated_sqls.append(sql)
        except Exception as e:
            print(f"生成失败: {e}")
            generated_sqls.append(f"-- 生成失败: {str(e)}")
        
        # 显示进度
        if i % 10 == 0:
            print(f"\n{'='*80}")
            print(f"进度: {i}/{len(questions)} ({i/len(questions)*100:.1f}%)")
            print(f"{'='*80}")
    
    return generated_sqls


def save_validation_results(df, generated_sqls):
    """保存验证集结果"""
    result_df = df.copy()
    
    # 填充"模型生成的SQL"列
    result_df['模型生成的SQL'] = generated_sqls

    # 保存到项目目录
    output_filename = "验证集75题_生成的SQL结果.xlsx"
    output_path = os.path.join(r"backups", output_filename)
    result_df.to_excel(output_path, index=False)
    print(f"\n结果已保存到: {output_path}")

    
    # 保存一份到比赛目录，方便提交
    submission_filename = "提交_验证集75题SQL结果.xlsx"
    submission_path = os.path.join(r"results", submission_filename)
    result_df.to_excel(submission_path, index=False)
    print(f"提交文件已保存到: {submission_path}")
    
    
    return output_path, submission_path


def main():
    """主函数"""
    print("="*80)
    print("Text-to-SQL 验证集生成 (75题)")
    print("="*80)
    
    try:
        # 加载验证集文件
        df, original_filename = load_validation_file()
        
        # 显示前几个问题
        print("\n前5个问题预览:")
        for i, q in enumerate(df['问题'].head(5), 1):
            print(f"{i}. {q}")
        
        # 确认是否继续
        print("\n" + "="*80)
        choice = input("是否开始生成SQL? (y/n，默认y): ").strip().lower() or 'y'
        
        if choice != 'y':
            print("已取消")
            return
        
        # 初始化引擎
        print("\n初始化Text-to-SQL引擎...")
        # 读取 JSON 数据
        with open(TRAIN_FILE, "r", encoding="utf-8") as f:
            training_samples = json.load(f)
        engine = TextToSQLEngine(training_samples)
        print("引擎初始化成功！")
        
        localhost = input("是否进行本地数据库检查? (y/n，默认y): ").strip().lower() or 'y'
        # 生成SQL
        generated_sqls= generate_validation_sqls(engine, df, localhost)

        
        if generated_sqls is None:
            print("生成失败")
            return
        
        # 保存结果
        output_path, submission_path = save_validation_results(df, generated_sqls)
        
        print("\n" + "="*80)
        print("验证集SQL生成完成！")
        print("="*80)
        print("\n生成的文件:")
        print(f"1. 项目结果: {output_path}")
        print(f"2. 提交文件: {submission_path}")
        print("\n下一步:")
        print("1. 打开提交文件检查SQL语句")
        print("2. 将文件提交到比赛平台进行评测")
        print("3. 根据评测结果优化算法")
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # enable_console_to_log(prefix="验证集75题log")
    main()
