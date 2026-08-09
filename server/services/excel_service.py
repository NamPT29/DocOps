import pandas as pd
import os
import json
import shutil
import openpyxl

def load_dictionaries(excel_path):
    """
    Load dictionaries from the DM_* sheets to provide dropdown options.
    """
    xl = pd.ExcelFile(excel_path)
    sheets = [s for s in xl.sheet_names if s.startswith('DM_') or s.strip() == 'LoaiHanChe']
    
    dicts = {}
    for s in sheets:
        df = pd.read_excel(xl, sheet_name=s)
        df = df.astype(str)  # Prevent fillna error on float64 columns
        df.fillna('', inplace=True)
        # We assume column 0 is code, column 1 is value
        if len(df.columns) >= 2:
            options = []
            for _, row in df.iterrows():
                code = str(row.iloc[0]).strip()
                val = str(row.iloc[1]).strip()
                if code.endswith('.0'): code = code[:-2] # clean float parses
                if code and val:
                    options.append(f"{code} - {val}")
                elif val:
                    options.append(val)
            dicts[s] = options
            
    # Hardcode some known logical dropdowns based on HuongDan
    dicts['Giới tính'] = ["1 - Nam", "0 - Nữ"]
    dicts['HGD'] = ["1 - Hộ ông/bà", "0 - Ông/Bà"]
    dicts['Người đại diện'] = ["1 - Có đại diện", "0 - Không đại diện"]
    dicts['Là SD chung'] = ["1 - Sử dụng chung", "0 - Sử dụng riêng"]
    
    return dicts

