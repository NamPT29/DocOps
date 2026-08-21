import os
from io import BytesIO
from unittest.mock import MagicMock

import pytest
import pandas as pd
import openpyxl
from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from starlette.datastructures import UploadFile
from server.routers import templates
from server.services.excel_service import export_submissions_to_excel, get_form_schema, get_ma_xa_mapping


def test_get_form_schema_only_applies_admin_dictionary_config(mocker):
    columns = pd.MultiIndex.from_tuples([
        ('Nhóm', 'Cột thường', '', ''),
        ('Nhóm', 'Dân tộc', '', ''),
    ])
    mocker.patch(
        'server.services.excel_service._detect_excel_layout',
        return_value=('Data', [0, 1, 2, 3]),
    )
    mocker.patch('pandas.read_excel', return_value=pd.DataFrame(columns=columns))

    schema = get_form_schema(
        'dummy_path.xlsx',
        {'Dân tộc': ['01 - Kinh']},
        {'dropdown_rules': [
            {'col': 2, 'dictionary': 'Dân tộc', 'extract_mode': 'left'}
        ]},
    )
    fields = [field for category in schema for field in category['fields']]

    assert fields[0]['type'] == 'text'
    assert fields[1]['type'] == 'dropdown'
    assert fields[1]['options'] == ['01 - Kinh']
    assert fields[1]['extract_mode'] == 'left'


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


@pytest.mark.parametrize(('template_path', 'keep_vba'), [
    ('template.xlsx', False),
    ('template.xlsm', True),
])
def test_export_preserves_vba_for_xlsm(mocker, template_path, keep_vba):
    mocker.patch(
        'server.services.excel_service._detect_excel_layout',
        return_value=('Data', [0, 1, 2, 3]),
    )
    mocker.patch('server.services.excel_service.shutil.copy')
    workbook = MagicMock()
    workbook.sheetnames = ['Data']
    worksheet = MagicMock()
    worksheet.max_row = 4
    worksheet.max_column = 1
    workbook.__getitem__.return_value = worksheet
    load_workbook = mocker.patch(
        'server.services.excel_service.openpyxl.load_workbook',
        return_value=workbook,
    )

    download_path = f'report{os.path.splitext(template_path)[1]}'
    export_submissions_to_excel(template_path, [], download_path)

    load_workbook.assert_called_once_with(download_path, keep_vba=keep_vba)
    workbook.save.assert_called_once_with(download_path)


@pytest.mark.parametrize('sheet_title', ['tmp', 'Data'])
def test_get_form_schema_detects_visible_sheet_and_shifted_headers(tmp_path, sheet_title):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_title
    worksheet.append(['Mã đơn vị', 'D01'])
    worksheet.append(['Loại hồ sơ', 'Xóa án tích'])
    worksheet.merge_cells('A3:B3')
    worksheet['A3'] = 'Thông tin hồ sơ'
    worksheet['C3'] = 'Thông tin nhân thân'
    worksheet.append(['Ngôn ngữ', 'Số lượng tờ', 'Họ và tên'])
    worksheet.append(['Chọn ngôn ngữ', None, None])
    worksheet.append(['Tiếng Việt', 2, 'Nguyễn Văn A'])
    template_path = tmp_path / 'dynamic-template.xlsx'
    workbook.save(template_path)

    schema = get_form_schema(template_path)

    assert [category['category'] for category in schema] == [
        'Thông tin hồ sơ',
        'Thông tin nhân thân',
    ]
    fields = [field for category in schema for field in category['fields']]
    assert [field['name'] for field in fields] == ['col_0', 'col_1', 'col_2']
    assert fields[0]['label'] == 'Ngôn ngữ - Chọn ngôn ngữ'


def test_export_uses_detected_sheet_and_data_start(mocker):
    mocker.patch(
        'server.services.excel_service._detect_excel_layout',
        return_value=('tmp', [2, 3, 4]),
    )
    mocker.patch('server.services.excel_service.shutil.copy')
    workbook = MagicMock()
    workbook.sheetnames = ['tmp']
    worksheet = MagicMock()
    worksheet.max_row = 6
    worksheet.max_column = 3
    workbook.__getitem__.return_value = worksheet
    mocker.patch(
        'server.services.excel_service.openpyxl.load_workbook',
        return_value=workbook,
    )

    export_submissions_to_excel('template.xlsm', [], 'report.xlsm')

    workbook.__getitem__.assert_called_once_with('tmp')
    worksheet.delete_rows.assert_called_once_with(6, 1)


