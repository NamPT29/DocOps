import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from server.services.excel_service import load_dictionaries, get_ma_xa_mapping

def test_load_dictionaries(mocker):
    # Create mock dataframes
    df_dan_toc = pd.DataFrame([
        ['Kinh', 'Kinh'],
        ['Tay', 'Tày']
    ])
    df_quoc_tich = pd.DataFrame([
        ['VN', 'Việt Nam'],
        ['US', 'Hoa Kỳ']
    ])
    
    # Mock pd.read_excel to return these dataframes based on sheet_name
    def mock_read_excel(*args, **kwargs):
        sheet_name = kwargs.get('sheet_name')
        if sheet_name == 'DM_DanToc':
            return df_dan_toc
        elif sheet_name == 'DM_QuocTich':
            return df_quoc_tich
        return pd.DataFrame()

    mocker.patch('pandas.read_excel', side_effect=mock_read_excel)
    
    # Mock pd.ExcelFile
    mock_xl = MagicMock()
    mock_xl.sheet_names = ['DM_DanToc', 'DM_QuocTich', 'OtherSheet']
    mocker.patch('pandas.ExcelFile', return_value=mock_xl)

    dicts = load_dictionaries('dummy_path.xlsx')

    assert 'DM_DanToc' in dicts
    assert 'DM_QuocTich' in dicts
    assert 'OtherSheet' not in dicts
    assert dicts['DM_DanToc'] == ['Kinh - Kinh', 'Tay - Tày']
    assert dicts['DM_QuocTich'] == ['VN - Việt Nam', 'US - Hoa Kỳ']
    
    # Check hardcoded dictionaries
    assert 'Giới tính' in dicts
    assert dicts['Giới tính'] == ["1 - Nam", "0 - Nữ"]


def test_get_ma_xa_mapping(mocker):
    # Mock data for MaXa_3cap_2cap
    df_maxa = pd.DataFrame({
        'Mã xã 3 cấp (cũ)': ['001', '002'],
        'Tên xã 3 cấp': ['Xã A', 'Xã B'],
        'Quận/huyện 3 cấp': ['Huyện X', 'Huyện Y'],
        'Tỉnh 3 cấp (cũ)': ['Tỉnh 1', 'Tỉnh 1'],
        'Mã xã 2 cấp (mới)': ['001', None],
        'Tên xã 2 cấp': ['Xã A mới', None],
        'Tỉnh/TP (2 cấp)': ['Tỉnh 1', None]
    })
    
    mocker.patch('pandas.read_excel', return_value=df_maxa)
    
    mappings = get_ma_xa_mapping('dummy_path.xlsx')
    
    map_3 = mappings['mapping_3_cap']
    map_2 = mappings['mapping_2_cap']
    
    # Test normalized key generation (xã ahuyện xtỉnh 1 without spaces/accents)
    key_3 = 'xãahuyệnxtỉnh1'
    assert key_3 in map_3
    assert map_3[key_3]['code'] == '001'
    assert map_3[key_3]['formatted'] == 'Xã A, Huyện X, Tỉnh 1'
    
    key_2 = 'xãamớitỉnh1'
    assert key_2 in map_2
    assert map_2[key_2]['code'] == '001'
    assert map_2[key_2]['formatted'] == 'Xã A mới, Tỉnh 1'
