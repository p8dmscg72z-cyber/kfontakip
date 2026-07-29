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
sunuyor; geçmiş **fon büyüklüğü / para giriş-çıkışı** ve **varlık dağılımı**
verileri artık herkese açık bir uç noktadan alınamıyor. Bu yüzden uygulamada:

- **Getiriler** (günlük / haftalık / YTD): tam olarak hesaplanır ve gösterilir.
- **Para giriş/çıkışı** ve **Varlık dağılımı**: TEFAS API'sinde artık mevcut
  olmadığından, ilgili bölümlerde bir bilgi notu ve her fonun resmi TEFAS
  sayfasına doğrudan bağlantı gösterilir.

Bu iki veri için ileride resmi ya da alternatif bir kaynak bulunursa,
`tefas_client.py` içine yeni bir fetch fonksiyonu eklenip `app.py`'daki ilgili
bölümler güncellenebilir.