def test_export_keeps_original_excel_columns_when_an_input_column_is_absent(tmp_path):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Data'
    worksheet.append(['Nhóm', None, None])
    worksheet.append(['Cột A', 'Cột ẩn', 'Cột C'])
    worksheet.append(['Nhãn A', 'Nhãn ẩn', 'Nhãn C'])
    worksheet.append(['Chi tiết A', 'Chi tiết ẩn', 'Chi tiết C'])
    template_path = tmp_path / 'hidden-column-template.xlsx'
    output_path = tmp_path / 'hidden-column-output.xlsx'
    workbook.save(template_path)

    submissions = [MagicMock(data_json='{"col_0":"Giá trị A","col_2":"Giá trị C"}')]
    export_submissions_to_excel(template_path, submissions, output_path)

    exported = openpyxl.load_workbook(output_path)
    exported_sheet = exported['Data']
    assert [exported_sheet.cell(5, column).value for column in range(1, 4)] == [
        'Giá trị A',
        None,
        'Giá trị C',
    ]
    exported.close()


def test_export_copies_template_cell_styles_to_every_output_row(tmp_path):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Data'
    worksheet.append(['Nhóm', None, None])
    worksheet.append(['Cột A', 'Cột B', 'Cột C'])
    worksheet.append(['Nhãn A', 'Nhãn B', 'Nhãn C'])
    worksheet.append(['Chi tiết A', 'Chi tiết B', 'Chi tiết C'])

    black_side = Side(style='thin', color='000000')
    for column in range(1, 4):
        cell = worksheet.cell(5, column, f'mẫu {column}')
        cell.border = Border(
            left=black_side,
            right=black_side,
            top=black_side,
            bottom=black_side,
        )
        cell.font = Font(name='Arial', bold=True, color='FF0000')
        cell.alignment = Alignment(horizontal='center', vertical='center')
    worksheet['B5'].fill = PatternFill(fill_type='solid', fgColor='000000')
    worksheet['C5'].number_format = '0.00'
    worksheet.row_dimensions[5].height = 28
    worksheet['A1'].fill = PatternFill(fill_type='solid', fgColor='00FF00')
    worksheet['A1'].font = Font(bold=True)

    template_path = tmp_path / 'styled-template.xlsx'
    output_path = tmp_path / 'styled-output.xlsx'
    workbook.save(template_path)

    submissions = [
        MagicMock(data_json='{"col_0":"A1","col_1":"B1","col_2":1.25}'),
        MagicMock(data_json='{"col_0":"A2","col_1":"B2","col_2":2.5}'),
    ]
    export_submissions_to_excel(template_path, submissions, output_path)

    exported = openpyxl.load_workbook(output_path)
    exported_sheet = exported['Data']
    for row in (5, 6):
        for column in range(1, 4):
            cell = exported_sheet.cell(row, column)
            assert cell.border.left.style == 'thin'
            assert cell.border.right.style == 'thin'
            assert cell.fill.fill_type is None
            assert not cell.font.bold
            assert cell.font.name != 'Arial'
            assert cell.alignment.horizontal is None
            assert cell.number_format == 'General'
        assert exported_sheet.row_dimensions[row].height is None
    assert exported_sheet['A1'].fill.fill_type == 'solid'
    assert exported_sheet['A1'].font.bold
    assert [exported_sheet.cell(5, column).value for column in range(1, 4)] == ['A1', 'B1', 1.25]
    assert [exported_sheet.cell(6, column).value for column in range(1, 4)] == ['A2', 'B2', 2.5]
    exported.close()


def test_upload_template_accepts_xlsm_case_insensitively(monkeypatch, tmp_path):
    monkeypatch.setattr(templates, 'TEMPLATES_DIR', str(tmp_path))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    workbook_bytes = BytesIO()
    Workbook().save(workbook_bytes)
    workbook_bytes.seek(0)
    upload = UploadFile(filename='MauCoMacro.XLSM', file=workbook_bytes)

    result = templates.upload_template(upload, current_user={'role': 'admin'}, db=db)

    assert result['status'] == 'ok'
    assert (tmp_path / 'MauCoMacro.XLSM').read_bytes().startswith(b'PK')
    saved_template = db.add.call_args.args[0]
    assert saved_template.filename == 'MauCoMacro.XLSM'


def test_upload_template_rejects_disguised_excel_file(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, 'TEMPLATES_DIR', str(tmp_path))
    upload = UploadFile(filename='fake.xlsx', file=BytesIO(b'<script>alert(1)</script>'))

    with pytest.raises(HTTPException, match='File Excel không hợp lệ') as error:
        templates.upload_template(upload, current_user={'role': 'admin'}, db=MagicMock())

    assert error.value.status_code == 400
    assert not (tmp_path / 'fake.xlsx').exists()


def test_upload_template_rejects_non_excel_file(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, 'TEMPLATES_DIR', str(tmp_path))
    upload = UploadFile(filename='not-excel.pdf', file=BytesIO(b'not-excel'))

    with pytest.raises(HTTPException, match='Chỉ hỗ trợ file Excel') as error:
        templates.upload_template(upload, current_user={'role': 'admin'}, db=MagicMock())

    assert error.value.status_code == 400
    assert not (tmp_path / 'not-excel.pdf').exists()
