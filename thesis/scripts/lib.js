// Shared builder for the thesis Word documents (Times New Roman 13, A4, VN margins).
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, LevelFormat, Footer, PageNumber, TableOfContents,
} = require('docx');

const FONT = 'Times New Roman';
const SIZE = 26; // 13pt
const PAGE_WIDTH = 11906; // A4
const MARGIN = { top: 1134, bottom: 1134, left: 1701, right: 1134 }; // 2/2/3/2 cm
const CONTENT_WIDTH = PAGE_WIDTH - MARGIN.left - MARGIN.right;

const STUDENT = [
  ['Tên đề tài', 'HỆ THỐNG SỐ HÓA TÀI LIỆU TÍCH HỢP AI'],
  ['Sinh viên thực hiện', '[Họ và tên] – Mã SV: [……] – Lớp: [……]'],
  ['Giảng viên hướng dẫn', '[Học hàm, học vị, họ và tên]'],
];

// Inline **bold** support inside plain strings.
function runs(text, extra = {}) {
  return String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(part => (
    part.startsWith('**')
      ? new TextRun({ text: part.slice(2, -2), bold: true, font: FONT, size: SIZE, ...extra })
      : new TextRun({ text: part, font: FONT, size: SIZE, ...extra })
  ));
}

function p(text, opts = {}) {
  return new Paragraph({
    children: runs(text, opts.run || {}),
    alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { after: 100, line: 312 },
    indent: opts.indent,
  });
}

function bullets(items, level = 0) {
  return items.flatMap(item => {
    if (Array.isArray(item)) return bullets(item, level + 1);
    return [new Paragraph({
      children: runs(item),
      numbering: { reference: 'bullets', level },
      alignment: AlignmentType.JUSTIFIED,
      spacing: { after: 60, line: 312 },
    })];
  });
}

function numbered(items) {
  return items.map(item => new Paragraph({
    children: runs(item),
    numbering: { reference: 'numbers', level: 0 },
    spacing: { after: 60, line: 312 },
  }));
}

function cell(text, width, { header = false, shade } = {}) {
  const lines = Array.isArray(text) ? text : [text];
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: header || shade ? { type: ShadingType.CLEAR, color: 'auto', fill: header ? 'D9E2F3' : shade } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: lines.map(line => new Paragraph({
      children: runs(line, header ? { bold: true, size: 24 } : { size: 24 }),
      alignment: header ? AlignmentType.CENTER : AlignmentType.LEFT,
      spacing: { after: 40, line: 276 },
    })),
  });
}

// widths: relative weights; rows[0] is the header row.
function table(widths, rows) {
  const total = widths.reduce((a, b) => a + b, 0);
  const dxa = widths.map(w => Math.floor((w / total) * CONTENT_WIDTH));
  dxa[dxa.length - 1] += CONTENT_WIDTH - dxa.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: '808080' };
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: dxa,
    borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
    rows: rows.map((row, i) => new TableRow({
      tableHeader: i === 0,
      children: row.map((value, j) => cell(value, dxa[j], { header: i === 0 })),
    })),
  });
}

function h(level, text) {
  const heading = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][level - 1];
  return new Paragraph({ heading, children: [new TextRun({ text, font: FONT })] });
}

function spacer() { return new Paragraph({ children: [], spacing: { after: 120 } }); }

function titleBlock(docTitle, subtitle) {
  const out = [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
      children: [new TextRun({ text: 'ĐỒ ÁN TỐT NGHIỆP', font: FONT, size: 26, bold: true })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '1F3864', space: 4 } },
      children: [new TextRun({ text: docTitle, font: FONT, size: 34, bold: true, color: '1F3864' })] }),
  ];
  if (subtitle) out.push(p(subtitle, { align: AlignmentType.CENTER, run: { italics: true } }));
  out.push(table([3, 7], [['Thông tin', 'Nội dung'], ...STUDENT]));
  out.push(spacer());
  return out;
}

function build(file, children, { toc = false } = {}) {
  const body = toc
    ? [children[0], ...children.slice(1)]
    : children;
  const doc = new Document({
    creator: 'Đồ án tốt nghiệp',
    styles: {
      default: { document: { run: { font: FONT, size: SIZE } } },
      paragraphStyles: [
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { font: FONT, size: 28, bold: true, color: '1F3864' },
          paragraph: { spacing: { before: 300, after: 140 }, outlineLevel: 0 } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { font: FONT, size: 26, bold: true },
          paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
        { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
          run: { font: FONT, size: 26, bold: true, italics: true },
          paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2 } },
      ],
    },
    numbering: {
      config: [
        { reference: 'bullets', levels: [
          { level: 0, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 567, hanging: 283 } } } },
          { level: 1, format: LevelFormat.BULLET, text: '+', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1134, hanging: 283 } } } },
        ] },
        { reference: 'numbers', levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 567, hanging: 340 } } } },
        ] },
      ],
    },
    sections: [{
      properties: { page: { size: { width: PAGE_WIDTH, height: 16838 }, margin: MARGIN } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 22 })] })] }) },
      children: body,
    }],
  });
  return Packer.toBuffer(doc).then(buf => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, buf);
    console.log('wrote', file);
  });
}

module.exports = { p, bullets, numbered, table, h, spacer, titleBlock, build, TableOfContents, AlignmentType };
