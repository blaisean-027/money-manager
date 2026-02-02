import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd


class DB_Handler:
    def __init__(self):
        self.conn = st.connection("gsheets", type=GSheetsConnection)

    def get_all_data(self):
        #모든 데이터 가져오기
        return self.conn.read(ttl = 0)
    
    def add_row(self, newData):
        #새로운 데이터 추가
        data = self.get_all_data()

        row = pd.DataFrame([newData])
        update = pd.concat([data, row], ignore_index=True)

        self.conn.update(data=update)
        return True