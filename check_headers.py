import pandas as pd
excel_path = "d:/scan_to_excel/tai_lieu_mau/Excel_FormMau_v5_04082026.xlsx"
df_head = pd.read_excel(excel_path, sheet_name='Data', header=None, nrows=4)
df_head.fillna('', inplace=True)
with open('check_cols.txt', 'w', encoding='utf8') as f:
    for i in range(50, 65):
        if i < len(df_head.columns):
            f.write(f"Col {i}: {df_head.iloc[1,i]} - {df_head.iloc[2,i]} - {df_head.iloc[3,i]}\n")
