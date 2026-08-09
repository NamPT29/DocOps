import json
from excel_handler import get_form_schema
import unicodedata
schema = get_form_schema('d:/scan_to_excel/tai_lieu_mau/Excel_FormMau_v5_04082026.xlsx')
with open('check_schema_out.txt', 'w', encoding='utf8') as f:
    for cat in schema:
        for fld in cat['fields']:
            if fld['col_index'] >= 57 and fld['col_index'] <= 61:
                f.write(f"Col {fld['col_index']}: {fld['label']} - Type: {fld['type']} - Options count: {len(fld['options'])}\n")
                if fld['options']:
                    f.write(f"  Sample option: {fld['options'][0]}\n")
