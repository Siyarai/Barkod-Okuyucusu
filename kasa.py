import customtkinter as ctk
import sqlite3
import sys
import os
from datetime import datetime

# DB her zaman uygulamanın yanında: PyInstaller exe'sinde exe'nin klasörü,
# script olarak çalıştırılınca kasa.py'nin klasörü (çalışma dizininden bağımsız)
if getattr(sys, 'frozen', False):
    UYGULAMA_DIZINI = os.path.dirname(sys.executable)
else:
    UYGULAMA_DIZINI = os.path.dirname(os.path.abspath(__file__))
DB_YOLU = os.path.join(UYGULAMA_DIZINI, "bufe_veritabani.db")

try:
    import winsound
except ImportError:
    winsound = None

# --- RENK PALETİ ---
RENK_ANA    = "#2b2b2b"
RENK_PANEL  = "#3a3a3a"
RENK_YESIL  = "#2ecc71"
RENK_KIRMIZI= "#e74c3c"
RENK_MAVI   = "#3498db"
RENK_SARI   = "#f1c40f"
FONT_ANA    = "Segoe UI"

# Alacakta bu gün sayısını geçmiş işlemler veresiye listesinde ⚠️ ile vurgulanır
VERESIYE_UYARI_GUN_ESIGI = 14

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class BufeSistemi(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Köşem Büfe - Kasa Sistemi")
        self.geometry("1200x800")

        self.veritabani_olustur()
        self.sepet = []
        self.toplam_fiyat   = 0   # kuruş (integer)
        self.toplam_maliyet = 0   # kuruş (integer)
        self.son_islem      = None  # sadece EN SON tamamlanan satış iptal edilebilir
        self.sepet_gorunum  = []    # self.sepet ile hizalı görünüm metinleri (saat, stok uyarısı)
        self.secili_urunler = set() # ürün listesinde checkbox ile seçilen barkodlar
        # Bekletilen satışlar (park): uygulama kapanınca kaybolur — bilinçli tercih,
        # Son Satışı İptal Et ile aynı mantık (DB'ye yazılmaz)
        self.bekleyen_satislar = {}
        self.bekleyen_sayac    = 0
        self.son_toplu_degisiklik = None  # son toplu fiyat değişikliğinin eski değerleri (tek seviyeli undo)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.arayuz_olustur()

        self.ozet_guncelle()
        self.hizli_tuslari_yukle()
        self.urunleri_listele()
        self.veresiye_listele()

        self.protocol("WM_DELETE_WINDOW", self.uygulamayi_kapat)

    def uygulamayi_kapat(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()

    def veritabani_olustur(self):
        self.conn = sqlite3.connect(DB_YOLU)
        self.c = self.conn.cursor()

        # Tüm parasal sütunlar INTEGER (kuruş). CREATE TABLE IF NOT EXISTS yeni DB'lere uygulanır.
        self.c.execute('''CREATE TABLE IF NOT EXISTS Urunler
                         (barkod TEXT PRIMARY KEY, isim TEXT, alis INTEGER, satis INTEGER,
                          satilan_adet INTEGER DEFAULT 0)''')
        try:
            self.c.execute("ALTER TABLE Urunler ADD COLUMN stok INTEGER DEFAULT 0")
            self.c.execute("ALTER TABLE Urunler ADD COLUMN hizli INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Ürün grupları (FK: Urunler.grup_id → Gruplar.id; SQLite FK'yi zorlamaz,
        # tutarlılık uygulama tarafında korunur)
        self.c.execute('''CREATE TABLE IF NOT EXISTS Gruplar
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          isim TEXT UNIQUE NOT NULL)''')
        try:
            self.c.execute(
                "ALTER TABLE Urunler ADD COLUMN grup_id INTEGER REFERENCES Gruplar(id)")
        except sqlite3.OperationalError:
            pass

        self.c.execute('''CREATE TABLE IF NOT EXISTS Gunluk
                         (id INTEGER PRIMARY KEY, ciro INTEGER, kar INTEGER)''')
        self.c.execute("INSERT OR IGNORE INTO Gunluk (id, ciro, kar) VALUES (1, 0, 0)")

        self.c.execute('''CREATE TABLE IF NOT EXISTS GunlukGecmis
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT,
                          ciro INTEGER, kar INTEGER)''')

        self.c.execute('''CREATE TABLE IF NOT EXISTS Veresiye
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, isim TEXT, tip TEXT,
                          bakiye INTEGER DEFAULT 0)''')
        try:
            self.c.execute("ALTER TABLE Veresiye ADD COLUMN tarih TEXT")
            self.c.execute("ALTER TABLE Veresiye ADD COLUMN detay TEXT")
        except sqlite3.OperationalError:
            pass

        # Sıralı tek seferlik migration'lar (PRAGMA user_version ile idempotent):
        # 0 → 1 : eski REAL (₺) → INTEGER (kuruş = ₺ × 100)
        # 1 → 2 : "Genel" grubu oluştur, grupsuz tüm ürünleri ona ata
        # Yeni boş DB de 0'dan başlayıp zincirin tamamından geçer (boş tablolarda no-op).
        self.c.execute("PRAGMA user_version")
        db_version = self.c.fetchone()[0]

        if db_version == 0:
            self.c.execute(
                "UPDATE Urunler SET "
                "alis  = CAST(ROUND(alis  * 100) AS INTEGER), "
                "satis = CAST(ROUND(satis * 100) AS INTEGER)")
            self.c.execute(
                "UPDATE Gunluk SET "
                "ciro = CAST(ROUND(ciro * 100) AS INTEGER), "
                "kar  = CAST(ROUND(kar  * 100) AS INTEGER)")
            self.c.execute(
                "UPDATE GunlukGecmis SET "
                "ciro = CAST(ROUND(ciro * 100) AS INTEGER), "
                "kar  = CAST(ROUND(kar  * 100) AS INTEGER)")
            self.c.execute(
                "UPDATE Veresiye SET "
                "bakiye = CAST(ROUND(bakiye * 100) AS INTEGER)")
            self.c.execute("PRAGMA user_version = 1")
            db_version = 1

        if db_version == 1:
            self.c.execute("INSERT OR IGNORE INTO Gruplar (isim) VALUES ('Genel')")
            self.c.execute(
                "UPDATE Urunler SET grup_id = (SELECT id FROM Gruplar WHERE isim='Genel') "
                "WHERE grup_id IS NULL")
            self.c.execute("PRAGMA user_version = 2")
            db_version = 2

        self.conn.commit()

    # =========================================================
    # PARA YARDIMCI METODları
    # =========================================================
    @staticmethod
    def format_tl(kurus: int) -> str:
        """Kuruş bazlı integer'ı '12.50 ₺' formatında döndürür."""
        return f"{kurus / 100:.2f} ₺"

    @staticmethod
    def _para_parse(metin: str) -> int:
        """Kullanıcı girdisini (TL, virgül veya nokta) kuruş integer'ına çevirir."""
        return int(round(float(metin.replace(",", ".")) * 100))

    @staticmethod
    def _isim_normalize(s: str) -> str:
        """İsim karşılaştırması için normalize eder: Türkçe İ/I uyumu.
        "ali".upper() → "ALI" (noktasız), kayıtta "ALİŞAN" (noktalı İ) —
        iki tarafı da noktasız I'ya indirger. Yalnızca karşılaştırma için;
        gösterilen/DB'deki isim değişmez."""
        return s.upper().replace("İ", "I")

    def ses_cikar(self, tur="ok"):
        if winsound:
            freq = 1500 if tur == "ok" else 500
            winsound.Beep(freq, 150)

    # =========================================================
    # ARAYÜZ OLUŞTURMA
    # =========================================================
    def arayuz_olustur(self):
        self.sekme_alani = ctk.CTkTabview(self, corner_radius=15, fg_color=RENK_ANA,
                                          command=self.sekme_degistir)
        self.sekme_alani.pack(pady=10, padx=10, fill="both", expand=True)

        self.sekme_satis    = self.sekme_alani.add(" 🛒 Satış Ekranı ")
        self.sekme_ekle     = self.sekme_alani.add(" 📦 Ürün & Stok ")
        self.sekme_veresiye = self.sekme_alani.add(" 📓 Veresiye Defteri ")
        self.sekme_ozet     = self.sekme_alani.add(" 📊 Rapor & Kasa ")

        self.satis_ekrani_kur()
        self.urun_ekle_ekrani_kur()
        self.veresiye_ekrani_kur()
        self.ozet_ekrani_kur()

    def sekme_degistir(self):
        secili = self.sekme_alani.get()
        if secili == " 📦 Ürün & Stok ":
            self.urunleri_listele()
        elif secili == " 📓 Veresiye Defteri ":
            self.veresiye_listele()
        elif secili == " 📊 Rapor & Kasa ":
            self.ozet_guncelle()

    # =========================================================
    # 1. SATIŞ EKRANI
    # =========================================================
    def satis_ekrani_kur(self):
        self.sekme_satis.grid_columnconfigure(0, weight=3)
        self.sekme_satis.grid_columnconfigure(1, weight=2)
        self.sekme_satis.grid_rowconfigure(0, weight=1)

        sol_panel = ctk.CTkFrame(self.sekme_satis, fg_color=RENK_PANEL, corner_radius=15)
        sol_panel.grid(row=0, column=0, padx=(0, 10), sticky="nsew")

        ctk.CTkLabel(sol_panel, text="🧾 Sepet / Fiş Listesi",
                     font=(FONT_ANA, 18, "bold"), text_color="#bbb").pack(pady=10)
        # Satır bazlı sepet: her kalemin yanında ✕ (tekil silme) butonu var
        self.sepet_liste_frame = ctk.CTkScrollableFrame(sol_panel, fg_color="#222",
                                                        corner_radius=10)
        self.sepet_liste_frame.pack(pady=5, padx=10, fill="both", expand=True)

        sag_panel = ctk.CTkFrame(self.sekme_satis, fg_color="transparent")
        sag_panel.grid(row=0, column=1, sticky="nsew")

        fiyat_karti = ctk.CTkFrame(sag_panel, fg_color="#222",
                                   border_color=RENK_YESIL, border_width=2, corner_radius=20)
        fiyat_karti.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(fiyat_karti, text="TOPLAM TUTAR",
                     font=(FONT_ANA, 14, "bold"), text_color="#888").pack(pady=(15, 0))
        self.toplam_etiketi = ctk.CTkLabel(fiyat_karti, text="0.00 ₺",
                                           font=(FONT_ANA, 48, "bold"), text_color=RENK_YESIL)
        self.toplam_etiketi.pack(pady=(0, 15))

        ctk.CTkLabel(sag_panel, text="⚡ Hızlı Ürünler", font=(FONT_ANA, 14, "bold")).pack(anchor="w")
        self.hizli_tuslar_frame = ctk.CTkScrollableFrame(sag_panel, height=80,
                                                          orientation="horizontal", fg_color=RENK_PANEL)
        self.hizli_tuslar_frame.pack(fill="x", pady=(0, 10))

        input_frame = ctk.CTkFrame(sag_panel, fg_color=RENK_PANEL, corner_radius=15)
        input_frame.pack(fill="x", pady=10, ipady=10)

        ctk.CTkLabel(input_frame, text="Adet", font=(FONT_ANA, 12)).pack(anchor="w", padx=20)
        self.satis_adet = ctk.CTkEntry(input_frame, width=200, height=40,
                                       font=(FONT_ANA, 18, "bold"), justify="center", corner_radius=10)
        self.satis_adet.insert(0, "1")
        self.satis_adet.pack(padx=20, pady=(0, 10), fill="x")

        ctk.CTkLabel(input_frame, text="Barkod Okut", font=(FONT_ANA, 12)).pack(anchor="w", padx=20)
        self.satis_barkod = ctk.CTkEntry(input_frame, width=200, height=45,
                                         placeholder_text="||||||||||||||",
                                         font=(FONT_ANA, 18), corner_radius=10)
        self.satis_barkod.pack(padx=20, pady=(0, 15), fill="x")
        self.satis_barkod.bind("<Return>", self.urunu_sepete_ekle)
        self.satis_barkod.focus()

        self.bitir_buton = ctk.CTkButton(sag_panel, text="✅ SATIŞI ONAYLA",
                                         font=(FONT_ANA, 20, "bold"), height=55,
                                         fg_color=RENK_YESIL, hover_color="#27ae60",
                                         corner_radius=15, command=self.islemi_bitir)
        self.bitir_buton.pack(fill="x", pady=5)

        self.veresiye_buton = ctk.CTkButton(sag_panel, text="📓 SEPETİ BORCA YAZ",
                                            font=(FONT_ANA, 16, "bold"), height=45,
                                            fg_color=RENK_SARI, text_color="black",
                                            hover_color="#f39c12", corner_radius=15,
                                            command=self.sepetteki_borca_yaz)
        self.veresiye_buton.pack(fill="x", pady=5)

        self.temizle_buton = ctk.CTkButton(sag_panel, text="🗑️ İPTAL ET / TEMİZLE",
                                           font=(FONT_ANA, 14, "bold"), height=35,
                                           fg_color=RENK_KIRMIZI, hover_color="#c0392b",
                                           corner_radius=15, command=self.sepeti_temizle)
        self.temizle_buton.pack(fill="x", pady=5)

        beklet_frame = ctk.CTkFrame(sag_panel, fg_color="transparent")
        beklet_frame.pack(fill="x", pady=(0, 5))
        self.beklet_buton = ctk.CTkButton(beklet_frame, text="⏸ Müşteriyi Beklet",
                                          font=(FONT_ANA, 13, "bold"), height=35,
                                          fg_color="#555", hover_color="#777",
                                          corner_radius=15, state="disabled",
                                          command=self.musteri_beklet)
        self.beklet_buton.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self.bekleyenler_buton = ctk.CTkButton(beklet_frame, text="⏸ Bekleyenler (0)",
                                               font=(FONT_ANA, 13, "bold"), height=35,
                                               fg_color="#555", hover_color="#777",
                                               corner_radius=15, state="disabled",
                                               command=self.bekleyenler_popup)
        self.bekleyenler_buton.pack(side="right", expand=True, fill="x", padx=(3, 0))

        self.iptal_buton = ctk.CTkButton(sag_panel, text="↩️ Son Satışı İptal Et",
                                          font=(FONT_ANA, 13, "bold"), height=35,
                                          fg_color="#555", hover_color="#777",
                                          corner_radius=15, command=self.son_satisi_iptal_et)
        self.iptal_buton.pack(fill="x", pady=(0, 5))

    def sepetteki_borca_yaz(self):
        if not self.sepet:
            return

        pencere = ctk.CTkToplevel(self)
        pencere.title("Borca Yaz - Müşteri Seçimi")
        pencere.geometry("450x550")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text="📋 Kayıtlı Müşteriler",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_SARI).pack(pady=(20, 5))

        arama_entry = ctk.CTkEntry(pencere, placeholder_text="🔍 Müşteri Ara...",
                                   font=(FONT_ANA, 14), height=35)
        arama_entry.pack(fill="x", padx=20, pady=(0, 5))

        liste_frame = ctk.CTkScrollableFrame(pencere, height=180, fg_color="#222")
        liste_frame.pack(fill="x", padx=20, pady=5)

        self.c.execute("SELECT DISTINCT isim FROM Veresiye WHERE tip='alacak' ORDER BY isim ASC")
        musteriler = self.c.fetchall()

        def onayla(isim):
            isim = isim.upper().strip()
            if not isim:
                return

            detay_listesi = [f"{adet}x {urun_isim}" for _, urun_isim, _, _, adet in self.sepet]
            urun_detay_metni = ", ".join(detay_listesi)
            tarih = datetime.now().strftime("%d.%m.%Y %H:%M")

            # tarih sütunu da çekiliyor — iptal sırasında eski tarih geri yazılacak
            self.c.execute("SELECT id, bakiye, tarih, detay FROM Veresiye WHERE isim=? AND tip='alacak'", (isim,))
            mevcut = self.c.fetchone()
            yeni_detay_kismi = f"[{tarih}] {urun_detay_metni}"

            if mevcut:
                v_id       = mevcut[0]
                eski_tarih = mevcut[2]           # iptal için saklanacak
                eski_detay = mevcut[3] if mevcut[3] else ""
                yeni_detay = f"{yeni_detay_kismi} | {eski_detay}" if eski_detay else yeni_detay_kismi
                self.c.execute(
                    "UPDATE Veresiye SET bakiye = bakiye + ?, tarih = ?, detay = ? "
                    "WHERE isim=? AND tip='alacak'",
                    (self.toplam_fiyat, tarih, yeni_detay, isim))
            else:
                # Yeni müşteri kaydı — iptal edilirse kayıt tamamen silinecek
                eski_tarih = None
                self.c.execute(
                    "INSERT INTO Veresiye (isim, tip, bakiye, tarih, detay) VALUES (?, 'alacak', ?, ?, ?)",
                    (isim, self.toplam_fiyat, tarih, yeni_detay_kismi))
                v_id = self.c.lastrowid

            # En son satış bilgisini hafızaya al; yeni satış yapılınca otomatik üzerine yazılır
            self.son_islem = {
                "zaman": tarih,
                "sepet": list(self.sepet),
                "toplam_fiyat": self.toplam_fiyat,
                "toplam_maliyet": self.toplam_maliyet,
                "tip": "veresiye",
                "veresiye_id": v_id,
                "veresiye_musteri": isim,
                "veresiye_detay_eklendi": yeni_detay_kismi,
                "veresiye_eski_tarih": eski_tarih,  # None → yeni kayıt → iptalde DELETE
            }

            self._satisi_isle(self.sepet, self.toplam_fiyat, self.toplam_maliyet)

            self.conn.commit()
            self.sepeti_temizle(tamamen=True)
            pencere.destroy()
            self.ses_cikar("ok")

        def musteri_listesi_ciz(event=None):
            for w in liste_frame.winfo_children():
                w.destroy()
            aranan = self._isim_normalize(arama_entry.get().strip())
            eslesenler = [m for (m,) in musteriler
                          if aranan in self._isim_normalize(m)] if aranan \
                         else [m for (m,) in musteriler]
            if eslesenler:
                for m_isim in eslesenler:
                    btn = ctk.CTkButton(liste_frame, text=f"{m_isim}",
                                        font=(FONT_ANA, 14, "bold"), fg_color=RENK_PANEL,
                                        hover_color="#444", height=35, anchor="w",
                                        command=lambda n=m_isim: onayla(n))
                    btn.pack(fill="x", pady=3, padx=5)
            elif musteriler:
                ctk.CTkLabel(liste_frame, text="Eşleşen müşteri bulunamadı.",
                             font=(FONT_ANA, 14), text_color="#aaa").pack(pady=20)
            else:
                ctk.CTkLabel(liste_frame, text="Henüz kayıtlı müşteri yok.",
                             font=(FONT_ANA, 14), text_color="#aaa").pack(pady=20)

        arama_entry.bind("<KeyRelease>", musteri_listesi_ciz)
        musteri_listesi_ciz()

        ctk.CTkLabel(pencere, text="➕ Veya Yeni Müşteri Ekle:",
                     font=(FONT_ANA, 16, "bold"), text_color=RENK_MAVI).pack(pady=(20, 5))
        yeni_isim_entry = ctk.CTkEntry(pencere, font=(FONT_ANA, 16),
                                       placeholder_text="Yeni Müşteri Adı",
                                       justify="center", height=40)
        yeni_isim_entry.pack(pady=5, padx=30, fill="x")
        yeni_isim_entry.focus()

        ctk.CTkButton(pencere, text="Yeni Kişiye Yaz", fg_color=RENK_YESIL,
                      font=(FONT_ANA, 14, "bold"), height=40,
                      command=lambda: onayla(yeni_isim_entry.get())).pack(pady=10, padx=30, fill="x")

    def hizli_satis_tetikle(self, barkod):
        self.satis_barkod.delete(0, "end")
        self.satis_barkod.insert(0, barkod)
        self.urunu_sepete_ekle(None)

    def hizli_tuslari_yukle(self):
        for widget in self.hizli_tuslar_frame.winfo_children():
            widget.destroy()
        self.c.execute("SELECT barkod, isim, satis FROM Urunler WHERE hizli=1")
        for barkod, isim, satis in self.c.fetchall():
            btn = ctk.CTkButton(self.hizli_tuslar_frame,
                                text=f"{isim}\n{self.format_tl(satis)}",
                                width=100, height=60, font=(FONT_ANA, 14, "bold"),
                                fg_color=RENK_MAVI, hover_color="#2980b9",
                                command=lambda b=barkod: self.hizli_satis_tetikle(b))
            btn.pack(side="left", padx=5, pady=5)

    def urunu_sepete_ekle(self, event):
        barkod = self.satis_barkod.get().strip()
        self.satis_barkod.delete(0, "end")

        try:
            adet = int(self.satis_adet.get())
            if adet < 1:
                adet = 1
        except ValueError:
            adet = 1

        self.c.execute("SELECT isim, alis, satis, stok FROM Urunler WHERE barkod=?", (barkod,))
        urun = self.c.fetchone()

        if urun:
            isim, alis, satis, stok = urun  # alis ve satis kuruş (integer)

            if stok < adet:
                self.ses_cikar("hata")
                self.toplam_etiketi.configure(
                    text=f"STOK YETERSİZ! ({stok} adet)", text_color=RENK_KIRMIZI)
                self.after(1800, lambda: self.toplam_etiketi.configure(
                    text=self.format_tl(self.toplam_fiyat), text_color=RENK_YESIL))
                return

            self.ses_cikar("ok")
            toplam_satis = satis * adet   # kuruş
            toplam_alis  = alis  * adet   # kuruş
            self.sepet.append((barkod, isim, toplam_alis, toplam_satis, adet))
            self.toplam_fiyat   += toplam_satis
            self.toplam_maliyet += toplam_alis

            stok_uyarisi = f" (Kalan: {stok - adet})" if stok - adet < 10 else ""
            zaman = datetime.now().strftime("%H:%M")
            satir = f"[{zaman}] {isim[:15]:<15} x{adet:<2} {self.format_tl(toplam_satis):>9}{stok_uyarisi}"

            self.sepet_gorunum.append(satir)
            self._sepet_gorunumu_yenile()
            self._beklet_butonlari_guncelle()
            self.toplam_etiketi.configure(text=self.format_tl(self.toplam_fiyat), text_color=RENK_YESIL)
            self.satis_adet.delete(0, "end")
            self.satis_adet.insert(0, "1")
        else:
            self.ses_cikar("hata")
            self.toplam_etiketi.configure(text="BULUNAMADI!", text_color=RENK_KIRMIZI)
            self.after(1500, lambda: self.toplam_etiketi.configure(
                text=self.format_tl(self.toplam_fiyat), text_color=RENK_YESIL))

    def _sepet_gorunumu_yenile(self, mesaj=None):
        """Sepet listesini self.sepet/self.sepet_gorunum'dan yeniden çizer."""
        for w in self.sepet_liste_frame.winfo_children():
            w.destroy()

        if mesaj:
            ctk.CTkLabel(self.sepet_liste_frame, text=mesaj,
                         font=("Consolas", 15), text_color="#aaa").pack(pady=10)
            return

        for i, metin in enumerate(self.sepet_gorunum):
            satir = ctk.CTkFrame(self.sepet_liste_frame, fg_color="transparent")
            satir.pack(fill="x", pady=1)
            ctk.CTkLabel(satir, text=metin, font=("Consolas", 15),
                         text_color="white", anchor="w").pack(side="left", padx=(5, 0))
            ctk.CTkButton(satir, text="✕", width=28, height=24,
                          font=(FONT_ANA, 12, "bold"),
                          fg_color="transparent", hover_color=RENK_KIRMIZI,
                          text_color="#888",
                          command=lambda idx=i: self.sepetten_kalem_sil(idx)).pack(
                              side="right", padx=(0, 5))

        # Son eklenen satır görünür kalsın
        self.after(50, lambda: self._sepet_sona_kaydir())

    def _sepet_sona_kaydir(self):
        try:
            self.sepet_liste_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass  # CTk iç API'si değişirse kaydırma sessizce atlanır

    def sepetten_kalem_sil(self, index):
        """Onaylanmamış sepetten tek kalemi çıkarır. DB'ye/stoğa dokunmaz —
        henüz commit edilmiş bir şey yok, yalnızca bellekteki sepet düzeltiliyor."""
        if index >= len(self.sepet):
            return
        _, _, toplam_alis, toplam_satis, _ = self.sepet.pop(index)
        self.sepet_gorunum.pop(index)
        self.toplam_fiyat   -= toplam_satis
        self.toplam_maliyet -= toplam_alis
        self._sepet_gorunumu_yenile()
        self._beklet_butonlari_guncelle()
        self.toplam_etiketi.configure(text=self.format_tl(self.toplam_fiyat),
                                      text_color=RENK_YESIL)

    def _satisi_isle(self, sepet, toplam_fiyat, toplam_maliyet):
        """Günlük ciro/kar ve ürün stok/satilan_adet güncellemesini yapar. commit() çağırmaz."""
        kar = toplam_fiyat - toplam_maliyet
        self.c.execute(
            "UPDATE Gunluk SET ciro = ciro + ?, kar = kar + ? WHERE id=1",
            (toplam_fiyat, kar))
        for barkod, _, _, _, adet in sepet:
            self.c.execute(
                "UPDATE Urunler SET satilan_adet = satilan_adet + ?, stok = stok - ? WHERE barkod=?",
                (adet, adet, barkod))

    def islemi_bitir(self):
        if not self.sepet:
            return
        # En son satış bilgisini hafızaya al; yeni satış yapılınca otomatik üzerine yazılır
        self.son_islem = {
            "zaman": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "sepet": list(self.sepet),
            "toplam_fiyat": self.toplam_fiyat,
            "toplam_maliyet": self.toplam_maliyet,
            "tip": "nakit",
            "veresiye_id": None,
            "veresiye_musteri": None,
            "veresiye_detay_eklendi": None,
        }
        self._satisi_isle(self.sepet, self.toplam_fiyat, self.toplam_maliyet)
        self.conn.commit()
        self.sepeti_temizle(tamamen=True)
        self.ses_cikar("ok")

    def son_satisi_iptal_et(self):
        if not self.son_islem:
            self.toplam_etiketi.configure(text="İptal edilecek\nişlem yok!", text_color=RENK_KIRMIZI)
            self.after(1800, lambda: self.toplam_etiketi.configure(
                text=self.format_tl(self.toplam_fiyat), text_color=RENK_YESIL))
            return

        islem = self.son_islem
        urun_sayisi = sum(adet for _, _, _, _, adet in islem["sepet"])
        tip_str = "Nakit" if islem["tip"] == "nakit" else f"Veresiye → {islem['veresiye_musteri']}"
        ozet = (f"Zaman : {islem['zaman']}\n"
                f"Tutar : {self.format_tl(islem['toplam_fiyat'])}\n"
                f"Kalem : {urun_sayisi} adet\n"
                f"Tür   : {tip_str}")

        pencere = ctk.CTkToplevel(self)
        pencere.title("Son Satışı İptal Et")
        pencere.geometry("420x260")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text="⚠️ Son Satışı İptal Et",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_KIRMIZI).pack(pady=(20, 10))
        ctk.CTkLabel(pencere, text=ozet, font=("Consolas", 13),
                     justify="left", text_color="#ddd").pack(pady=5, padx=30, anchor="w")

        btn_frame = ctk.CTkFrame(pencere, fg_color="transparent")
        btn_frame.pack(pady=20, fill="x", padx=30)

        def do_iptal():
            pencere.destroy()
            self._iptal_uygula()

        ctk.CTkButton(btn_frame, text="✅ Evet, İptal Et", fg_color=RENK_KIRMIZI,
                      hover_color="#c0392b", font=(FONT_ANA, 14, "bold"),
                      command=do_iptal).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="❌ Vazgeç", fg_color=RENK_PANEL,
                      hover_color="#444", font=(FONT_ANA, 14, "bold"),
                      command=pencere.destroy).pack(side="right", expand=True, padx=5)

    def _iptal_uygula(self):
        islem = self.son_islem
        if not islem:
            return

        # 1. Stok geri ekle, satilan_adet geri düş
        for barkod, _, _, _, adet in islem["sepet"]:
            self.c.execute(
                "UPDATE Urunler SET "
                "satilan_adet = MAX(0, satilan_adet - ?), "
                "stok = stok + ? "
                "WHERE barkod=?",
                (adet, adet, barkod))

        # 2. Günlük ciro ve karı geri çıkar
        kar = islem["toplam_fiyat"] - islem["toplam_maliyet"]
        self.c.execute(
            "UPDATE Gunluk SET ciro = ciro - ?, kar = kar - ? WHERE id=1",
            (islem["toplam_fiyat"], kar))

        # 3. Veresiyeyse: kaydı geri al
        if islem["tip"] == "veresiye":
            v_id          = islem["veresiye_id"]
            detay_eklendi = islem["veresiye_detay_eklendi"]
            eski_tarih    = islem["veresiye_eski_tarih"]

            if eski_tarih is None:
                # Bu satış yeni bir müşteri kaydı açmıştı — kaydı tamamen sil
                self.c.execute("DELETE FROM Veresiye WHERE id=?", (v_id,))
            else:
                # Mevcut müşterinin kaydına eklenmiş satıştı — geri al
                self.c.execute(
                    "UPDATE Veresiye SET bakiye = bakiye - ?, tarih = ? WHERE id=?",
                    (islem["toplam_fiyat"], eski_tarih, v_id))

                # Detay satırını temizle
                self.c.execute("SELECT detay FROM Veresiye WHERE id=?", (v_id,))
                row = self.c.fetchone()
                if row and row[0]:
                    mevcut_detay = row[0]
                    if mevcut_detay == detay_eklendi:
                        yeni_detay = ""
                    elif mevcut_detay.startswith(detay_eklendi + " | "):
                        yeni_detay = mevcut_detay[len(detay_eklendi) + 3:]
                    else:
                        yeni_detay = mevcut_detay  # beklenmedik durum — dokunma
                    self.c.execute("UPDATE Veresiye SET detay=? WHERE id=?", (yeni_detay, v_id))

        self.conn.commit()

        # 4. İptal hakkını sıfırla — bu işlem bir daha iptal edilemesin
        self.son_islem = None

        # 5. Tüm ilgili ekranları yenile
        self.ozet_guncelle()
        self.urunleri_listele()
        self.veresiye_listele()

        # 6. Kullanıcıya kısa bilgi ver
        self.toplam_etiketi.configure(text="✅ Satış\niptal edildi!", text_color=RENK_SARI)
        self.after(2000, lambda: self.toplam_etiketi.configure(
            text=self.format_tl(self.toplam_fiyat), text_color=RENK_YESIL))

    def sepeti_temizle(self, tamamen=False):
        self.sepet.clear()
        self.sepet_gorunum.clear()
        self.toplam_fiyat   = 0
        self.toplam_maliyet = 0
        self._sepet_gorunumu_yenile(
            mesaj=None if tamamen else "--- İŞLEM İPTAL EDİLDİ ---")
        self.toplam_etiketi.configure(text=self.format_tl(0), text_color=RENK_YESIL)
        self._beklet_butonlari_guncelle()

    # =========================================================
    # 1b. MÜŞTERİYİ BEKLET (SATIŞI PARK ET)
    # =========================================================
    def _beklet_butonlari_guncelle(self):
        """Beklet butonu sepet doluyken, Bekleyenler butonu bekleyen varken aktif."""
        self.beklet_buton.configure(
            state="normal" if self.sepet else "disabled")
        n = len(self.bekleyen_satislar)
        self.bekleyenler_buton.configure(
            text=f"⏸ Bekleyenler ({n})",
            state="normal" if n > 0 else "disabled")

    def musteri_beklet(self):
        if not self.sepet:
            return

        pencere = ctk.CTkToplevel(self)
        pencere.title("Müşteriyi Beklet")
        pencere.geometry("380x220")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text="⏸ Satış Bekletiliyor",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_MAVI).pack(pady=(25, 5))
        ctk.CTkLabel(pencere, text="Etiket / not (boş bırakılabilir):",
                     font=(FONT_ANA, 13)).pack(pady=(5, 5))
        etiket_entry = ctk.CTkEntry(pencere, placeholder_text="örn. Ahmet, 2. masa...",
                                    font=(FONT_ANA, 14), justify="center", height=36)
        etiket_entry.pack(pady=5, padx=40, fill="x")
        etiket_entry.focus()

        def beklet():
            self.bekleyen_sayac += 1
            etiket = etiket_entry.get().strip() or f"Bekleyen #{self.bekleyen_sayac}"
            self.bekleyen_satislar[self.bekleyen_sayac] = {
                "sepet": list(self.sepet),            # kopya — referans değil
                "gorunum": list(self.sepet_gorunum),  # fiş satırları da geri gelsin
                "toplam_fiyat": self.toplam_fiyat,
                "toplam_maliyet": self.toplam_maliyet,
                "etiket": etiket,
                "zaman": datetime.now().strftime("%H:%M"),
            }
            pencere.destroy()
            # Ekranı sıfırla — DB'ye hiçbir şey yazılmıyor, satış commit edilmedi
            self.sepeti_temizle(tamamen=True)
            self.satis_barkod.focus()

        etiket_entry.bind("<Return>", lambda e: beklet())
        ctk.CTkButton(pencere, text="⏸ Beklet", fg_color=RENK_MAVI, hover_color="#2980b9",
                      font=(FONT_ANA, 14, "bold"), height=38,
                      command=beklet).pack(pady=15, padx=40, fill="x")

    def bekleyenler_popup(self):
        if not self.bekleyen_satislar:
            return

        pencere = ctk.CTkToplevel(self)
        pencere.title("Bekleyen Satışlar")
        pencere.geometry("480x420")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text="⏸ Bekleyen Satışlar",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_MAVI).pack(pady=(20, 5))
        liste_frame = ctk.CTkScrollableFrame(pencere, fg_color="#222")
        liste_frame.pack(fill="both", expand=True, padx=20, pady=5)
        uyari = ctk.CTkLabel(pencere, text="", font=(FONT_ANA, 12), text_color=RENK_KIRMIZI)
        uyari.pack(pady=(0, 10))

        def listeyi_ciz():
            for w in liste_frame.winfo_children():
                w.destroy()
            if not self.bekleyen_satislar:
                pencere.destroy()
                return
            for anahtar, kayit in self.bekleyen_satislar.items():
                satir = ctk.CTkFrame(liste_frame, fg_color="#333", corner_radius=8)
                satir.pack(fill="x", pady=3, padx=2)
                urun_adedi = sum(adet for _, _, _, _, adet in kayit["sepet"])
                bilgi = (f"{kayit['etiket']}  [{kayit['zaman']}]\n"
                         f"{urun_adedi} ürün — {self.format_tl(kayit['toplam_fiyat'])}")
                ctk.CTkLabel(satir, text=bilgi, font=(FONT_ANA, 13, "bold"),
                             justify="left", anchor="w").pack(side="left", padx=10, pady=8)
                ctk.CTkButton(satir, text="🗑️", width=35, height=28,
                              fg_color=RENK_KIRMIZI, hover_color="#c0392b",
                              command=lambda a=anahtar: beklet_iptal(a)).pack(
                                  side="right", padx=5)
                ctk.CTkButton(satir, text="▶️ Devam Et", width=95, height=28,
                              fg_color=RENK_YESIL, hover_color="#27ae60",
                              font=(FONT_ANA, 12, "bold"),
                              command=lambda a=anahtar: devam_et(a)).pack(
                                  side="right", padx=5)

        def devam_et(anahtar):
            if self.sepet:
                uyari.configure(
                    text="Mevcut sepetiniz var — önce onu bekletin ya da tamamlayın!")
                return
            kayit = self.bekleyen_satislar.pop(anahtar)
            # clear+extend: self.sepet liste nesnesi korunur, diğer referanslar bozulmaz
            self.sepet.clear()
            self.sepet.extend(kayit["sepet"])
            self.sepet_gorunum.clear()
            self.sepet_gorunum.extend(kayit["gorunum"])
            self.toplam_fiyat   = kayit["toplam_fiyat"]
            self.toplam_maliyet = kayit["toplam_maliyet"]
            self._sepet_gorunumu_yenile()
            self.toplam_etiketi.configure(text=self.format_tl(self.toplam_fiyat),
                                          text_color=RENK_YESIL)
            self._beklet_butonlari_guncelle()
            pencere.destroy()
            self.satis_barkod.focus()

        def beklet_iptal(anahtar):
            kayit = self.bekleyen_satislar[anahtar]
            onay = ctk.CTkToplevel(pencere)
            onay.title("Bekleyeni Sil")
            onay.geometry("380x160")
            onay.attributes("-topmost", True)
            onay.grab_set()
            ctk.CTkLabel(onay,
                         text=f"⚠️ '{kayit['etiket']}' bekleyen satışı silinecek.\n"
                              f"Bu işlem geri alınamaz, emin misiniz?",
                         font=(FONT_ANA, 14, "bold"), justify="center").pack(pady=(25, 10))
            btn_f = ctk.CTkFrame(onay, fg_color="transparent")
            btn_f.pack(pady=5, fill="x", padx=30)

            def sil():
                del self.bekleyen_satislar[anahtar]
                self._beklet_butonlari_guncelle()
                onay.destroy()
                pencere.grab_set()
                listeyi_ciz()

            ctk.CTkButton(btn_f, text="Evet, Sil", fg_color=RENK_KIRMIZI,
                          hover_color="#c0392b",
                          command=sil).pack(side="left", expand=True, padx=5)
            ctk.CTkButton(btn_f, text="Vazgeç", fg_color=RENK_PANEL, hover_color="#444",
                          command=lambda: (onay.destroy(), pencere.grab_set())).pack(
                              side="right", expand=True, padx=5)

        listeyi_ciz()

    # =========================================================
    # 2. ÜRÜN VE STOK YÖNETİMİ
    # =========================================================
    def urun_ekle_ekrani_kur(self):
        self.sekme_ekle.grid_columnconfigure(0, weight=1)
        self.sekme_ekle.grid_columnconfigure(1, weight=1)
        self.sekme_ekle.grid_rowconfigure(0, weight=1)

        sol_frame = ctk.CTkFrame(self.sekme_ekle, fg_color=RENK_PANEL, corner_radius=15)
        sol_frame.grid(row=0, column=0, padx=10, sticky="nsew")

        ust_kisim = ctk.CTkFrame(sol_frame, fg_color="transparent")
        ust_kisim.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(ust_kisim, text="📦 Kayıtlı Ürünler & Stok",
                     font=(FONT_ANA, 18, "bold")).pack(side="left")

        ctk.CTkButton(ust_kisim, text="🗂️ Grupları Yönet", width=130, height=30,
                      font=(FONT_ANA, 12, "bold"), fg_color="#555", hover_color="#777",
                      command=self.gruplari_yonet_popup).pack(side="right")

        self.toplu_geri_al_buton = ctk.CTkButton(
            ust_kisim, text="↩️ Fiyat Değişikliğini Geri Al", width=180, height=30,
            font=(FONT_ANA, 12, "bold"), fg_color="#555", hover_color="#777",
            state="disabled", command=self.toplu_fiyat_geri_al)
        self.toplu_geri_al_buton.pack(side="right", padx=(0, 8))

        filtre_frame = ctk.CTkFrame(sol_frame, fg_color="transparent")
        filtre_frame.pack(fill="x", padx=10, pady=(0, 5))

        self.arama_kutusu = ctk.CTkEntry(filtre_frame,
                                          placeholder_text="🔍 Ürün Ara (İsim veya Barkod)...",
                                          font=(FONT_ANA, 14), height=35)
        self.arama_kutusu.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._arama_timer = None
        self.arama_kutusu.bind("<KeyRelease>", self._arama_bekle)

        # Grup filtresi: arama ile AND mantığıyla birlikte çalışır
        self.grup_filtre_menu = ctk.CTkOptionMenu(filtre_frame, values=["Tümü"],
                                                   width=130, height=35,
                                                   font=(FONT_ANA, 13, "bold"),
                                                   fg_color="#555", button_color="#444",
                                                   command=lambda _: self.urunleri_listele())
        self.grup_filtre_menu.pack(side="right")
        self._grup_filtre_yenile()

        secim_frame = ctk.CTkFrame(sol_frame, fg_color="transparent")
        secim_frame.pack(fill="x", padx=10, pady=(0, 5))

        self.tumunu_sec_check = ctk.CTkCheckBox(secim_frame,
                                                 text="Tümünü Seç / Seçimi Kaldır",
                                                 font=(FONT_ANA, 12, "bold"),
                                                 fg_color=RENK_YESIL,
                                                 command=self._tumunu_sec_toggle)
        self.tumunu_sec_check.pack(side="left")

        self.secim_sayac_etiketi = ctk.CTkLabel(secim_frame, text="0 ürün seçili",
                                                 font=(FONT_ANA, 12), text_color="#aaa")
        self.secim_sayac_etiketi.pack(side="right")

        self.gruba_tasi_buton = ctk.CTkButton(secim_frame, text="📁 Seçilenleri Gruba Taşı",
                                               width=170, height=28,
                                               font=(FONT_ANA, 12, "bold"),
                                               fg_color=RENK_MAVI, hover_color="#2980b9",
                                               state="disabled",
                                               command=self.secilenleri_gruba_tasi_popup)
        self.gruba_tasi_buton.pack(side="right", padx=(0, 10))

        self.toplu_fiyat_buton = ctk.CTkButton(secim_frame, text="💰 Toplu Fiyat Değiştir",
                                                width=160, height=28,
                                                font=(FONT_ANA, 12, "bold"),
                                                fg_color=RENK_SARI, text_color="black",
                                                hover_color="#f39c12",
                                                state="disabled",
                                                command=self.toplu_fiyat_popup)
        self.toplu_fiyat_buton.pack(side="right", padx=(0, 10))

        self.urun_listesi_frame = ctk.CTkScrollableFrame(sol_frame, fg_color="transparent")
        self.urun_listesi_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.stok_toplam_etiketi = ctk.CTkLabel(sol_frame, text="Genel Depo Maliyeti: 0.00 ₺",
                                                 font=(FONT_ANA, 16, "bold"), text_color=RENK_SARI)
        self.stok_toplam_etiketi.pack(pady=10)

        sag_frame = ctk.CTkFrame(self.sekme_ekle, fg_color=RENK_PANEL, corner_radius=15)
        sag_frame.grid(row=0, column=1, padx=10, sticky="nsew")
        ctk.CTkLabel(sag_frame, text="✏️ Ürün Ekle / Güncelle",
                     font=(FONT_ANA, 18, "bold")).pack(pady=20)

        self.ekle_barkod = ctk.CTkEntry(sag_frame,
                                         placeholder_text="Barkod (Yoksa EKM1, CAY1 yaz)",
                                         height=40, font=(FONT_ANA, 14))
        self.ekle_barkod.pack(pady=5, padx=20, fill="x")
        self.ekle_barkod.bind("<Return>", self.urun_bilgisi_getir)

        self.ekle_isim = ctk.CTkEntry(sag_frame, placeholder_text="Ürün Adı",
                                       height=40, font=(FONT_ANA, 14))
        self.ekle_isim.pack(pady=5, padx=20, fill="x")

        fiyat_frame = ctk.CTkFrame(sag_frame, fg_color="transparent")
        fiyat_frame.pack(pady=5, fill="x", padx=20)
        self.ekle_alis  = ctk.CTkEntry(fiyat_frame, placeholder_text="Alış Fiyatı (₺)", width=120)
        self.ekle_alis.pack(side="left", padx=5)
        self.ekle_satis = ctk.CTkEntry(fiyat_frame, placeholder_text="Satış Fiyatı (₺)", width=120)
        self.ekle_satis.pack(side="right", padx=5)

        self.ekle_stok = ctk.CTkEntry(sag_frame, placeholder_text="Güncel Stok Adeti",
                                       height=40, font=(FONT_ANA, 14))
        self.ekle_stok.pack(pady=10, padx=20, fill="x")

        grup_frame = ctk.CTkFrame(sag_frame, fg_color="transparent")
        grup_frame.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(grup_frame, text="Grup:", font=(FONT_ANA, 14)).pack(side="left", padx=(0, 10))
        self.ekle_grup_menu = ctk.CTkOptionMenu(grup_frame, values=["Genel"],
                                                 font=(FONT_ANA, 13, "bold"), height=32)
        self.ekle_grup_menu.pack(side="left", fill="x", expand=True)
        self.ekle_grup_menu.set("Genel")
        self._grup_filtre_yenile()  # form menüsü artık var — güncel gruplarla doldur

        self.check_hizli = ctk.CTkCheckBox(sag_frame,
                                            text="Satış Ekranına Hızlı Tuş Olarak Ekle",
                                            font=(FONT_ANA, 14, "bold"), fg_color=RENK_YESIL)
        self.check_hizli.pack(pady=10, padx=20, anchor="w")

        self.kaydet_buton = ctk.CTkButton(sag_frame, text="💾 KAYDET",
                                           font=(FONT_ANA, 16, "bold"), height=45,
                                           fg_color=RENK_MAVI, command=self.urun_kaydet)
        self.kaydet_buton.pack(pady=20, padx=20, fill="x")

        self.durum_etiketi = ctk.CTkLabel(sag_frame, text="", font=(FONT_ANA, 12))
        self.durum_etiketi.pack()

    def genel_depo_maliyeti_guncelle(self):
        self.c.execute("SELECT SUM(stok * alis) FROM Urunler WHERE stok > 0")
        veri = self.c.fetchone()
        depo_maliyet = veri[0] if veri[0] else 0
        self.stok_toplam_etiketi.configure(
            text=f"Genel Depo Maliyeti (Toplam Yatan Para): {self.format_tl(depo_maliyet)}")

    def _arama_bekle(self, event=None):
        """Debounce: son tuşa basıştan 350ms sonra aramayı tetikler."""
        if self._arama_timer is not None:
            self.after_cancel(self._arama_timer)
        self._arama_timer = self.after(350, self.urunleri_listele)

    def urunleri_listele(self, event=None):
        for widget in self.urun_listesi_frame.winfo_children():
            widget.destroy()

        arama_metni = self.arama_kutusu.get().strip()
        secili_grup = self.grup_filtre_menu.get()

        # Grup ve arama filtreleri AND mantığıyla birleşir
        kosullar, params = [], []
        if arama_metni:
            kosullar.append("(isim LIKE ? OR barkod LIKE ?)")
            params += ['%' + arama_metni + '%', '%' + arama_metni + '%']
        if secili_grup != "Tümü":
            kosullar.append("grup_id = (SELECT id FROM Gruplar WHERE isim=?)")
            params.append(secili_grup)

        where = ("WHERE " + " AND ".join(kosullar)) if kosullar else ""
        # Arama varsa alfabetik (kullanıcı ürün arıyor), yoksa stok ASC (azalan stok üstte)
        siralama = "isim ASC" if arama_metni else "stok ASC, isim ASC"

        self.c.execute(
            f"SELECT barkod, isim, alis, satis, stok, hizli FROM Urunler "
            f"{where} ORDER BY {siralama} LIMIT 60", params)

        satirlar = self.c.fetchall()
        # Ekranda görünen barkodlar — "Tümünü Seç" yalnızca bunları etkiler
        self._gorunen_barkodlar = [s[0] for s in satirlar]

        # Master checkbox: görünenlerin hepsi seçiliyse işaretli görünsün
        if self._gorunen_barkodlar and all(
                b in self.secili_urunler for b in self._gorunen_barkodlar):
            self.tumunu_sec_check.select()
        else:
            self.tumunu_sec_check.deselect()

        self._secim_sayaci_guncelle()
        self.genel_depo_maliyeti_guncelle()
        self._urun_satirlari_ciz(satirlar, 0)

    def _grup_filtre_yenile(self):
        """Grup filtresi ve formdaki grup menüsünü DB'deki güncel gruplarla doldurur."""
        self.c.execute("SELECT isim FROM Gruplar ORDER BY isim ASC")
        grup_isimleri = [r[0] for r in self.c.fetchall()]

        isimler = ["Tümü"] + grup_isimleri
        mevcut_secim = self.grup_filtre_menu.get()
        self.grup_filtre_menu.configure(values=isimler)
        if mevcut_secim not in isimler:  # seçili grup silinmiş/adı değişmişse
            self.grup_filtre_menu.set("Tümü")

        # Ürün formundaki grup menüsü (form filtre menüsünden sonra kurulur — guard)
        if hasattr(self, "ekle_grup_menu"):
            form_secim = self.ekle_grup_menu.get()
            self.ekle_grup_menu.configure(values=grup_isimleri)
            if form_secim not in grup_isimleri:
                self.ekle_grup_menu.set("Genel")

    def _secim_sayaci_guncelle(self):
        adet = len(self.secili_urunler)
        self.secim_sayac_etiketi.configure(text=f"{adet} ürün seçili")
        # Seçim varsa toplu işlem butonları aktifleşir
        durum = "normal" if adet > 0 else "disabled"
        self.gruba_tasi_buton.configure(state=durum)
        self.toplu_fiyat_buton.configure(state=durum)

    def _urun_secim_toggle(self, barkod):
        """Satır checkbox'ı değişince seti güncelle."""
        if barkod in self.secili_urunler:
            self.secili_urunler.discard(barkod)
            self.tumunu_sec_check.deselect()
        else:
            self.secili_urunler.add(barkod)
            if all(b in self.secili_urunler for b in self._gorunen_barkodlar):
                self.tumunu_sec_check.select()
        self._secim_sayaci_guncelle()

    def _tumunu_sec_toggle(self):
        """Yalnızca EKRANDA GÖRÜNEN (filtrelenmiş) ürünleri seçer/bırakır."""
        if self.tumunu_sec_check.get() == 1:
            self.secili_urunler.update(self._gorunen_barkodlar)
        else:
            self.secili_urunler.difference_update(self._gorunen_barkodlar)
        self.urunleri_listele()  # satır checkbox'ları yeni duruma göre yeniden çizilir

    def _urun_satirlari_ciz(self, satirlar, baslangic, chunk=10):
        """Ürün satırlarını 10'ar 10'ar çizerek UI'ın nefes almasını sağlar."""
        bitis = min(baslangic + chunk, len(satirlar))
        for barkod, isim, alis, satis, stok, hizli in satirlar[baslangic:bitis]:
            satir = ctk.CTkFrame(self.urun_listesi_frame, fg_color="#222", corner_radius=8)
            satir.pack(fill="x", pady=3, padx=2)

            stok_renk  = RENK_KIRMIZI if stok < 5 else "#aaa"
            hizli_ikon = "⚡ " if hizli == 1 else ""
            urun_maliyet_toplam = stok * alis  # kuruş

            chk = ctk.CTkCheckBox(satir, text="", width=24, checkbox_width=20,
                                  checkbox_height=20, fg_color=RENK_YESIL,
                                  command=lambda b=barkod: self._urun_secim_toggle(b))
            if barkod in self.secili_urunler:
                chk.select()
            chk.pack(side="left", padx=(5, 0), pady=8)

            ctk.CTkLabel(satir, text=f"{hizli_ikon}{isim}",
                         font=(FONT_ANA, 14, "bold"), width=150, anchor="w").pack(side="left", padx=5, pady=8)

            lbl_stok = ctk.CTkLabel(satir, text=f"Stok: {stok}",
                                     text_color=stok_renk, font=(FONT_ANA, 12, "bold"))
            lbl_stok.pack(side="left", padx=5)

            lbl_maliyet = ctk.CTkLabel(satir,
                                        text=f"Maliyet: {self.format_tl(urun_maliyet_toplam)}",
                                        text_color=RENK_SARI, font=(FONT_ANA, 12, "bold"))
            lbl_maliyet.pack(side="left", padx=10)

            ctk.CTkButton(satir, text="Sil", width=40, height=25, fg_color=RENK_KIRMIZI,
                          command=lambda b=barkod, sf=satir: self.urun_sil(b, sf)).pack(side="right", padx=5)
            ctk.CTkButton(satir, text="📦 Stok", width=55, height=25, fg_color=RENK_MAVI,
                          command=lambda b=barkod, n=isim, a=alis, ls=lbl_stok, lm=lbl_maliyet:
                              self.stok_guncelle_popup(b, n, a, ls, lm)).pack(side="right", padx=5)

        if bitis < len(satirlar):
            self.after(10, lambda: self._urun_satirlari_ciz(satirlar, bitis, chunk))

    def stok_guncelle_popup(self, barkod, isim, alis_fiyati, lbl_stok, lbl_maliyet):
        # alis_fiyati kuruş cinsinden integer
        self.c.execute("SELECT stok FROM Urunler WHERE barkod=?", (barkod,))
        mevcut_stok = self.c.fetchone()[0]

        pencere = ctk.CTkToplevel(self)
        pencere.title("Stok İşlemi")
        pencere.geometry("350x250")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text=f"{isim}",
                     font=(FONT_ANA, 20, "bold"), text_color=RENK_MAVI).pack(pady=(20, 5))
        ctk.CTkLabel(pencere, text=f"Mevcut Stok: {mevcut_stok} Adet",
                     font=(FONT_ANA, 16)).pack(pady=(0, 15))

        miktar_entry = ctk.CTkEntry(pencere, placeholder_text="Eklenecek/Düşülecek Adet",
                                    font=(FONT_ANA, 14), justify="center")
        miktar_entry.pack(pady=10, padx=30, fill="x")
        miktar_entry.focus()

        uyari_etiket = ctk.CTkLabel(pencere, text="", font=(FONT_ANA, 12), text_color=RENK_KIRMIZI)
        uyari_etiket.pack()

        btn_frame = ctk.CTkFrame(pencere, fg_color="transparent")
        btn_frame.pack(pady=10, fill="x", padx=20)

        def islem_yap(islem_tipi):
            girilen = miktar_entry.get().strip()
            if not girilen:
                uyari_etiket.configure(text="Lütfen bir miktar girin!")
                return
            try:
                miktar = int(girilen)
                if miktar <= 0:
                    uyari_etiket.configure(text="Miktar sıfırdan büyük olmalı!")
                    return

                if islem_tipi == "ekle":
                    yeni_stok = mevcut_stok + miktar
                else:
                    yeni_stok = max(0, mevcut_stok - miktar)

                self.c.execute("UPDATE Urunler SET stok = ? WHERE barkod = ?", (yeni_stok, barkod))
                self.conn.commit()

                stok_renk = RENK_KIRMIZI if yeni_stok < 5 else "#aaa"
                lbl_stok.configure(text=f"Stok: {yeni_stok}", text_color=stok_renk)
                lbl_maliyet.configure(text=f"Maliyet: {self.format_tl(yeni_stok * alis_fiyati)}")
                self.genel_depo_maliyeti_guncelle()
                pencere.destroy()
            except ValueError:
                uyari_etiket.configure(text="Geçersiz değer! Sadece tam sayı girin.")

        ctk.CTkButton(btn_frame, text="Stok Düş (-)", fg_color=RENK_KIRMIZI,
                      hover_color="#c0392b",
                      command=lambda: islem_yap("cikar")).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Stok Ekle (+)", fg_color=RENK_YESIL,
                      hover_color="#27ae60",
                      command=lambda: islem_yap("ekle")).pack(side="right", expand=True, padx=5)

    def urun_sil(self, barkod, satir_frame):
        self.c.execute("DELETE FROM Urunler WHERE barkod=?", (barkod,))
        self.conn.commit()
        satir_frame.destroy()
        self.secili_urunler.discard(barkod)  # silinen ürün seçimde kalmasın
        self._secim_sayaci_guncelle()
        self.genel_depo_maliyeti_guncelle()
        self.hizli_tuslari_yukle()

    def urun_bilgisi_getir(self, event):
        barkod = self.ekle_barkod.get()
        for entry in (self.ekle_isim, self.ekle_alis, self.ekle_satis, self.ekle_stok):
            entry.delete(0, "end")

        self.c.execute(
            "SELECT u.isim, u.alis, u.satis, u.stok, u.hizli, g.isim "
            "FROM Urunler u LEFT JOIN Gruplar g ON g.id = u.grup_id "
            "WHERE u.barkod=?", (barkod,))
        urun = self.c.fetchone()
        if urun:
            isim, alis, satis, stok, hizli, grup_isim = urun  # alis, satis kuruş
            self.ses_cikar("ok")
            self.ekle_isim.insert(0, isim)
            self.ekle_alis.insert(0, f"{alis / 100:.2f}")   # kuruşu TL'ye çevirerek göster
            self.ekle_satis.insert(0, f"{satis / 100:.2f}") # kuruşu TL'ye çevirerek göster
            self.ekle_stok.insert(0, str(stok))
            self.ekle_grup_menu.set(grup_isim if grup_isim else "Genel")
            if hizli == 1:
                self.check_hizli.select()
            else:
                self.check_hizli.deselect()
            self.durum_etiketi.configure(text="Ürün Bulundu!", text_color=RENK_SARI)
            self.ekle_satis.focus()
        else:
            self.ses_cikar("hata")
            self.check_hizli.deselect()
            self.ekle_grup_menu.set("Genel")
            self.durum_etiketi.configure(text="Yeni Ürün!", text_color=RENK_MAVI)
            self.ekle_isim.focus()

    def urun_kaydet(self):
        barkod = self.ekle_barkod.get().strip()
        isim   = self.ekle_isim.get().strip()

        if not barkod or not isim:
            self.durum_etiketi.configure(text="Hata: Barkod ve ürün adı boş bırakılamaz!",
                                          text_color=RENK_KIRMIZI)
            return

        hizli_mi = 1 if self.check_hizli.get() == 1 else 0
        try:
            alis  = self._para_parse(self.ekle_alis.get())   # TL → kuruş
            satis = self._para_parse(self.ekle_satis.get())  # TL → kuruş
            stok  = int(self.ekle_stok.get()) if self.ekle_stok.get().strip() else 0

            # grup_id formdaki seçimden gelir; isim bulunamazsa Genel'e düşer
            secili_grup = self.ekle_grup_menu.get()
            self.c.execute(
                "INSERT OR REPLACE INTO Urunler "
                "(barkod, isim, alis, satis, satilan_adet, stok, hizli, grup_id) "
                "VALUES (?, ?, ?, ?, "
                "COALESCE((SELECT satilan_adet FROM Urunler WHERE barkod=?), 0), ?, ?, "
                "COALESCE((SELECT id FROM Gruplar WHERE isim=?), "
                "         (SELECT id FROM Gruplar WHERE isim='Genel')))",
                (barkod, isim, alis, satis, barkod, stok, hizli_mi, secili_grup))
            self.conn.commit()
            self.durum_etiketi.configure(text="Kaydedildi!", text_color=RENK_YESIL)
            self.urunleri_listele()
            self.hizli_tuslari_yukle()

            for entry in (self.ekle_barkod, self.ekle_isim, self.ekle_alis,
                          self.ekle_satis, self.ekle_stok):
                entry.delete(0, "end")
            self.check_hizli.deselect()
            self.ekle_grup_menu.set("Genel")
            self.ekle_barkod.focus()
        except ValueError:
            self.durum_etiketi.configure(
                text="Hata: Alış, satış ve stok sayısal değer olmalı!",
                text_color=RENK_KIRMIZI)

    # =========================================================
    # 2b. GRUP YÖNETİMİ
    # =========================================================
    def secilenleri_gruba_tasi_popup(self):
        if not self.secili_urunler:
            return

        pencere = ctk.CTkToplevel(self)
        pencere.title("Gruba Taşı")
        pencere.geometry("380x240")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        adet = len(self.secili_urunler)
        ctk.CTkLabel(pencere, text=f"📁 {adet} ürün taşınacak",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_MAVI).pack(pady=(25, 5))
        ctk.CTkLabel(pencere, text="Hedef grubu seçin:",
                     font=(FONT_ANA, 14)).pack(pady=(5, 5))

        self.c.execute("SELECT isim FROM Gruplar ORDER BY isim ASC")
        grup_isimleri = [r[0] for r in self.c.fetchall()]
        hedef_menu = ctk.CTkOptionMenu(pencere, values=grup_isimleri,
                                       font=(FONT_ANA, 14, "bold"), height=35)
        hedef_menu.pack(pady=5, padx=40, fill="x")

        def tasi():
            hedef = hedef_menu.get()
            barkodlar = list(self.secili_urunler)
            yer_tutucular = ",".join("?" * len(barkodlar))
            self.c.execute(
                f"UPDATE Urunler SET grup_id = (SELECT id FROM Gruplar WHERE isim=?) "
                f"WHERE barkod IN ({yer_tutucular})",
                [hedef] + barkodlar)
            self.conn.commit()
            self.secili_urunler.clear()
            pencere.destroy()
            self.urunleri_listele()
            self.durum_etiketi.configure(
                text=f"{adet} ürün '{hedef}' grubuna taşındı.", text_color=RENK_YESIL)

        btn_frame = ctk.CTkFrame(pencere, fg_color="transparent")
        btn_frame.pack(pady=20, fill="x", padx=40)
        ctk.CTkButton(btn_frame, text="Taşı", fg_color=RENK_YESIL, hover_color="#27ae60",
                      font=(FONT_ANA, 14, "bold"),
                      command=tasi).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Vazgeç", fg_color=RENK_PANEL, hover_color="#444",
                      font=(FONT_ANA, 14, "bold"),
                      command=pencere.destroy).pack(side="right", expand=True, padx=5)

    # =========================================================
    # 2c. TOPLU FİYAT DEĞİŞTİRME
    # =========================================================
    def toplu_fiyat_popup(self):
        if not self.secili_urunler:
            return

        barkodlar = list(self.secili_urunler)
        yer_tutucular = ",".join("?" * len(barkodlar))
        self.c.execute(
            f"SELECT barkod, isim, alis, satis FROM Urunler "
            f"WHERE barkod IN ({yer_tutucular}) ORDER BY isim ASC", barkodlar)
        urunler = self.c.fetchall()  # (barkod, isim, alis_kurus, satis_kurus)

        pencere = ctk.CTkToplevel(self)
        pencere.title("Toplu Fiyat Değiştir")
        pencere.geometry("480x640")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text=f"💰 {len(urunler)} ürünün fiyatı değişecek",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_SARI).pack(pady=(20, 10))

        # --- Hangi alanlar ---
        alan_frame = ctk.CTkFrame(pencere, fg_color="#222", corner_radius=10)
        alan_frame.pack(fill="x", padx=25, pady=5)
        ctk.CTkLabel(alan_frame, text="Uygulanacak Alan(lar):",
                     font=(FONT_ANA, 13, "bold")).pack(anchor="w", padx=15, pady=(10, 0))
        chk_satis = ctk.CTkCheckBox(alan_frame, text="Satış Fiyatı",
                                    font=(FONT_ANA, 13), fg_color=RENK_YESIL)
        chk_satis.select()
        chk_satis.pack(side="left", padx=15, pady=10)
        chk_alis = ctk.CTkCheckBox(alan_frame, text="Maliyet (Alış) Fiyatı",
                                   font=(FONT_ANA, 13), fg_color=RENK_YESIL)
        chk_alis.pack(side="left", padx=15, pady=10)

        # --- Değişim tipi ve yön ---
        tip_var = ctk.StringVar(value="yuzde")
        yon_var = ctk.StringVar(value="artir")

        tip_frame = ctk.CTkFrame(pencere, fg_color="#222", corner_radius=10)
        tip_frame.pack(fill="x", padx=25, pady=5)
        ctk.CTkLabel(tip_frame, text="Değişim Tipi:",
                     font=(FONT_ANA, 13, "bold")).pack(anchor="w", padx=15, pady=(10, 0))
        ctk.CTkRadioButton(tip_frame, text="Yüzde (%)", variable=tip_var, value="yuzde",
                           font=(FONT_ANA, 13)).pack(side="left", padx=15, pady=10)
        ctk.CTkRadioButton(tip_frame, text="Sabit Tutar (₺)", variable=tip_var, value="tl",
                           font=(FONT_ANA, 13)).pack(side="left", padx=15, pady=10)

        yon_frame = ctk.CTkFrame(pencere, fg_color="#222", corner_radius=10)
        yon_frame.pack(fill="x", padx=25, pady=5)
        ctk.CTkLabel(yon_frame, text="Yön:",
                     font=(FONT_ANA, 13, "bold")).pack(anchor="w", padx=15, pady=(10, 0))
        ctk.CTkRadioButton(yon_frame, text="Artır (+)", variable=yon_var, value="artir",
                           font=(FONT_ANA, 13)).pack(side="left", padx=15, pady=10)
        ctk.CTkRadioButton(yon_frame, text="Azalt (−)", variable=yon_var, value="azalt",
                           font=(FONT_ANA, 13)).pack(side="left", padx=15, pady=10)

        # --- Değer girişi ---
        deger_entry = ctk.CTkEntry(pencere, placeholder_text="Değer (örn. 10 veya 5,50)",
                                   font=(FONT_ANA, 15), height=38, justify="center")
        deger_entry.pack(fill="x", padx=25, pady=(10, 5))
        deger_entry.focus()

        uyari = ctk.CTkLabel(pencere, text="", font=(FONT_ANA, 12), text_color=RENK_KIRMIZI)
        uyari.pack()

        # --- Önizleme ---
        ctk.CTkLabel(pencere, text="Önizleme (ilk 5 ürün):",
                     font=(FONT_ANA, 13, "bold")).pack(anchor="w", padx=25, pady=(5, 0))
        onizleme = ctk.CTkTextbox(pencere, height=130, font=("Consolas", 12), fg_color="#1a1a1a")
        onizleme.pack(fill="x", padx=25, pady=5)
        onizleme.configure(state="disabled")

        def deger_oku():
            """Girilen değeri doğrular. Dönüş: yüzdeyse float, TL'yse kuruş int; hatada None."""
            metin = deger_entry.get().strip().replace("%", "").replace("₺", "")
            if not metin:
                return None
            try:
                if tip_var.get() == "yuzde":
                    deger = float(metin.replace(",", "."))
                else:
                    deger = self._para_parse(metin)
                return deger if deger > 0 else None
            except ValueError:
                return None

        def hesapla(eski_kurus, deger):
            """Yeni fiyatı hesaplar; 0 altına düşerse 0'da sınırlar. Dönüş: (yeni, sifirlandi_mi)"""
            if tip_var.get() == "yuzde":
                carpan = 1 + deger / 100 if yon_var.get() == "artir" else 1 - deger / 100
                yeni = int(round(eski_kurus * carpan))
            else:
                yeni = eski_kurus + deger if yon_var.get() == "artir" else eski_kurus - deger
            if yeni < 0:
                return 0, True
            return yeni, False

        def onizleme_guncelle(*_):
            onizleme.configure(state="normal")
            onizleme.delete("1.0", "end")
            deger = deger_oku()
            if deger is None:
                onizleme.insert("end", "Geçerli bir değer girin...")
            elif chk_satis.get() == 0 and chk_alis.get() == 0:
                onizleme.insert("end", "En az bir alan seçin (Satış / Alış)...")
            else:
                for _, isim, alis, satis in urunler[:5]:
                    parcalar = [f"{isim[:14]:<14}"]
                    if chk_satis.get() == 1:
                        yeni_s, _sfr = hesapla(satis, deger)
                        parcalar.append(f"S: {satis/100:.2f}→{yeni_s/100:.2f}")
                    if chk_alis.get() == 1:
                        yeni_a, _sfr = hesapla(alis, deger)
                        parcalar.append(f"A: {alis/100:.2f}→{yeni_a/100:.2f}")
                    onizleme.insert("end", "  ".join(parcalar) + "\n")
            onizleme.configure(state="disabled")

        deger_entry.bind("<KeyRelease>", onizleme_guncelle)
        chk_satis.configure(command=onizleme_guncelle)
        chk_alis.configure(command=onizleme_guncelle)
        for rb_var in (tip_var, yon_var):
            rb_var.trace_add("write", onizleme_guncelle)
        onizleme_guncelle()

        def uygula():
            deger = deger_oku()
            if deger is None:
                uyari.configure(text="Geçerli bir pozitif değer girin!")
                return
            if chk_satis.get() == 0 and chk_alis.get() == 0:
                uyari.configure(text="En az bir alan seçmelisin (Satış / Alış)!")
                return

            alanlar = []
            if chk_satis.get() == 1:
                alanlar.append("satış")
            if chk_alis.get() == 1:
                alanlar.append("alış")
            alan_str = " ve ".join(alanlar)
            yon_str = "artırılacak" if yon_var.get() == "artir" else "azaltılacak"
            deger_str = (f"%{deger:g}" if tip_var.get() == "yuzde"
                         else self.format_tl(deger))

            onay = ctk.CTkToplevel(pencere)
            onay.title("Onay")
            onay.geometry("400x170")
            onay.attributes("-topmost", True)
            onay.grab_set()
            ctk.CTkLabel(onay,
                         text=f"⚠️ {len(urunler)} ürünün {alan_str} fiyatı\n"
                              f"{deger_str} {yon_str}. Emin misin?",
                         font=(FONT_ANA, 14, "bold"), justify="center").pack(pady=(25, 10))
            btn_f = ctk.CTkFrame(onay, fg_color="transparent")
            btn_f.pack(pady=10, fill="x", padx=30)

            def onaylandi():
                # Geri alma için eski değerleri sakla — yeni bir toplu değişiklik
                # yapılırsa üzerine yazılır (tek seviyeli undo)
                self.son_toplu_degisiklik = [
                    (alis, satis, barkod) for barkod, _, alis, satis in urunler]
                self.toplu_geri_al_buton.configure(state="normal")

                guncellemeler = []  # (yeni_alis, yeni_satis, barkod)
                sifirlanan = 0
                for barkod, _, alis, satis in urunler:
                    yeni_alis, yeni_satis = alis, satis
                    if chk_alis.get() == 1:
                        yeni_alis, sfr = hesapla(alis, deger)
                        sifirlanan += 1 if sfr else 0
                    if chk_satis.get() == 1:
                        yeni_satis, sfr = hesapla(satis, deger)
                        sifirlanan += 1 if sfr else 0
                    guncellemeler.append((yeni_alis, yeni_satis, barkod))

                self.c.executemany(
                    "UPDATE Urunler SET alis=?, satis=? WHERE barkod=?", guncellemeler)
                self.conn.commit()

                self.secili_urunler.clear()
                onay.destroy()
                pencere.destroy()
                self.urunleri_listele()
                self.hizli_tuslari_yukle()  # hızlı tuşlar satış fiyatını gösteriyor

                mesaj = f"{len(urunler)} ürünün fiyatı güncellendi."
                if sifirlanan:
                    mesaj += f" ({sifirlanan} fiyat 0'a sabitlendi!)"
                self.durum_etiketi.configure(text=mesaj, text_color=RENK_YESIL)

            ctk.CTkButton(btn_f, text="Evet, Uygula", fg_color=RENK_KIRMIZI,
                          hover_color="#c0392b",
                          command=onaylandi).pack(side="left", expand=True, padx=5)
            ctk.CTkButton(btn_f, text="Vazgeç", fg_color=RENK_PANEL, hover_color="#444",
                          command=lambda: (onay.destroy(), pencere.grab_set())).pack(
                              side="right", expand=True, padx=5)

        btn_frame = ctk.CTkFrame(pencere, fg_color="transparent")
        btn_frame.pack(pady=15, fill="x", padx=25)
        ctk.CTkButton(btn_frame, text="✅ UYGULA", fg_color=RENK_YESIL, hover_color="#27ae60",
                      font=(FONT_ANA, 15, "bold"), height=42,
                      command=uygula).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Vazgeç", fg_color=RENK_PANEL, hover_color="#444",
                      font=(FONT_ANA, 15, "bold"), height=42,
                      command=pencere.destroy).pack(side="right", expand=True, padx=5)

    def toplu_fiyat_geri_al(self):
        """Son toplu fiyat değişikliğini birebir geri yazar (tek seviyeli undo)."""
        if not self.son_toplu_degisiklik:
            return

        adet = len(self.son_toplu_degisiklik)

        pencere = ctk.CTkToplevel(self)
        pencere.title("Toplu Değişikliği Geri Al")
        pencere.geometry("400x170")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere,
                     text=f"↩️ {adet} ürünün alış/satış fiyatı\n"
                          f"değişiklik öncesi değerlerine dönecek. Emin misin?",
                     font=(FONT_ANA, 14, "bold"), justify="center").pack(pady=(25, 10))
        btn_f = ctk.CTkFrame(pencere, fg_color="transparent")
        btn_f.pack(pady=10, fill="x", padx=30)

        def geri_al():
            # Kaydedilen (eski_alis, eski_satis, barkod) üçlüleri birebir geri yazılır;
            # bu arada silinmiş ürünler için UPDATE sessizce atlanır
            self.c.executemany(
                "UPDATE Urunler SET alis=?, satis=? WHERE barkod=?",
                self.son_toplu_degisiklik)
            self.conn.commit()

            self.son_toplu_degisiklik = None  # tek seviyeli undo — hak kullanıldı
            self.toplu_geri_al_buton.configure(state="disabled")

            pencere.destroy()
            self.urunleri_listele()
            self.hizli_tuslari_yukle()
            self.durum_etiketi.configure(
                text=f"{adet} ürünün fiyatı geri alındı.", text_color=RENK_YESIL)

        ctk.CTkButton(btn_f, text="Evet, Geri Al", fg_color=RENK_KIRMIZI,
                      hover_color="#c0392b",
                      command=geri_al).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_f, text="Vazgeç", fg_color=RENK_PANEL, hover_color="#444",
                      command=pencere.destroy).pack(side="right", expand=True, padx=5)

    def gruplari_yonet_popup(self):
        pencere = ctk.CTkToplevel(self)
        pencere.title("Grup Yönetimi")
        pencere.geometry("440x540")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text="🗂️ Ürün Grupları",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_MAVI).pack(pady=(20, 5))

        liste_frame = ctk.CTkScrollableFrame(pencere, fg_color="#222")
        liste_frame.pack(fill="both", expand=True, padx=20, pady=5)

        durum = ctk.CTkLabel(pencere, text="", font=(FONT_ANA, 12))
        durum.pack()

        ekle_frame = ctk.CTkFrame(pencere, fg_color="transparent")
        ekle_frame.pack(fill="x", padx=20, pady=(5, 15))
        yeni_grup_entry = ctk.CTkEntry(ekle_frame, placeholder_text="Yeni Grup Adı",
                                       font=(FONT_ANA, 14), height=35)
        yeni_grup_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def listeyi_yenile():
            # Grup ekleme/silme/rename sonrası ana ekrandaki filtre menüsü de güncellensin
            self._grup_filtre_yenile()
            self.urunleri_listele()
            for w in liste_frame.winfo_children():
                w.destroy()
            self.c.execute(
                "SELECT g.id, g.isim, COUNT(u.barkod) FROM Gruplar g "
                "LEFT JOIN Urunler u ON u.grup_id = g.id "
                "GROUP BY g.id, g.isim ORDER BY g.isim ASC")
            for g_id, g_isim, urun_sayisi in self.c.fetchall():
                satir = ctk.CTkFrame(liste_frame, fg_color="#333", corner_radius=8)
                satir.pack(fill="x", pady=3, padx=2)
                ctk.CTkLabel(satir, text=f"{g_isim}  ({urun_sayisi} ürün)",
                             font=(FONT_ANA, 14, "bold"), anchor="w").pack(side="left", padx=10, pady=8)
                if g_isim == "Genel":
                    # Genel: varsayılan grup — silinemez ve yeniden adlandırılamaz,
                    # çünkü silme/kayıt akışları 'Genel' ismine dayanıyor
                    ctk.CTkLabel(satir, text="🔒 Varsayılan", font=(FONT_ANA, 12),
                                 text_color="#888").pack(side="right", padx=10)
                else:
                    ctk.CTkButton(satir, text="🗑️", width=35, height=25, fg_color=RENK_KIRMIZI,
                                  hover_color="#c0392b",
                                  command=lambda i=g_id, n=g_isim, s=urun_sayisi:
                                      grup_sil(i, n, s)).pack(side="right", padx=5)
                    ctk.CTkButton(satir, text="✏️", width=35, height=25, fg_color=RENK_MAVI,
                                  hover_color="#2980b9",
                                  command=lambda i=g_id, n=g_isim:
                                      grup_adlandir(i, n)).pack(side="right", padx=5)

        def grup_ekle():
            isim = yeni_grup_entry.get().strip()
            if not isim:
                durum.configure(text="Grup adı boş olamaz!", text_color=RENK_KIRMIZI)
                return
            try:
                self.c.execute("INSERT INTO Gruplar (isim) VALUES (?)", (isim,))
                self.conn.commit()
                yeni_grup_entry.delete(0, "end")
                durum.configure(text=f"'{isim}' grubu eklendi.", text_color=RENK_YESIL)
                listeyi_yenile()
            except sqlite3.IntegrityError:
                durum.configure(text="Bu isimde bir grup zaten var!", text_color=RENK_KIRMIZI)

        def grup_sil(g_id, g_isim, urun_sayisi):
            def sil_uygula():
                if urun_sayisi > 0:
                    self.c.execute(
                        "UPDATE Urunler SET grup_id = (SELECT id FROM Gruplar WHERE isim='Genel') "
                        "WHERE grup_id = ?", (g_id,))
                self.c.execute("DELETE FROM Gruplar WHERE id=?", (g_id,))
                self.conn.commit()
                durum.configure(text=f"'{g_isim}' grubu silindi.", text_color=RENK_YESIL)
                listeyi_yenile()

            if urun_sayisi == 0:
                sil_uygula()
                return

            onay = ctk.CTkToplevel(pencere)
            onay.title("Grubu Sil")
            onay.geometry("380x180")
            onay.attributes("-topmost", True)
            onay.grab_set()
            ctk.CTkLabel(onay, text=f"⚠️ '{g_isim}' grubunda {urun_sayisi} ürün var.\n"
                                    f"Silersen bu ürünler 'Genel' grubuna taşınacak.",
                         font=(FONT_ANA, 14), justify="center").pack(pady=(25, 10), padx=20)
            btn_f = ctk.CTkFrame(onay, fg_color="transparent")
            btn_f.pack(pady=10, fill="x", padx=30)

            def onayla_ve_kapat():
                sil_uygula()
                onay.destroy()
                pencere.grab_set()  # grab üst pencereye geri dönsün

            ctk.CTkButton(btn_f, text="Evet, Sil", fg_color=RENK_KIRMIZI, hover_color="#c0392b",
                          command=onayla_ve_kapat).pack(side="left", expand=True, padx=5)
            ctk.CTkButton(btn_f, text="Vazgeç", fg_color=RENK_PANEL, hover_color="#444",
                          command=lambda: (onay.destroy(), pencere.grab_set())).pack(
                              side="right", expand=True, padx=5)

        def grup_adlandir(g_id, eski_isim):
            adlandir = ctk.CTkToplevel(pencere)
            adlandir.title("Grup Adını Değiştir")
            adlandir.geometry("360x180")
            adlandir.attributes("-topmost", True)
            adlandir.grab_set()
            ctk.CTkLabel(adlandir, text=f"'{eski_isim}' için yeni ad:",
                         font=(FONT_ANA, 14, "bold")).pack(pady=(25, 5))
            ad_entry = ctk.CTkEntry(adlandir, font=(FONT_ANA, 14), justify="center")
            ad_entry.insert(0, eski_isim)
            ad_entry.pack(pady=5, padx=30, fill="x")
            ad_entry.focus()
            ad_uyari = ctk.CTkLabel(adlandir, text="", font=(FONT_ANA, 12), text_color=RENK_KIRMIZI)
            ad_uyari.pack()

            def kaydet():
                yeni_isim = ad_entry.get().strip()
                if not yeni_isim:
                    ad_uyari.configure(text="Grup adı boş olamaz!")
                    return
                try:
                    self.c.execute("UPDATE Gruplar SET isim=? WHERE id=?", (yeni_isim, g_id))
                    self.conn.commit()
                    adlandir.destroy()
                    pencere.grab_set()
                    durum.configure(text=f"'{eski_isim}' → '{yeni_isim}' olarak değiştirildi.",
                                    text_color=RENK_YESIL)
                    listeyi_yenile()
                except sqlite3.IntegrityError:
                    ad_uyari.configure(text="Bu isimde bir grup zaten var!")

            ad_entry.bind("<Return>", lambda e: kaydet())
            ctk.CTkButton(adlandir, text="Kaydet", fg_color=RENK_YESIL, hover_color="#27ae60",
                          command=kaydet).pack(pady=10, padx=30, fill="x")

        ctk.CTkButton(ekle_frame, text="+ Ekle", width=80, height=35, fg_color=RENK_YESIL,
                      hover_color="#27ae60", font=(FONT_ANA, 13, "bold"),
                      command=grup_ekle).pack(side="right")
        yeni_grup_entry.bind("<Return>", lambda e: grup_ekle())

        listeyi_yenile()

    # =========================================================
    # 3. VERESİYE DEFTERİ
    # =========================================================
    def veresiye_ekrani_kur(self):
        self.sekme_veresiye.grid_columnconfigure(0, weight=1)
        self.sekme_veresiye.grid_columnconfigure(1, weight=1)
        self.sekme_veresiye.grid_rowconfigure(1, weight=1)

        # Arama: hem Alacaklar hem Borçlar listesini aynı anda filtreler
        self.veresiye_arama = ctk.CTkEntry(self.sekme_veresiye,
                                           placeholder_text="🔍 Müşteri/Tedarikçi Ara...",
                                           font=(FONT_ANA, 14), height=35)
        self.veresiye_arama.grid(row=0, column=0, columnspan=2, padx=10,
                                 pady=(0, 5), sticky="ew")
        self.veresiye_arama.bind("<KeyRelease>", lambda e: self.veresiye_listele())

        musteri_frame = ctk.CTkFrame(self.sekme_veresiye, fg_color=RENK_PANEL, corner_radius=15)
        musteri_frame.grid(row=1, column=0, padx=10, sticky="nsew")
        ctk.CTkLabel(musteri_frame, text="📙 Müşteri Borçları (Alacaklarım)",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_YESIL).pack(pady=10)
        self.alacak_liste = ctk.CTkScrollableFrame(musteri_frame, fg_color="transparent")
        self.alacak_liste.pack(fill="both", expand=True, padx=5, pady=5)
        self.toplam_alacak_etiket = ctk.CTkLabel(musteri_frame,
                                                   text="Genel Toplam Alacak: 0.00 ₺",
                                                   font=(FONT_ANA, 18, "bold"), text_color=RENK_YESIL)
        self.toplam_alacak_etiket.pack(pady=10)

        toptanci_frame = ctk.CTkFrame(self.sekme_veresiye, fg_color=RENK_PANEL, corner_radius=15)
        toptanci_frame.grid(row=1, column=1, padx=10, sticky="nsew")
        ctk.CTkLabel(toptanci_frame, text="📕 Toptancı / Gider (Borçlarım)",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_KIRMIZI).pack(pady=10)
        self.borc_liste = ctk.CTkScrollableFrame(toptanci_frame, fg_color="transparent")
        self.borc_liste.pack(fill="both", expand=True, padx=5, pady=5)
        self.toplam_borc_etiket = ctk.CTkLabel(toptanci_frame,
                                                text="Genel Toplam Borç: 0.00 ₺",
                                                font=(FONT_ANA, 18, "bold"), text_color=RENK_KIRMIZI)
        self.toplam_borc_etiket.pack(pady=10)

        islem_frame = ctk.CTkFrame(self.sekme_veresiye, fg_color="#222", corner_radius=15)
        islem_frame.grid(row=2, column=0, columnspan=2, pady=10, padx=10, sticky="ew")

        self.v_isim = ctk.CTkEntry(islem_frame, placeholder_text="Kişi / Firma Adı",
                                    width=200, font=(FONT_ANA, 14))
        self.v_isim.pack(side="left", padx=20, pady=15)
        self.v_miktar = ctk.CTkEntry(islem_frame, placeholder_text="Miktar (₺)",
                                      width=150, font=(FONT_ANA, 14))
        self.v_miktar.pack(side="left", padx=10, pady=15)

        ctk.CTkButton(islem_frame, text="+ Alacak Ekle (Manuel)", fg_color=RENK_YESIL,
                      command=lambda: self.veresiye_islem("alacak")).pack(side="left", padx=10)
        ctk.CTkButton(islem_frame, text="- Borç Ekle (Manuel)", fg_color=RENK_KIRMIZI,
                      command=lambda: self.veresiye_islem("borc")).pack(side="left", padx=10)

    def genel_veresiye_toplam_guncelle(self):
        self.c.execute("SELECT SUM(bakiye) FROM Veresiye WHERE tip='alacak' AND bakiye > 0")
        alacak = self.c.fetchone()[0]
        self.toplam_alacak_etiket.configure(
            text=f"Genel Toplam Alacak: {self.format_tl(alacak if alacak else 0)}")

        self.c.execute("SELECT SUM(bakiye) FROM Veresiye WHERE tip='borc' AND bakiye > 0")
        borc = self.c.fetchone()[0]
        self.toplam_borc_etiket.configure(
            text=f"Genel Toplam Borç: {self.format_tl(borc if borc else 0)}")

    def veresiye_listele(self):
        for w in self.alacak_liste.winfo_children():
            w.destroy()
        for w in self.borc_liste.winfo_children():
            w.destroy()

        self.c.execute(
            "SELECT id, isim, tip, bakiye, tarih, detay FROM Veresiye WHERE bakiye > 0")
        tum_satirlar = self.c.fetchall()

        # Arama filtresi: iki listeyi de isim üzerinden aynı anda daraltır
        # (Türkçe İ/I uyumu için _isim_normalize — Borca Yaz aramasıyla aynı mantık)
        aranan = self._isim_normalize(self.veresiye_arama.get().strip())
        if aranan:
            tum_satirlar = [s for s in tum_satirlar
                            if aranan in self._isim_normalize(s[1])]

        alacaklar = [s for s in tum_satirlar if s[2] == "alacak"]
        borclar   = [s for s in tum_satirlar if s[2] == "borc"]

        # Filtre aktifken eşleşme yoksa bilgi mesajı göster
        if aranan:
            for hedef, kayitlar in ((self.alacak_liste, alacaklar),
                                    (self.borc_liste, borclar)):
                if not kayitlar:
                    ctk.CTkLabel(hedef, text="Eşleşen kayıt bulunamadı.",
                                 font=(FONT_ANA, 14), text_color="#aaa").pack(pady=20)

        def tarih_sort_key(satir):
            # NULL tarih → datetime.min → listenin en üstüne çıkar (en riskli)
            tarih_str = satir[4]
            if not tarih_str:
                return datetime.min
            try:
                return datetime.strptime(tarih_str, "%d.%m.%Y %H:%M")
            except ValueError:
                return datetime.min

        # Alacaklar: en ESKİ işlem tarihi en üstte (ASC) — uzun süredir ödenmeyen önce görünsün
        alacaklar.sort(key=tarih_sort_key)
        # Borçlar: bakiye büyükten küçüğe (DESC) — mevcut davranış korunuyor
        borclar.sort(key=lambda s: s[3], reverse=True)

        self.genel_veresiye_toplam_guncelle()
        self._veresiye_satirlari_ciz(alacaklar + borclar, 0)

    def _veresiye_satirlari_ciz(self, satirlar, baslangic, chunk=8):
        """Veresiye satırlarını 8'er 8'er çizer."""
        bitis = min(baslangic + chunk, len(satirlar))
        bugun = datetime.now()
        for v_id, isim, tip, bakiye, tarih, detay in satirlar[baslangic:bitis]:
            hedef_liste = self.alacak_liste if tip == "alacak" else self.borc_liste
            renk        = RENK_YESIL if tip == "alacak" else RENK_KIRMIZI

            # Uyarı: alacak ve son işlem tarihi eşikten eski (ya da tarih hiç girilmemiş)
            uyari = False
            if tip == "alacak":
                if not tarih:
                    uyari = True
                else:
                    try:
                        dt = datetime.strptime(tarih, "%d.%m.%Y %H:%M")
                        uyari = (bugun - dt).days >= VERESIYE_UYARI_GUN_ESIGI
                    except ValueError:
                        uyari = True

            satir = ctk.CTkFrame(hedef_liste, fg_color="#333", corner_radius=8)
            satir.pack(fill="x", pady=3, padx=2)

            ust_frame = ctk.CTkFrame(satir, fg_color="transparent")
            ust_frame.pack(fill="x", padx=5, pady=8)

            isim_text  = f"⚠️ {isim}" if uyari else isim
            isim_renk  = RENK_SARI if uyari else "white"
            ctk.CTkLabel(ust_frame, text=isim_text, text_color=isim_renk,
                         font=(FONT_ANA, 14, "bold")).pack(side="left", padx=5)

            lbl_bakiye = ctk.CTkLabel(ust_frame, text=self.format_tl(bakiye),
                                       font=(FONT_ANA, 14, "bold"), text_color=renk)
            lbl_bakiye.pack(side="left", padx=10)

            ctk.CTkButton(ust_frame, text="İşlem Yap", width=85, height=28,
                          fg_color=RENK_MAVI,
                          command=lambda id=v_id, n=isim, lb=lbl_bakiye, sf=satir:
                              self.veresiye_tahsilat(id, n, lb, sf)).pack(side="right", padx=5)

            ctk.CTkButton(ust_frame, text="📝 Detay", width=70, height=28,
                          fg_color="#555", hover_color="#777",
                          command=lambda vid=v_id, n=isim:
                              self.veresiye_detay_popup(n, vid)).pack(side="right", padx=5)

        if bitis < len(satirlar):
            self.after(10, lambda: self._veresiye_satirlari_ciz(satirlar, bitis, chunk))

    def veresiye_detay_popup(self, isim, v_id):
        self.c.execute("SELECT detay FROM Veresiye WHERE id=?", (v_id,))
        row = self.c.fetchone()
        detay = row[0] if row else None

        pencere = ctk.CTkToplevel(self)
        pencere.title(f"{isim} - Hesap Detayları")
        pencere.geometry("550x450")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text=f"🔍 {isim} - İşlem Geçmişi",
                     font=(FONT_ANA, 18, "bold"), text_color=RENK_MAVI).pack(pady=(15, 10))
        textbox = ctk.CTkTextbox(pencere, font=("Consolas", 14), fg_color="#222")
        textbox.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        if detay:
            for islem in detay.split(" | "):
                textbox.insert("end", f"▪ {islem}\n\n")
        else:
            textbox.insert("end", "Henüz bir işlem geçmişi yok.")
        textbox.configure(state="disabled")

    def veresiye_islem(self, tip):
        isim = self.v_isim.get().upper().strip()
        if not isim:
            return
        tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
        try:
            miktar = self._para_parse(self.v_miktar.get())  # TL → kuruş
            self.c.execute(
                "SELECT bakiye, detay FROM Veresiye WHERE isim=? AND tip=?", (isim, tip))
            mevcut = self.c.fetchone()
            miktar_str = self.format_tl(miktar)
            if mevcut:
                eski_detay = mevcut[1] if mevcut[1] else ""
                yeni_detay = (f"[{tarih}] +{miktar_str} (Manuel Ekleme) | {eski_detay}"
                              if eski_detay else f"[{tarih}] +{miktar_str} (Manuel Ekleme)")
                self.c.execute(
                    "UPDATE Veresiye SET bakiye = bakiye + ?, tarih=?, detay=? WHERE isim=? AND tip=?",
                    (miktar, tarih, yeni_detay, isim, tip))
            else:
                self.c.execute(
                    "INSERT INTO Veresiye (isim, tip, bakiye, tarih, detay) VALUES (?, ?, ?, ?, ?)",
                    (isim, tip, miktar, tarih, f"[{tarih}] +{miktar_str} (Manuel Ekleme)"))
            self.conn.commit()
            self.v_isim.delete(0, "end")
            self.v_miktar.delete(0, "end")
            self.veresiye_listele()
        except ValueError:
            pass

    def veresiye_tahsilat(self, v_id, isim, lbl_bakiye, satir_frame):
        self.c.execute("SELECT bakiye FROM Veresiye WHERE id=?", (v_id,))
        row = self.c.fetchone()
        if not row:
            return
        mevcut_bakiye = row[0]  # kuruş

        pencere = ctk.CTkToplevel(self)
        pencere.title("Hesap İşlemi")
        pencere.geometry("350x280")
        pencere.attributes("-topmost", True)
        pencere.grab_set()

        ctk.CTkLabel(pencere, text=f"{isim}",
                     font=(FONT_ANA, 20, "bold"), text_color=RENK_SARI).pack(pady=(20, 5))
        bakiye_label = ctk.CTkLabel(pencere,
                                     text=f"Mevcut Bakiye: {self.format_tl(mevcut_bakiye)}",
                                     font=(FONT_ANA, 16))
        bakiye_label.pack(pady=(0, 15))

        miktar_entry = ctk.CTkEntry(pencere, placeholder_text="Miktarı girin (₺)...",
                                    font=(FONT_ANA, 16), justify="center")
        miktar_entry.pack(pady=10, padx=30, fill="x")
        miktar_entry.focus()

        uyari = ctk.CTkLabel(pencere, text="", font=(FONT_ANA, 12), text_color=RENK_KIRMIZI)
        uyari.pack()

        btn_frame = ctk.CTkFrame(pencere, fg_color="transparent")
        btn_frame.pack(pady=10, fill="x", padx=20)

        def islem_yap(islem_tipi):
            self.c.execute("SELECT bakiye FROM Veresiye WHERE id=?", (v_id,))
            guncel_row = self.c.fetchone()
            if not guncel_row:
                pencere.destroy()
                return
            guncel_bakiye = guncel_row[0]  # kuruş

            girilen = miktar_entry.get().strip()
            if not girilen:
                uyari.configure(text="Lütfen bir miktar girin!")
                return
            tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
            try:
                miktar = self._para_parse(girilen)  # TL → kuruş
                if islem_tipi == "ekle":
                    yeni_bakiye = guncel_bakiye + miktar
                    yeni_satir = f"[{tarih}] +{self.format_tl(miktar)} Eklendi"
                    self.c.execute(
                        "UPDATE Veresiye SET bakiye=?, tarih=?, "
                        "detay=? || CASE WHEN COALESCE(detay,'')='' THEN '' ELSE ' | ' || detay END "
                        "WHERE id=?",
                        (yeni_bakiye, tarih, yeni_satir, v_id))
                    lbl_bakiye.configure(text=self.format_tl(yeni_bakiye))
                    bakiye_label.configure(text=f"Mevcut Bakiye: {self.format_tl(yeni_bakiye)}")
                else:  # cikar
                    yeni_bakiye = guncel_bakiye - miktar
                    if yeni_bakiye <= 0:  # tam sayı karşılaştırması — güvenilir
                        self.c.execute("DELETE FROM Veresiye WHERE id=?", (v_id,))
                        satir_frame.destroy()
                    else:
                        yeni_satir = f"[{tarih}] -{self.format_tl(miktar)} Tahsil Edildi"
                        self.c.execute(
                            "UPDATE Veresiye SET bakiye=?, tarih=?, "
                            "detay=? || CASE WHEN COALESCE(detay,'')='' THEN '' ELSE ' | ' || detay END "
                            "WHERE id=?",
                            (yeni_bakiye, tarih, yeni_satir, v_id))
                        lbl_bakiye.configure(text=self.format_tl(yeni_bakiye))
                        bakiye_label.configure(text=f"Mevcut Bakiye: {self.format_tl(yeni_bakiye)}")

                self.conn.commit()
                self.genel_veresiye_toplam_guncelle()
                pencere.destroy()
                self.veresiye_listele()
            except ValueError:
                uyari.configure(text="Geçersiz değer! Ondalık için virgül veya nokta kullanın.")

        ctk.CTkButton(btn_frame, text="Borca Ekle (+)", fg_color=RENK_KIRMIZI,
                      hover_color="#c0392b",
                      command=lambda: islem_yap("ekle")).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Tahsil Et (-)", fg_color=RENK_YESIL,
                      hover_color="#27ae60",
                      command=lambda: islem_yap("cikar")).pack(side="right", expand=True, padx=5)

    # =========================================================
    # 4. RAPOR EKRANI
    # =========================================================
    def ozet_ekrani_kur(self):
        self.sekme_ozet.grid_columnconfigure(0, weight=1)
        panel = ctk.CTkFrame(self.sekme_ozet, fg_color=RENK_PANEL, corner_radius=20)
        panel.pack(fill="both", expand=True, padx=20, pady=20)
        ctk.CTkLabel(panel, text="📊 GÜNLÜK RAPOR",
                     font=(FONT_ANA, 24, "bold"), text_color="#bbb").pack(pady=20)

        info_frame = ctk.CTkFrame(panel, fg_color="transparent")
        info_frame.pack(fill="x", padx=20)

        ciro_kart = ctk.CTkFrame(info_frame, fg_color="#222",
                                  border_color=RENK_MAVI, border_width=2)
        ciro_kart.pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(ciro_kart, text="Toplam Ciro", font=(FONT_ANA, 14)).pack(pady=(10, 0))
        self.ciro_etiket = ctk.CTkLabel(ciro_kart, text="0.00 ₺",
                                         font=(FONT_ANA, 28, "bold"), text_color=RENK_MAVI)
        self.ciro_etiket.pack(pady=(0, 10))

        kar_kart = ctk.CTkFrame(info_frame, fg_color="#222",
                                 border_color=RENK_SARI, border_width=2)
        kar_kart.pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(kar_kart, text="Net Kâr", font=(FONT_ANA, 14)).pack(pady=(10, 0))
        self.kar_etiket = ctk.CTkLabel(kar_kart, text="0.00 ₺",
                                        font=(FONT_ANA, 28, "bold"), text_color=RENK_SARI)
        self.kar_etiket.pack(pady=(0, 10))

        ctk.CTkLabel(panel, text="🏆 Bugünün Yıldızları",
                     font=(FONT_ANA, 18, "bold")).pack(pady=(30, 10))
        self.encok_satanlar_liste = ctk.CTkTextbox(panel, height=150,
                                                    fg_color="#222", font=("Consolas", 14))
        self.encok_satanlar_liste.pack(fill="x", padx=30)
        self.encok_satanlar_liste.configure(state="disabled")

        ctk.CTkLabel(panel, text="📅 Geçmiş Kapanış Raporları",
                     font=(FONT_ANA, 16, "bold"), text_color="#aaa").pack(pady=(20, 5))
        self.gecmis_rapor_liste = ctk.CTkTextbox(panel, height=100,
                                                  fg_color="#1a1a1a", font=("Consolas", 12))
        self.gecmis_rapor_liste.pack(fill="x", padx=30)
        self.gecmis_rapor_liste.configure(state="disabled")

        ctk.CTkButton(panel, text="🌙 GÜNÜ KAPAT (Z RAPORU)",
                      fg_color=RENK_KIRMIZI, hover_color="#c0392b", height=50,
                      font=(FONT_ANA, 16, "bold"),
                      command=self.gunu_kapat).pack(pady=20, padx=30, fill="x")
        self.kapanis_etiketi = ctk.CTkLabel(panel, text="")
        self.kapanis_etiketi.pack()

    def ozet_guncelle(self):
        self.c.execute("SELECT ciro, kar FROM Gunluk WHERE id=1")
        veri = self.c.fetchone()
        if veri:
            self.ciro_etiket.configure(text=self.format_tl(veri[0]))
            self.kar_etiket.configure(text=self.format_tl(veri[1]))

        self.c.execute(
            "SELECT isim, satilan_adet FROM Urunler WHERE satilan_adet > 0 "
            "ORDER BY satilan_adet DESC LIMIT 5")
        satanlar = self.c.fetchall()

        self.encok_satanlar_liste.configure(state="normal")
        self.encok_satanlar_liste.delete("1.0", "end")
        for i, (isim, adet) in enumerate(satanlar, 1):
            self.encok_satanlar_liste.insert("end", f"{i}. {isim:<20} -> {adet} Adet\n")
        self.encok_satanlar_liste.configure(state="disabled")

        self.c.execute(
            "SELECT tarih, ciro, kar FROM GunlukGecmis ORDER BY id DESC LIMIT 7")
        gecmis = self.c.fetchall()
        self.gecmis_rapor_liste.configure(state="normal")
        self.gecmis_rapor_liste.delete("1.0", "end")
        if gecmis:
            for tarih, ciro, kar in gecmis:
                self.gecmis_rapor_liste.insert(
                    "end",
                    f"📅 {tarih}  |  Ciro: {self.format_tl(ciro)}  |  Kâr: {self.format_tl(kar)}\n")
        else:
            self.gecmis_rapor_liste.insert("end", "Henüz kapanış raporu yok.\n")
        self.gecmis_rapor_liste.configure(state="disabled")

    def gunu_kapat(self):
        self.c.execute("SELECT ciro, kar FROM Gunluk WHERE id=1")
        veri = self.c.fetchone()
        if veri and veri[0] > 0:
            tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
            self.c.execute(
                "INSERT INTO GunlukGecmis (tarih, ciro, kar) VALUES (?, ?, ?)",
                (tarih, veri[0], veri[1]))

        self.c.execute("UPDATE Gunluk SET ciro = 0, kar = 0 WHERE id=1")
        self.c.execute("UPDATE Urunler SET satilan_adet = 0")
        self.conn.commit()
        self.ozet_guncelle()
        self.kapanis_etiketi.configure(text="✅ GÜN KAPATILDI!", text_color=RENK_YESIL)
        self.after(3000, lambda: self.kapanis_etiketi.configure(text=""))


if __name__ == "__main__":
    uygulama = BufeSistemi()
    uygulama.mainloop()