def get_form_schema(excel_path):
    """
    Reads the first 4 rows of the 'Data' sheet to construct a hierarchical form schema.
    Also injects dropdown options based on dictionaries.
    """
    df_head = pd.read_excel(excel_path, sheet_name='Data', header=[0, 1, 2, 3], nrows=0)
    
    # Load dictionaries
    try:
        dicts = load_dictionaries(excel_path)
    except Exception:
        dicts = {}

    schema = []
    current_category = ""
    category_fields = []
    
    for col_idx, col_tuple in enumerate(df_head.columns):
        cat = str(col_tuple[0]).strip()
        field1 = str(col_tuple[1]).strip()
        field2 = str(col_tuple[2]).strip()
        field3 = str(col_tuple[3]).strip()
        
        # Skip 'Số TT' as user requested
        if 'số tt' in cat.lower() or 'số tt' in field1.lower():
            continue
        
        if 'Unnamed:' in cat: cat = ""
        if 'Unnamed:' in field1: field1 = ""
        if 'Unnamed:' in field2: field2 = ""
        if 'Unnamed:' in field3: field3 = ""
        
        if not cat and not field1 and not field2 and not field3:
            continue
            
        col_1 = col_idx + 1
        if (17 <= col_1 <= 22) or (34 <= col_1 <= 39) or (86 <= col_1 <= 89) or (90 <= col_1 <= 94) or (111 <= col_1 <= 168) or (179 <= col_1 <= 182):
            label_parts = [p for p in [field2, field3] if p]
        else:
            label_parts = [p for p in [field1, field2, field3] if p]
            
        label = " - ".join(label_parts) if label_parts else cat
        
        if not cat:
            cat = "Thông tin chung"
            
        if cat != current_category:
            if current_category:
                schema.append({
                    "category": current_category,
                    "fields": category_fields
                })
            current_category = cat
            category_fields = []
            
        # Determine field type and options
        field_type = "text"
        options = []
        extract_mode = "none"
        col_1 = col_idx + 1
        
        # Check against hardcoded dict keys (e.g. Giới tính)
        for key in ['Giới tính', 'HGD', 'Người đại diện', 'Là SD chung']:
            if key in label:
                field_type = "dropdown"
                options = dicts.get(key, [])
                if key == 'Là SD chung':
                    extract_mode = "left"
                break
                
        # Dictionary mapping for dynamic dropdowns
        mapping = {
            'Dân tộc': 'DM_DanToc',
            'Quốc tịch': 'DM_QuocTich',
            'Loại GT': 'DM_LoaiGiayToTuyThan',
            'Loại bản đồ': 'DM_LoaiBanDoDiaChinh',
            'Loại tài sản': 'DM_LoaiTaiSan',
            'Loại công trình': 'DM_LoaiTaiSan',
            'Cấp hạng': 'DM_LoaiCapHang',
            'ĐTSD': 'DM_DoiTuongSuDungQuanLy',
            'TSD': 'DM_DoiTuongSuDungQuanLy',
            'Loại đất': 'DM_LoaiDat',
            'Mục đích sử dụng': 'DM_LoaiDat',
            'MĐSD': 'DM_LoaiDat',
            'Nguồn gốc': 'DM_NguonGocSuDungDat',
            'Loại GCN': 'DM_LoaiGiayChungNhan',
            'Trạng thái': 'DM_LoaiTrangThaiDangKyCapGCN',
            'Loại thửa': 'DM_LoaiThuaDat',
            'Phân loại thửa đất': 'DM_LoaiThuaDat',
            'Nghĩa vụ tài chính': 'DM_LoaiNghiaVuTaiChinh',
            'NVTC': 'DM_LoaiNghiaVuTaiChinh',
            'Hạn chế': 'LoaiHanChe'
        }
        
        if field_type == "text":
            if col_1 in [56, 57, 58, 59, 64, 65, 66, 67, 72, 73, 74, 75, 80, 81, 82, 83, 61, 69, 77, 85]:
                field_type = "text"
            elif col_1 in [60, 68, 76, 84]:
                field_type = "dropdown"
                options = dicts.get('DM_NguonGocSuDungDat', [])
                extract_mode = "left"
            elif col_1 == 97:
                field_type = "dropdown"
                options = [
                    "1 - Sử dụng chung (đồng sử dụng, 1 thửa có từ 2 Họ và Tên người sử dụng KHÁC nhau)",
                    "0 - Sử dụng riêng"
                ]
                extract_mode = "left"
            elif col_1 == 104:
                field_type = "dropdown"
                options = [
                    "1 - Có uỷ quyền",
                    "0 - Không uỷ quyền"
                ]
                extract_mode = "left"
            elif col_1 == 105:
                field_type = "dropdown"
                options = [
                    "1 - Ký thay",
                    "0 - Không ký thay"
                ]
                extract_mode = "left"
            else:
                for keyword, dict_key in mapping.items():
                    if keyword.lower() in label.lower() and dict_key in dicts:
                        field_type = "dropdown"
                        options = dicts.get(dict_key, [])
                        break
        
        if field_type == "dropdown":
            if col_1 in [6, 7, 8, 10, 27, 54, 55, 62, 63, 70, 71, 78, 79, 172]:
                extract_mode = "left"
            elif col_1 in [13, 24, 30, 99]:
                extract_mode = "right"
            elif col_1 == 41:
                extract_mode = "right"
            elif "quốc tịch" in label.lower():
                extract_mode = "right"
            elif "phân loại thửa" in label.lower():
                extract_mode = "ABCD"
                
        field = {
            "col_index": col_idx,
            "label": label,
            "name": f"col_{col_idx}",
            "type": field_type,
            "options": options
        }
        if col_1 == 17:
            field["separator_above"] = "Địa chỉ sử dụng"
            field["group_end"] = 22
        elif col_1 == 34:
            field["separator_above"] = "Địa chỉ vợ (chồng)"
            field["group_end"] = 39
        elif col_1 == 86:
            field["separator_above"] = "Diện tích hành lang"
            field["group_end"] = 89
        elif col_1 == 90:
            field["separator_above"] = "Địa chỉ thửa đất"
            field["group_end"] = 94
        elif col_1 == 111:
            field["separator_above"] = "Hạn chế quyền"
            field["group_end"] = 117
        elif col_1 == 118:
            field["separator_above"] = "Nghĩa vụ tài chính"
            field["group_end"] = 123
        elif col_1 == 124:
            field["separator_above"] = "Miễn giảm nghĩa vụ tài chính"
            field["group_end"] = 128
        elif col_1 == 129:
            field["separator_above"] = "Nợ nghĩa vụ tài chính"
            field["group_end"] = 133
        elif col_1 == 134:
            field["separator_above"] = "Nhà ở riêng lẻ"
            field["group_end"] = 141
        elif col_1 == 142:
            field["separator_above"] = "Công trình, hạng mục công trình xây dựng"
            field["group_end"] = 154
        elif col_1 == 155:
            field["separator_above"] = "Công trình ngầm"
            field["group_end"] = 162
        elif col_1 == 163:
            field["separator_above"] = "Rừng trồng"
            field["group_end"] = 165
        elif col_1 == 166:
            field["separator_above"] = "Cây lâu năm"
            field["group_end"] = 168
        elif col_1 == 179:
            field["separator_above"] = "Thông tin lưu kho vật lý hồ sơ"
            field["group_end"] = 182
            
        if field_type == "dropdown":
            field["extract_mode"] = extract_mode
            
        category_fields.append(field)
        
    if current_category:
        schema.append({
            "category": current_category,
            "fields": category_fields
        })
        
    return schema

