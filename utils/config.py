"""
配置文件 - Text-to-SQL项目
"""

# DeepSeek API配置
# 自定义部署的DeepSeek V3（当前使用） SSP
# DEEPSEEK_API_KEY = "fca969a668494c828726c0395e797180"  # Token
# DEEPSEEK_BASE_URL = "https://www.ssfssp.com:8888/ssp/openApi/GkfFhhUy/kvshB4Rh/LNslKxsF/v1"
# DEEPSEEK_MODEL = "DeepSeek-V3"  # 注意：带连字符

# DS官方平台（备用）
DEEPSEEK_API_KEY = "sk-eb8dcd5229e74ce98c74d4e49c677754"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 数据路径配置
DATA_DIR = r"data\评测题目"
TRAIN_FILE = r"data\llm_train_parse.json"

# 数据库Schema文件
SCHEMA_FILE = r"data\schema_knowledge_base.json"
FORMULA_FILE = r"data\formula_knowledge_base.json"
COMMON_EXPR_FILE = r"data\common_expressions.json"

# 模型参数
TEMPERATURE = 0.1  # 较低的温度以获得更确定的输出
MAX_TOKENS = 1500  # 减少token使用，SQL通常不需要太长
TOP_P = 0.95

# 本地数据库
MYSQL_USER = "root"
MYSQL_PWD = "123456"
MYSQL_DATABASE = "heating_meta"