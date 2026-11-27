"""Generate 12 synthetic image-only PDFs and a labeled CSV in a new directory."""
import argparse
import csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ocr_benchmark import FIELDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/times.ttf"))
    args = parser.parse_args()
    font = ImageFont.truetype(str(args.font), 29)
    args.directory.mkdir(parents=True, exist_ok=False)
    types = ["Quyết định", "Báo cáo", "Thông báo", "Công văn"]
    codes = ["QĐ", "BC", "TB", "CV"]
    topics = ["tổ chức hội nghị", "kiểm kê hồ sơ", "bàn giao tài liệu"]
    with (args.directory / "labels.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["pdf", *FIELDS, "header_text"])
        writer.writeheader()
        for i in range(12):
            agency = ["SỞ NỘI VỤ", "SỞ TƯ PHÁP", "SỞ GIÁO DỤC"][i // 4]
            kind = types[i % 4]
            subject = "Về việc " + topics[i // 4]
            code = f"{101+i}/{codes[i % 4]}-VP"
            name = f"demo-{i+1:02}.pdf"
            image = Image.new("RGB", (1654, 2339), "white")
            draw = ImageDraw.Draw(image)
            for xy, label in [((80, 100), agency), ((720, 100), "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"),
                              ((80, 185), "Số: " + code), ((720, 185), f"Hà Nội, ngày {i+1:02} tháng 11 năm 2026")]:
                draw.text(xy, label, font=font, fill="black")
            if kind == "Công văn":
                draw.text((80, 265), "V/v " + subject, font=font, fill="black")
            else:
                draw.text((800, 380), kind.upper(), font=font, fill="black", anchor="mt")
                draw.text((800, 450), subject, font=font, fill="black", anchor="mt")
            image.save(args.directory / name, resolution=200)
            heading = "V/v " + subject if kind == "Công văn" else kind.upper() + " " + subject
            header = (f"{agency} CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM Số: {code} "
                      f"Hà Nội, ngày {i+1:02} tháng 11 năm 2026 {heading}")
            writer.writerow(dict(pdf=name, typeName=kind, code=code, issuedDate=f"{i+1:02}/11/2026",
                                 organName=agency, subject=subject, header_text=header))


if __name__ == "__main__":
    main()