def get_ma_xa_mapping(excel_path):
    """
    Extracts 3-level and 2-level mapping for communes from 'MaXa_3cap_2cap' sheet.
    Returns: { "mapping_3_cap": dict, "mapping_2_cap": dict }
    """
    import re
    try:
        df = pd.read_excel(excel_path, sheet_name='MaXa_3cap_2cap', dtype=str)
        mapping_3_cap = {}
        mapping_2_cap = {}
        
        def normalize_str(s):
            if pd.isna(s): return ""
            s = str(s).lower()
            # Sử dụng chung một regex với JS để đảm bảo đồng nhất 100%
            s = re.sub(r'[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]', '', s)
            return s
            
        def clean_code(c):
            c = str(c).strip()
            if c.endswith('.0'): c = c[:-2]
            return c
            
        for _, row in df.iterrows():
            # 3 cap
            if 'Mã xã 3 cấp (cũ)' in row:
                t3_raw = str(row.get('Tên xã 3 cấp')).strip() if not pd.isna(row.get('Tên xã 3 cấp')) else ''
                h3_raw = str(row.get('Quận/huyện 3 cấp')).strip() if not pd.isna(row.get('Quận/huyện 3 cấp')) else ''
                p3_raw = str(row.get('Tỉnh 3 cấp (cũ)')).strip() if not pd.isna(row.get('Tỉnh 3 cấp (cũ)')) else ''
                
                t3 = normalize_str(t3_raw)
                h3 = normalize_str(h3_raw)
                p3 = normalize_str(p3_raw)
                
                if t3 and h3 and p3:
                    addr_3 = f"{t3}{h3}{p3}"
                    code_3 = row['Mã xã 3 cấp (cũ)']
                    if not pd.isna(code_3):
                        mapping_3_cap[addr_3] = {
                            "code": clean_code(code_3),
                            "formatted": f"{t3_raw}, {h3_raw}, {p3_raw}"
                        }
                
            # 2 cap
            if 'Mã xã 2 cấp (mới)' in row:
                t2_raw = str(row.get('Tên xã 2 cấp')).strip() if not pd.isna(row.get('Tên xã 2 cấp')) else ''
                p2_raw = str(row.get('Tỉnh/TP (2 cấp)')).strip() if not pd.isna(row.get('Tỉnh/TP (2 cấp)')) else ''
                
                t2 = normalize_str(t2_raw)
                p2 = normalize_str(p2_raw)
                
                if t2 and p2:
                    addr_2 = f"{t2}{p2}"
                    code_2 = row['Mã xã 2 cấp (mới)']
                    if not pd.isna(code_2):
                        mapping_2_cap[addr_2] = {
                            "code": clean_code(code_2),
                            "formatted": f"{t2_raw}, {p2_raw}"
                        }
                
        return {
            "mapping_3_cap": mapping_3_cap,
            "mapping_2_cap": mapping_2_cap
        }
    except Exception as e:
        print(f"Error loading MaXa mapping: {e}")
        return {"mapping_3_cap": {}, "mapping_2_cap": {}}

