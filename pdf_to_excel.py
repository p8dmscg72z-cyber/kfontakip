import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def masaustu_bul() -> Path:
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


def sayiya_cevir(metin):
    """Türkçe biçimli sayıları ve tarihleri Excel'in anlayacağı değere çevirir."""
    metin = metin.strip()
    if not metin:
        return None
    if re.fullmatch(r"\d{2}[./]\d{2}[./]\d{4}", metin):  # 01.11.2026
        try:
            return datetime.strptime(metin.replace("/", "."), "%d.%m.%Y")
        except ValueError:
            return metin
    temiz = metin.replace("%", "").replace("TL", "").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d+", temiz):  # 1.234,56
        return float(temiz.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d+,\d+", temiz):  # 12,5
        return float(temiz.replace(",", "."))
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", temiz):  # 1.059.756
        return int(temiz.replace(".", ""))
    if re.fullmatch(r"-?\d+\.\d+", temiz):  # 7.5838
        return float(temiz)
    if re.fullmatch(r"-?\d+", temiz):
        return int(temiz)
    return metin


def satirlara_ayir(kelimeler, tolerans=3):
    """Kelimeleri dikey konumlarına göre satırlara gruplar."""
    satirlar = []
    for k in sorted(kelimeler, key=lambda k: (k["top"], k["x0"])):
        if satirlar and abs(satirlar[-1]["top"] - k["top"]) <= tolerans:
            satirlar[-1]["kelimeler"].append(k)
        else:
            satirlar.append({"top": k["top"], "kelimeler": [k]})
    for s in satirlar:
        s["kelimeler"].sort(key=lambda k: k["x0"])
    return satirlar


def parcalara_ayir(kelimeler):
    """Bir satırdaki birbirine yakın kelimeleri (ör. 'Fon Adı') tek hücre yapar."""
    parcalar = []
    for k in kelimeler:
        bosluk_esigi = (k["bottom"] - k["top"]) * 0.6
        if parcalar and k["x0"] - parcalar[-1]["x1"] <= bosluk_esigi:
            parcalar[-1]["text"] += " " + k["text"]
            parcalar[-1]["x1"] = k["x1"]
        else:
            parcalar.append({"text": k["text"], "x0": k["x0"], "x1": k["x1"]})
    return parcalar


def sutun_sinirlari(satir_parcalari, sayfa_genisligi):
    """Tüm satırlarda boş kalan dikey şeritleri bularak sütun sınırlarını çıkarır."""
    tablo_satirlari = [p for p in satir_parcalari if len(p) >= 3]
    if not tablo_satirlari:
        return [(0, sayfa_genisligi)]
    genislik = int(sayfa_genisligi) + 2
    doluluk = [0] * genislik
    for parcalar in tablo_satirlari:
        for p in parcalar:
            for x in range(max(0, int(p["x0"])), min(genislik, int(p["x1"]) + 1)):
                doluluk[x] += 1
    esik = max(1, len(tablo_satirlari) * 0.1)  # başlık taşmalarına tolerans
    sutunlar, bas = [], None
    for x, d in enumerate(doluluk):
        if d >= esik and bas is None:
            bas = x
        elif d < esik and bas is not None:
            sutunlar.append((bas, x))
            bas = None
    if bas is not None:
        sutunlar.append((bas, genislik))

    # Hiçbir sütuna denk gelmeyen parçalar (ör. çoğu satırı boş bir sütunun başlığı)
    # kendi sütunlarını oluştursun
    ekler = []
    for parcalar in tablo_satirlari:
        for p in parcalar:
            if not any(min(b, p["x1"]) > max(a, p["x0"]) for a, b in sutunlar):
                ekler.append((p["x0"], p["x1"]))
    for a, b in sorted(ekler):
        for i, (c, d) in enumerate(sutunlar):
            if min(b, d) > max(a, c):
                sutunlar[i] = (min(a, c), max(b, d))
                break
        else:
            sutunlar.append((a, b))
            sutunlar.sort()
    return sutunlar


def sutun_bul(parca, sutunlar):
    """Parçanın en çok örtüştüğü sütunu, örtüşme yoksa en yakınını döndürür."""
    en_iyi, en_iyi_skor = 0, None
    for i, (a, b) in enumerate(sutunlar):
        ortusme = min(b, parca["x1"]) - max(a, parca["x0"])
        skor = ortusme if ortusme > 0 else -min(abs(parca["x0"] - b), abs(parca["x1"] - a))
        if en_iyi_skor is None or skor > en_iyi_skor:
            en_iyi, en_iyi_skor = i, skor
    return en_iyi


def sayfa_tablosu(sayfa):
    kelimeler = sayfa.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
    satirlar = satirlara_ayir(kelimeler)
    satir_parcalari = [parcalara_ayir(s["kelimeler"]) for s in satirlar]
    sutunlar = sutun_sinirlari(satir_parcalari, sayfa.width)
    tablo = []
    for parcalar in satir_parcalari:
        hucreler = [""] * len(sutunlar)
        if len(parcalar) < 3:  # başlık / not gibi tablo dışı satırlar A sütununa
            for i, p in enumerate(parcalar):
                hucreler[i] = p["text"]
            tablo.append(hucreler)
            continue
        for p in parcalar:
            i = sutun_bul(p, sutunlar)
            hucreler[i] = (hucreler[i] + " " + p["text"]).strip()
        tablo.append(hucreler)
    return tablo


def sutun_genisligi_ayarla(ws):
    for i, sutun in enumerate(ws.iter_cols(), start=1):
        en_uzun = max((len(str(h.value)) for h in sutun if h.value is not None), default=0)
        ws.column_dimensions[get_column_letter(i)].width = min(max(en_uzun + 2, 8), 50)


def pdf_to_excel(pdf_yolu: Path, excel_yolu: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Veri"
    baslik = None
    satir_sayisi = 0

    with pdfplumber.open(pdf_yolu) as pdf:
        for sayfa in pdf.pages:
            for hucreler in sayfa_tablosu(sayfa):
                dolu = [h for h in hucreler if h]
                if not dolu:
                    continue
                # İlk çok sütunlu satırı başlık say, sonraki sayfalarda tekrarını atla
                if baslik is None and len(dolu) >= 3:
                    baslik = hucreler
                    ws.append(hucreler)
                    for h in ws[ws.max_row]:
                        h.font = Font(bold=True)
                    continue
                if hucreler == baslik:
                    continue
                ws.append([sayiya_cevir(h) for h in hucreler])
                satir_sayisi += 1
                for h in ws[ws.max_row]:
                    if isinstance(h.value, datetime):
                        h.number_format = "DD.MM.YYYY"

    sutun_genisligi_ayarla(ws)
    wb.save(excel_yolu)
    print(f"Tamamlandı: {excel_yolu}")
    print(f"  {satir_sayisi} satır, {ws.max_column} sütun yazıldı.")


def main():
    pdf_yolu = Path(sys.argv[1]) if len(sys.argv) > 1 else masaustu_bul() / "c.pdf"
    if not pdf_yolu.exists():
        print(f"Dosya bulunamadı: {pdf_yolu}")
        sys.exit(1)
    excel_yolu = Path(sys.argv[2]) if len(sys.argv) > 2 else pdf_yolu.with_suffix(".xlsx")
    pdf_to_excel(pdf_yolu, excel_yolu)


if __name__ == "__main__":
    main()
