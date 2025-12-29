import mysql.connector
from typing import Tuple, Any, List, Dict
from modify_sql import modify_sql
from config import MYSQL_USER, MYSQL_PWD, MYSQL_DATABASE

def get_conn():
    conn = mysql.connector.connect(
        host="localhost",
        port=3306,
        user=MYSQL_USER,
        password=MYSQL_PWD,
        database=MYSQL_DATABASE,
    )
    return conn

def run_sql(sql: str, fetch: bool = False) -> Tuple[bool, Any]:
    """
    执行SQL语句
    
    Args:
        sql: SQL语句
        fetch: 是否获取查询结果
    
    Returns:
        Tuple[bool, Any]: (执行状态, 结果或错误信息)
        - 成功: (True, 数据列表或受影响行数)
        - 失败: (False, 错误信息)
        - 空结果集: (False, "Empty set")
    """
    conn = None
    cursor = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        
        if fetch:
            rows = cursor.fetchall()
            
            # 检查是否为空结果集
            if not rows:
                return False, "Empty set"
            
            # 将结果转换为字典列表
            cols = [desc[0] for desc in cursor.description]
            result = [dict(zip(cols, row)) for row in rows]
            
            return True, result
        else:
            # INSERT/UPDATE/DELETE 操作
            conn.commit()
            affected_rows = cursor.rowcount
            return True, f"成功执行，影响行数：{affected_rows}"
    
    except mysql.connector.Error as e:
        # MySQL 特定错误
        if conn:
            conn.rollback()
        error_msg = f"MySQL错误 [{e.errno}]: {e.msg}"
        return False, error_msg
    
    except Exception as e:
        # 其他异常
        if conn:
            conn.rollback()
        error_msg = f"执行出错：{str(e)}"
        return False, error_msg
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    
    # 测试1：正常查询（有结果）
    print("=" * 60)
    print("测试1：正常查询")
    print("=" * 60)
    query = "2024-2025供暖季商河热网的热单耗是多少？"
    select_sql = """
    WITH start_period AS (
    SELECT src_id, MIN(data_time) AS start_time
    FROM ods_sc01_ntjt_zhgr_heat_source_inst_data
    WHERE data_time >= '2024-11-15 00:00:00'
    AND src_id IN (1, 2)
    GROUP BY src_id
),
end_period AS (
    SELECT src_id, MAX(data_time) AS end_time
    FROM ods_sc01_ntjt_zhgr_heat_source_inst_data
    WHERE data_time <= '2025-03-15 00:00:00'
    AND src_id IN (1, 2)
    GROUP BY src_id
),
start_heat AS (
    SELECT d.src_id, d.src_sup_total_hheat AS start_heat
    FROM ods_sc01_ntjt_zhgr_heat_source_inst_data d
    JOIN start_period s ON d.src_id = s.src_id AND d.data_time = s.start_time
),
end_heat AS (
    SELECT d.src_id, d.src_sup_total_hheat AS end_heat
    FROM ods_sc01_ntjt_zhgr_heat_source_inst_data d
    JOIN end_period e ON d.src_id = e.src_id AND d.data_time = e.end_time
),
total_heat_area AS (
    SELECT SUM(heat_area) AS total_area
    FROM ods_sc01_ntjt_zhgr_heat_station_info
)
SELECT (SUM(e.end_heat - s.start_heat) / t.total_area) * 24 * 120 / (TIMESTAMPDIFF(HOUR, MIN(st.start_time), MAX(et.end_time)) + 1) AS heat_specific_consumption
FROM start_heat s
JOIN end_heat e ON s.src_id = e.src_id
JOIN start_period st ON s.src_id = st.src_id
JOIN end_period et ON s.src_id = et.src_id
CROSS JOIN total_heat_area t;
    """
    
    success, result = run_sql(select_sql, fetch=True)
    print(f"执行状态: {success}")
    if success:
        print(f"查询结果：")
        for row in result:
            print(row)
    else:
        print(f"错误原因: {result}")
        modified_sql = modify_sql(query, select_sql, result)
        print(modified_sql)

    
    
    
