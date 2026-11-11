"""
Masaüstündeki c.pdf dosyasının içeriğini Excel'e aktarır.

Kurulum:
    pip install pdfplumber openpyxl

Kullanım:
    python pdf_to_excel.py                    # Masaüstü\\c.pdf -> Masaüstü\\c.xlsx
    python pdf_to_excel.py dosya.pdf          # başka bir PDF
    python pdf_to_excel.py dosya.pdf cikti.xlsx

Çıktı:
    - PDF'teki her tablo ayrı bir sayfaya (Tablo_1, Tablo_2, ...) yazılır.
    - Tüm metin, sayfa ve satır numarasıyla birlikte "Metin" sayfasına yazılır.
"""

import sys
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def masaustu_bul() -> Path:
    """Windows'ta OneDrive altındaki masaüstünü de dikkate alır."""
    home = Path.home()
    adaylar = [
        home / "Desktop",
        home / "Masaüstü",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "Masaüstü",
    ]
    for aday in adaylar:
        if (aday / "c.pdf").exists():
            return aday
    for aday in adaylar:
        if aday.exists():
            return aday
    return home / "Desktop"


def sayiya_cevir(deger):
    """'1.234,56' veya '1234.56' gibi metinleri sayıya çevirmeyi dener."""
    if deger is None:
        return ""
    metin = str(deger).strip()
    if not metin:
        return ""
    temiz = metin.replace(" ", "").replace("%", "").replace("TL", "")
    try:
        if "," in temiz:  # Türkçe biçim: 1.234,56
            return float(temiz.replace(".", "").replace(",", "."))
        return float(temiz) if "." in temiz else int(temiz)
    except ValueError:
        return metin


def sutun_genisligi_ayarla(ws):
    for i, sutun in enumerate(ws.iter_cols(), start=1):
        en_uzun = max((len(str(h.value)) for h in sutun if h.value is not None), default=0)
        ws.column_dimensions[get_column_letter(i)].width = min(max(en_uzun + 2, 8), 60)


def pdf_to_excel(pdf_yolu: Path, excel_yolu: Path):
    wb = Workbook()
    metin_ws = wb.active
    metin_ws.title = "Metin"
    metin_ws.append(["Sayfa", "Satır", "İçerik"])
    for h in metin_ws[1]:
        h.font = Font(bold=True)

    tablo_sayisi = 0
    with pdfplumber.open(pdf_yolu) as pdf:
        for sayfa_no, sayfa in enumerate(pdf.pages, start=1):
            # Tablolar
            for tablo in sayfa.extract_tables():
                if not tablo:
                    continue
                tablo_sayisi += 1
                ws = wb.create_sheet(f"Tablo_{tablo_sayisi}")
                ws.append([f"Kaynak: sayfa {sayfa_no}"])
                ws["A1"].font = Font(italic=True)
                for satir_no, satir in enumerate(tablo):
                    if satir_no == 0:
                        ws.append([("" if h is None else str(h).strip()) for h in satir])
                        for h in ws[ws.max_row]:
                            h.font = Font(bold=True)
                    else:
                        ws.append([sayiya_cevir(h) for h in satir])
                sutun_genisligi_ayarla(ws)

            # Düz metin
            metin = sayfa.extract_text() or ""
            for satir_no, satir in enumerate(metin.splitlines(), start=1):
                if satir.strip():
                    metin_ws.append([sayfa_no, satir_no, satir])

    sutun_genisligi_ayarla(metin_ws)
    wb.save(excel_yolu)
    print(f"Tamamlandı: {excel_yolu}")
    print(f"  {tablo_sayisi} tablo bulundu, metin 'Metin' sayfasına yazıldı.")


def main():
    if len(sys.argv) > 1:
        pdf_yolu = Path(sys.argv[1])
    else:
        pdf_yolu = masaustu_bul() / "c.pdf"

    if not pdf_yolu.exists():
        print(f"Dosya bulunamadı: {pdf_yolu}")
        sys.exit(1)

    excel_yolu = Path(sys.argv[2]) if len(sys.argv) > 2 else pdf_yolu.with_suffix(".xlsx")
    pdf_to_excel(pdf_yolu, excel_yolu)


if __name__ == "__main__":
    main()
