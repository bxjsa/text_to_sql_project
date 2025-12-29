import sys
from pathlib import Path
current_dir = Path.cwd()  # Notebook 当前目录
target_dir = current_dir/'utils' 
sys.path.append(str(target_dir))
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, TEMPERATURE, MAX_TOKENS, TOP_P
import time
from openai import OpenAI

def modify_sql(question, sql, message):
        """
        生成SQL查询语句
        
        Args:
            question: 自然语言问题
            sql: 需要验证的sql语句
            message: 错误信息
            
        Returns:
            生成的SQL语句(如果没有问题,返回初始sql值)
        """
        system_prompt = f"""你是一个专业的SQL语句审查专家，精通能源供热领域的数据查询任务。

你的任务是：根据报错信息，修改SQL语句，使其输出正确

**输出格式**：只输出SQL语句，不要有任何解释或markdown标记
"""


        user_prompt = f"""以下是问题和对应的SQL语句：
问题：{question}

sql语句:{sql}

报错信息:{message}

要求：
1. 只输出SQL语句，不要有任何解释
2. SQL语句末尾加分号
3. 确保语法正确，字段名和表名准确
4. 如果涉及计算，严格按照公式描述中的逻辑
"""
        

        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL
        )
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=TOP_P
        )
        
        sql = response.choices[0].message.content.strip()
        
        return sql

                
