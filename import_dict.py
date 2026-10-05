import sqlite3
import pandas as pd
from sqlalchemy import create_engine

chunksize = 20000
offset = 0

src = sqlite3.connect("data/stardict.db")
dst = create_engine(
    "mysql+pymysql://galaxy:0323@127.0.0.1:3306/words?charset=utf8mb4")

while True:
    df = pd.read_sql(f"SELECT * FROM stardict LIMIT {chunksize} OFFSET {offset}",src)
    if df.empty:
        break
    df.to_sql("dict",dst,if_exists = "append",index = False,chunksize = 5000)
    offset += len(df)
    print(f"已写入{offset}条")

src.close()
print("写入完成")