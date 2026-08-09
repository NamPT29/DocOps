import re

def normalize_str(s: str) -> str:
    s = s.lower()
    return re.sub(r'[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]', '', s)

def process_address(val: str, field_name: str, ma_xa_mapping: dict, don_vi_do_mapping: dict = None) -> dict:
    val = val.strip()
    if not val:
        return {}
        
    normalized_val = normalize_str(val)
    
    matched_key = None
    match_obj = None
    
    mapping_3 = ma_xa_mapping.get("mapping_3_cap", {})
    mapping_2 = ma_xa_mapping.get("mapping_2_cap", {})
    
    # Check 3 cap
    for key, obj in mapping_3.items():
        if normalized_val.endswith(key):
            if not matched_key or len(key) > len(matched_key):
                matched_key = key
                match_obj = obj
                
    # Check 2 cap
    for key, obj in mapping_2.items():
        if normalized_val.endswith(key):
            if not matched_key or len(key) > len(matched_key):
                matched_key = key
                match_obj = obj
                
    if not match_obj:
        return {}
        
    prefix_norm_len = len(normalized_val) - len(matched_key)
    count = 0
    split_idx = 0
    for i, char in enumerate(val):
        if count == prefix_norm_len:
            split_idx = i
            break
        char_norm = normalize_str(char)
        if char_norm:
            count += 1
            
    prefix_original = val[:split_idx].strip()
    prefix_original = re.sub(r'(^[\s,]+)|([\s,]+$)', '', prefix_original)
    
    formatted_str = f"{prefix_original}, {match_obj['formatted']}" if prefix_original else match_obj['formatted']
    
    result = {
        "formatted": formatted_str,
        "code": match_obj['code']
    }
    
    if field_name == 'col_92' and don_vi_do_mapping:
        search_str = match_obj.get("formatted", formatted_str).replace(", Tỉnh Quảng Ninh", "")
        key = normalize_str(search_str)
        if key in don_vi_do_mapping:
            result["don_vi_do"] = don_vi_do_mapping[key].get("don_vi", "")
            result["ngay_hoan_thanh"] = don_vi_do_mapping[key].get("ngay_hoan_thanh", "")
        else:
            ward_str = normalize_str(search_str.split(",")[0])
            for map_key, map_val in don_vi_do_mapping.items():
                if map_key.startswith(ward_str):
                    result["don_vi_do"] = map_val.get("don_vi", "")
                    result["ngay_hoan_thanh"] = map_val.get("ngay_hoan_thanh", "")
                    break
                    
    return result
