# TEFAS Fon Takip Paneli

Takip listesindeki fonlar için günlük, haftalık ve yıl başından bugüne (YTD)
getirileri gösteren bir Streamlit panosu.

Fonlar: PKZ, TLY, DFI, LTL, TP2, PRY, PHE, MT2, PBR, PUK, PCS, VPS, IIE

## Çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Veri kaynağı ve kapsam notu

Uygulama, TEFAS'ın güncel fon fiyatı API'sini (`tefas.gov.tr/api/funds/fonFiyatBilgiGetir`)
kullanarak günlük fiyat geçmişinden getiri hesaplar.

TEFAS, eski toplu veri API'sini (`BindHistoryInfo` / `BindHistoryAllocation`)
2026 içinde kapattı. Yeni API yalnızca fon bazında günlük fiyat verisi
sunuyor; geçmiş **varlık dağılımı** verisi artık herkese açık bir uç
noktadan alınamıyor, bu yüzden panoda bu bölüm yer almıyor. Bunun yerine:

- **Getiriler** (günlük / haftalık / YTD) ve **büyüklük**: tam olarak
  hesaplanır ve gösterilir. Getiri Özeti tablosundaki her satır, o fonun
  resmi TEFAS sayfasına bağlantıdır (satıra tıklayınca açılır).
- **Para giriş/çıkışı**: TEFAS'ta doğrudan yayınlanmadığından, büyüklük
  değişiminden fiyat getirisinin payı çıkarılarak bir **tahmin** olarak
  hesaplanır.

Varlık dağılımı için ileride resmi ya da alternatif bir kaynak bulunursa,
`tefas_client.py` içine yeni bir fetch fonksiyonu eklenip `app.py`'ye
karşılık gelen bölüm eklenebilir.