def get_don_vi_do_mapping(excel_path):
    """
    Extracts mapping from QNH_ThongTinDoDac sheet to automatically fill Don vi do dac based on address.
    Returns: { "normalized_phuong_huyen": {"don_vi": "Tên đơn vị đo", "ngay_hoan_thanh": "Ngày hoàn thành"} }
    """
    import re
    try:
        df = pd.read_excel(excel_path, sheet_name='QNH_ThongTinDoDac', dtype=str)
        # Handle dynamic columns in case of encoding issues
        col_phuong = next((c for c in df.columns if 'ph' in c.lower() and 'c' in c.lower()), df.columns[1] if len(df.columns) > 1 else 'Tên phường cũ')
        col_huyen = next((c for c in df.columns if 'huy' in c.lower()), df.columns[2] if len(df.columns) > 2 else 'Huyện')
        col_don_vi = next((c for c in df.columns if 'đơn vị' in c.lower() or 'v' in c.lower()), df.columns[3] if len(df.columns) > 3 else 'Tên đơn vị đo')
        col_ngay = next((c for c in df.columns if 'ng' in c.lower() and 'ho' in c.lower()), df.columns[4] if len(df.columns) > 4 else 'Ngày hoàn thành')

        mapping = {}
        for _, row in df.iterrows():
            phuong = str(row.get(col_phuong, '')).strip()
            huyen = str(row.get(col_huyen, '')).strip()
            don_vi = str(row.get(col_don_vi, '')).strip()
            ngay = str(row.get(col_ngay, '')).strip()
            
            if ngay and ngay != 'nan':
                if ngay.replace('.', '', 1).isdigit():
                    try:
                        ngay = pd.to_datetime(float(ngay), origin='1899-12-30', unit='D').strftime("%d/%m/%Y")
                    except:
                        pass
            else:
                ngay = ""

            if phuong and phuong != 'nan' and don_vi and don_vi != 'nan':
                # create a normalized key: lowercase and alphanumeric only
                s = (phuong + huyen).lower()
                key = re.sub(r'[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]', '', s)
                mapping[key] = {
                    "don_vi": don_vi,
                    "ngay_hoan_thanh": ngay
                }
        return mapping
    except Exception as e:
        print(f"Error reading QNH_ThongTinDoDac: {e}")
        return {}

def export_submissions_to_excel(template_file_path: str, submissions: list, download_path: str):
    """
    Exports a list of submissions into a provided Excel template.
    Returns the path to the exported file.
    """
    shutil.copy(template_file_path, download_path)
    wb = openpyxl.load_workbook(download_path)
    
    sht_name = next((s for s in wb.sheetnames if s.strip().lower() == 'data'), None)
    if not sht_name:
        raise Exception("Không tìm thấy sheet 'Data' trong file mẫu.")
    ws = wb[sht_name]
    
    if ws.max_row >= 5:
        ws.delete_rows(5, ws.max_row - 4)
    
    def process_value(idx, val):
        if val and " - " in str(val):
            parts = str(val).split(" - ", 1)
            if len(parts) == 2 and parts[0].strip().isdigit():
                val = parts[0].strip()
        
        if idx == 58 and val and str(val).strip():
            str_val = str(val).strip()
            if not str_val.lower().startswith("đến ngày"):
                val = f"đến ngày {str_val}"
                
        return val
        
    for sub in submissions:
        data_dict = json.loads(sub.data_json)
        new_row = [""] * (ws.max_column + 10)
        
        for key, value in data_dict.items():
            if key.startswith('col_'):
                idx = int(key.split('_')[1])
                new_row[idx] = process_value(idx, value)
                
        if len(new_row) <= 105:
            new_row.extend([""] * (106 - len(new_row)))
        new_row[105] = new_row[101]
            
        ws.append(new_row)
        
    wb.save(download_path)
    wb.close()
    return download_path
